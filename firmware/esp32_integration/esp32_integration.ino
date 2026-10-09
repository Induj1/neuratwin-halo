// ============================================================
// NeuraTwin Halo - ESP32 backend integration firmware
//
// Derived from the bench-tested hardware/esp32.ino. The measurement,
// calibration and relay code is kept as-is; the built-in HTML dashboard
// is replaced by a JSON API that the NeuraTwin backend polls and commands.
//
// Arduino IDE: this file must live in a folder named "esp32_integration".
// Board: ESP32 Dev Module. Libraries: ArduinoJson (v7), OneWire,
// DallasTemperature (WiFi, WebServer, ESPmDNS, Preferences ship with core).
//
// HTTP API (all JSON; mutating calls take a JSON body)
//   GET  /healthz           liveness: wifi, uptime, probe status  (no auth)
//   GET  /api/readings      primary/secondary V & I, temperature, loads, raw
//   GET  /api/loads         load 1/2/4 states
//   POST /api/loads         {"load":1,"state":true}
//                           or {"load1":true,"load2":false,"load4":true}
//   GET  /api/calibration   factors, sensitivity, method, status
//   POST /api/calibration   {"action":"<name>","value":<number>}
//        actions: mains_voltage(value=V), secondary_voltage(value=V),
//                 current_meter(value=A), sensor_model(value=66|100|185),
//                 auto, zero, reset, step_test
//
// Auth: when API_TOKEN is non-empty every route except /healthz requires
//       "Authorization: Bearer <API_TOKEN>". Use the same value as
//       HALO_DEVICE_TOKEN in the backend .env.
//
// Calibration actions block for 3-15 s (relays click); give the HTTP
// client a timeout of at least 30 s.
// ============================================================

#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <ArduinoJson.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Preferences.h>
#include <math.h>
#include <string.h>
#include <stdarg.h>

// ============================================================
// NETWORK / IDENTITY - EDIT THESE
// ============================================================

const char* WIFI_SSID     = "YOUR_SSID";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";

const char* DEVICE_ID     = "HALO-ESP32";     // must equal the backend's configured device_id
const char* MDNS_HOSTNAME = "halo-esp32";     // reachable as http://halo-esp32.local
const char* API_TOKEN     = "YOUR_TOKEN";     // paste HALO_DEVICE_TOKEN from .env; empty = no auth (LAN dev only)
const uint16_t HTTP_PORT  = 80;

const unsigned long WIFI_BOOT_WAIT_MS     = 20000;  // wait this long at boot, then carry on
const unsigned long WIFI_RETRY_INTERVAL_MS = 10000; // reconnect attempts while running

WebServer server(HTTP_PORT);
Preferences preferences;

// ============================================================
// ESP32 DEV MODULE PIN MAPPING - UNCHANGED FROM TESTED CIRCUIT
// ============================================================

#define ZMPT_MAINS_PIN       32
#define ZMPT_SECONDARY_PIN   34

#define ACS_MAINS_PIN        33
#define ACS_SECONDARY_PIN    35

#define ONE_WIRE_PIN         4

#define RELAY_1_PIN          14
#define RELAY_2_PIN          15
// GPIO18 / Relay I3 intentionally ignored.
#define RELAY_4_PIN          19

// ============================================================
// MEASUREMENT SETTINGS - UNCHANGED
// ============================================================

const float MAINS_FREQUENCY_HZ = 50.0;

const int UPDATE_CYCLES = 20;          // 400 ms per update
const int CAL_CYCLES    = 100;         // 2 s per calibration measurement

const unsigned long UPDATE_INTERVAL_MS = 1500;

const float MAINS_PRESENT_V     = 50.0;
const float SECONDARY_PRESENT_V = 1.5;

const float SECONDARY_CURRENT_DEADBAND_A = 0.03;
const float MAINS_CURRENT_DEADBAND_A     = 0.002;

const float LOAD_RESISTANCE_OHM     = 39.0;
const float TRANSFORMER_EFFICIENCY  = 0.80;

const bool USE_MEASURED_MAINS_CURRENT = false;

const float ADC_MV_PER_COUNT = 3300.0 / 4095.0;
const int   ADC_SETTLE_READS = 1;

const unsigned long RELAY_SETTLE_MS = 2000;
const float ZERO_TRACK_ALPHA = 0.3;

const float MIN_LOAD_SIGNAL_MV = 2.0;

// Run the 39 ohm auto-calibration once when mains is first seen and no
// current calibration is stored. Same behaviour as the tested sketch.
const bool AUTO_CALIBRATE_ON_FIRST_MAINS = true;

// Current calibration methods (saved in flash).
const int32_t CAL_NONE  = 0;
const int32_t CAL_OHM   = 1;
const int32_t CAL_METER = 2;
const int32_t CAL_MODEL = 3;

// ============================================================
// TYPES
// ============================================================

struct Cpx
{
    float re;
    float im;
};

struct Calibration
{
    float   vMainsFactor;
    float   vSecFactor;
    float   iSecSens;
    float   iMainsSens;
    Cpx     kIs;
    Cpx     kIm;
    int32_t iCalMethod;
};

enum { CH_VS = 0, CH_IS = 1, CH_VM = 2, CH_IM = 3 };

const int CH_PINS[4] =
{
    ZMPT_SECONDARY_PIN,
    ACS_SECONDARY_PIN,
    ZMPT_MAINS_PIN,
    ACS_MAINS_PIN
};

struct Measurement
{
    float mean[4];
    float acRms[4];
    Cpx   ph[4];
    float fund[4];
    float minV[4];
    float maxV[4];
    uint32_t samples;
};

struct Readings
{
    bool  mainsPresent;
    float mainsV;
    float secV;
    float mainsI;
    float secI;
    float mainsIMeasured;
    float vmFund_mV;
    float vsFund_mV;
    float isFund_mV;
    float isCorr_mV;
    float imCorr_mV;
    float expectedSecI;
};

// ============================================================
// GLOBAL STATE
// ============================================================

Calibration cal;

OneWire oneWire(ONE_WIRE_PIN);
DallasTemperature temperatureSensor(&oneWire);

const bool RELAY_ACTIVE_LOW = true;

bool load1State = true;
bool load2State = true;
bool load4State = false;

float mainsVoltage = 0.0;
float secondaryVoltage = 0.0;
float mainsCurrent = 0.0;
float secondaryCurrent = 0.0;
float expectedSecondaryCurrent = 0.0;
float transformerTemperature = -127.0;

unsigned long lastSensorUpdate = 0;
unsigned long lastRelayChangeMs = 0;
unsigned long lastWifiAttemptMs = 0;

bool autoCalDone = false;
bool zeroTrackingActive = false;
bool currentSensorOk = false;
String calStatus = "Current not calibrated yet";

Measurement lastM;
Readings lastR;

String opLog;
String bootId;
uint32_t sequence = 0;
bool temperatureProbeOk = false;

// ============================================================
// LOGGING (Serial + text returned in API responses)
// ============================================================

void reportf(const char* fmt, ...)
{
    char buf[220];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);

    Serial.println(buf);
    opLog += buf;
    opLog += "\n";
}

// ============================================================
// COMPLEX HELPERS
// ============================================================

float cAbs(Cpx a)
{
    return sqrtf(a.re * a.re + a.im * a.im);
}

Cpx cMul(Cpx a, Cpx b)
{
    Cpx r;
    r.re = a.re * b.re - a.im * b.im;
    r.im = a.re * b.im + a.im * b.re;
    return r;
}

Cpx cSub(Cpx a, Cpx b)
{
    Cpx r;
    r.re = a.re - b.re;
    r.im = a.im - b.im;
    return r;
}

Cpx cDiv(Cpx a, Cpx b)
{
    Cpx r;
    float d = b.re * b.re + b.im * b.im;

    if (d < 1e-9)
    {
        r.re = 0.0;
        r.im = 0.0;
        return r;
    }

    r.re = (a.re * b.re + a.im * b.im) / d;
    r.im = (a.im * b.re - a.re * b.im) / d;
    return r;
}

// ============================================================
// CALIBRATION DEFAULTS
// ============================================================

void setDefaultCalibration()
{
    cal.vMainsFactor = 0.58;
    cal.vSecFactor   = 0.555;

    cal.iSecSens   = 100.0;
    cal.iMainsSens = 100.0;

    cal.kIs.re = 0.0; cal.kIs.im = 0.0;
    cal.kIm.re = 0.0; cal.kIm.im = 0.0;

    cal.iCalMethod = CAL_NONE;
}

const char* calMethodName(int32_t method)
{
    switch (method)
    {
        case CAL_OHM:   return "ohm";
        case CAL_METER: return "meter";
        case CAL_MODEL: return "model";
        default:        return "none";
    }
}

void refreshCalStatus()
{
    String s = String(cal.iSecSens, 1) + " mV/A";

    if (cal.iCalMethod == CAL_OHM)
    {
        currentSensorOk = true;
        calStatus = "OK: current calibrated with 39 ohm loads (" + s + ")";
    }
    else if (cal.iCalMethod == CAL_METER)
    {
        currentSensorOk = true;
        calStatus = "OK: current calibrated with ammeter (" + s + ")";
    }
    else if (cal.iCalMethod == CAL_MODEL)
    {
        currentSensorOk = true;
        calStatus = "Current sensitivity set from sensor type (" + s + ")";
    }
    else
    {
        currentSensorOk = false;
        calStatus = "Current not calibrated yet";
    }
}

// ============================================================
// RELAY CONTROL
// ============================================================

void setRelay(int pin, bool state)
{
    if (RELAY_ACTIVE_LOW)
    {
        digitalWrite(pin, state ? LOW : HIGH);
    }
    else
    {
        digitalWrite(pin, state ? HIGH : LOW);
    }
}

void updateRelays()
{
    setRelay(RELAY_1_PIN, load1State);
    setRelay(RELAY_2_PIN, load2State);
    setRelay(RELAY_4_PIN, load4State);

    lastRelayChangeMs = millis();
}

int loadsOn()
{
    return (load1State ? 1 : 0) + (load2State ? 1 : 0) + (load4State ? 1 : 0);
}

// ============================================================
// ADC READ WITH CHANNEL SETTLING
// ============================================================

float readPin_mV(int pin)
{
    for (int i = 0; i < ADC_SETTLE_READS; i++)
    {
        analogRead(pin);
    }

    return analogRead(pin) * ADC_MV_PER_COUNT;
}

// ============================================================
// 50 Hz LOCK-IN MEASUREMENT OF ALL FOUR CHANNELS
// ============================================================

Measurement sampleAll(int cycles)
{
    double sum[4]   = {0, 0, 0, 0};
    double sumSq[4] = {0, 0, 0, 0};
    double sumC[4]  = {0, 0, 0, 0};
    double sumS[4]  = {0, 0, 0, 0};
    double sc = 0.0;
    double ss = 0.0;

    float mn[4] = {1e9, 1e9, 1e9, 1e9};
    float mx[4] = {-1e9, -1e9, -1e9, -1e9};

    uint32_t n = 0;

    const uint32_t windowUs =
        (uint32_t)(1000000.0 * cycles / MAINS_FREQUENCY_HZ);

    const uint32_t periodUs =
        (uint32_t)(1000000.0 / MAINS_FREQUENCY_HZ);

    const uint32_t start = micros();

    while (true)
    {
        uint32_t elapsed = micros() - start;

        if (elapsed >= windowUs)
        {
            break;
        }

        float phase = TWO_PI * (float)(elapsed % periodUs) / (float)periodUs;
        float c = cosf(phase);
        float s = sinf(phase);

        for (int ch = 0; ch < 4; ch++)
        {
            float x = readPin_mV(CH_PINS[ch]);

            sum[ch]   += x;
            sumSq[ch] += (double)x * x;
            sumC[ch]  += (double)x * c;
            sumS[ch]  += (double)x * s;

            if (x < mn[ch]) mn[ch] = x;
            if (x > mx[ch]) mx[ch] = x;
        }

        sc += c;
        ss += s;
        n++;
    }

    Measurement m;
    memset(&m, 0, sizeof(m));
    m.samples = n;

    if (n == 0)
    {
        return m;
    }

    for (int ch = 0; ch < 4; ch++)
    {
        double mean = sum[ch] / n;
        double var  = sumSq[ch] / n - mean * mean;

        double I = (sumC[ch] - mean * sc) / n;
        double Q = (sumS[ch] - mean * ss) / n;

        m.mean[ch]  = (float)mean;
        m.acRms[ch] = (float)sqrt(var > 0.0 ? var : 0.0);

        m.ph[ch].re = (float)(M_SQRT2 * I);
        m.ph[ch].im = (float)(M_SQRT2 * Q);
        m.fund[ch]  = cAbs(m.ph[ch]);

        m.minV[ch] = mn[ch];
        m.maxV[ch] = mx[ch];
    }

    return m;
}

// ============================================================
// CONVERSION TO ENGINEERING UNITS
// ============================================================

Readings computeReadings(const Measurement& m)
{
    Readings r;
    memset(&r, 0, sizeof(r));

    r.vmFund_mV = m.fund[CH_VM];
    r.mainsV = cal.vMainsFactor * r.vmFund_mV;
    r.mainsPresent = (r.mainsV >= MAINS_PRESENT_V);

    if (!r.mainsPresent)
    {
        memset(&r, 0, sizeof(r));
        r.vmFund_mV = m.fund[CH_VM];
        return r;
    }

    r.vsFund_mV = m.fund[CH_VS];
    r.secV = cal.vSecFactor * r.vsFund_mV;

    if (r.secV < SECONDARY_PRESENT_V)
    {
        r.secV = 0.0;
    }

    r.isFund_mV = m.fund[CH_IS];

    Cpx isCorr = cSub(m.ph[CH_IS], cMul(cal.kIs, m.ph[CH_VM]));
    r.isCorr_mV = cAbs(isCorr);

    r.secI = r.isCorr_mV / cal.iSecSens;

    if (r.secV == 0.0 || r.secI < SECONDARY_CURRENT_DEADBAND_A)
    {
        r.secI = 0.0;
    }

    Cpx imCorr = cSub(m.ph[CH_IM], cMul(cal.kIm, m.ph[CH_VM]));
    r.imCorr_mV = cAbs(imCorr);
    r.mainsIMeasured = r.imCorr_mV / cal.iMainsSens;

    float pSec = r.secV * r.secI;
    float ipCalc = pSec / (TRANSFORMER_EFFICIENCY * r.mainsV);

    r.mainsI = USE_MEASURED_MAINS_CURRENT ? r.mainsIMeasured : ipCalc;

    if (r.mainsI < MAINS_CURRENT_DEADBAND_A)
    {
        r.mainsI = 0.0;
    }

    r.expectedSecI = r.secV * loadsOn() / LOAD_RESISTANCE_OHM;

    return r;
}

// ============================================================
// TEMPERATURE - UNCHANGED
// ============================================================

float readTemperature()
{
    temperatureSensor.requestTemperatures();

    float temperature =
        temperatureSensor.getTempCByIndex(0);

    if (temperature == DEVICE_DISCONNECTED_C)
    {
        return -127.0;
    }

    return temperature;
}

// ============================================================
// CALIBRATION STORAGE
// ============================================================

bool inRange(float v, float lo, float hi)
{
    return isfinite(v) && v >= lo && v <= hi;
}

bool calibrationValid()
{
    return inRange(cal.vMainsFactor, 0.05, 5.0) &&
           inRange(cal.vSecFactor, 0.05, 5.0) &&
           inRange(cal.iSecSens, 10.0, 1000.0) &&
           inRange(cal.iMainsSens, 10.0, 1000.0) &&
           inRange(cAbs(cal.kIs), 0.0, 1.0) &&
           inRange(cAbs(cal.kIm), 0.0, 1.0) &&
           cal.iCalMethod >= CAL_NONE && cal.iCalMethod <= CAL_MODEL;
}

void saveCalibration()
{
    size_t written = preferences.putBytes("cal", &cal, sizeof(cal));

    if (written != sizeof(cal))
    {
        reportf("WARNING: calibration could not be saved to flash.");
    }
}

void loadCalibration()
{
    // Same namespace as the tested sketch so an already-calibrated board
    // keeps its values after flashing this firmware.
    preferences.begin("xfmrmon8", false);

    setDefaultCalibration();

    if (preferences.getBytesLength("cal") == sizeof(cal))
    {
        preferences.getBytes("cal", &cal, sizeof(cal));

        if (!calibrationValid())
        {
            Serial.println("Stored calibration invalid. Using defaults.");
            setDefaultCalibration();
        }
    }

    refreshCalStatus();
}

// ============================================================
// CALIBRATION ROUTINES - UNCHANGED
// ============================================================

bool requireMains()
{
    Measurement m = sampleAll(UPDATE_CYCLES);

    if (!computeReadings(m).mainsPresent)
    {
        reportf("Aborted: mains is OFF. Switch mains ON first.");
        return false;
    }

    return true;
}

bool calibrateCrosstalk()
{
    if (!requireMains()) return false;

    bool s1 = load1State, s2 = load2State, s4 = load4State;

    reportf("Zero offset: all loads OFF, measuring 2 s...");

    load1State = false;
    load2State = false;
    load4State = false;
    updateRelays();

    delay(1500);

    Measurement m = sampleAll(CAL_CYCLES);

    load1State = s1;
    load2State = s2;
    load4State = s4;
    updateRelays();

    if (m.fund[CH_VM] < 20.0)
    {
        reportf("Zero offset failed: mains reference signal too small.");
        return false;
    }

    cal.kIs = cDiv(m.ph[CH_IS], m.ph[CH_VM]);
    cal.kIm = cDiv(m.ph[CH_IM], m.ph[CH_VM]);

    saveCalibration();

    reportf("No-load signal on current sensor: %.2f mV (removed). Loads restored.",
            m.fund[CH_IS]);

    return true;
}

bool calibrateVoltage(bool mainsChannel, float referenceV)
{
    if (!inRange(referenceV, 0.5, 300.0))
    {
        reportf("Invalid reference voltage.");
        return false;
    }

    if (!requireMains()) return false;

    Measurement m = sampleAll(CAL_CYCLES);

    float sig = mainsChannel ? m.fund[CH_VM] : m.fund[CH_VS];

    if (sig < 3.0)
    {
        reportf("Calibration failed: 50 Hz signal only %.2f mV.", sig);
        return false;
    }

    float factor = referenceV / sig;

    if (!inRange(factor, 0.05, 5.0))
    {
        reportf("Calibration rejected: implausible factor %.4f", factor);
        return false;
    }

    if (mainsChannel) cal.vMainsFactor = factor;
    else              cal.vSecFactor = factor;

    saveCalibration();

    reportf("%s calibrated to %.2f V (signal %.2f mV, factor %.4f). Saved.",
            mainsChannel ? "Mains" : "Secondary", referenceV, sig, factor);

    return true;
}

bool applySecondarySensitivity(const Readings& r, float referenceA, int32_t method)
{
    if (!r.mainsPresent || r.secV == 0.0)
    {
        reportf("Current calibration failed: secondary voltage not present.");
        return false;
    }

    if (!inRange(referenceA, 0.02, 30.0))
    {
        reportf("Invalid reference current.");
        return false;
    }

    if (r.isCorr_mV < MIN_LOAD_SIGNAL_MV)
    {
        currentSensorOk = false;
        calStatus = "FAULT: current sensor sees no load current. Check relays and ACS712 wiring.";
        reportf("Current calibration FAILED: load signal only %.2f mV for %.3f A.",
                r.isCorr_mV, referenceA);
        reportf("Either the loads are not switching, or the ACS712 is not");
        reportf("in series with the common load return wire.");
        return false;
    }

    float sens = r.isCorr_mV / referenceA;

    if (!inRange(sens, 10.0, 1000.0))
    {
        currentSensorOk = false;
        calStatus = "FAULT: implausible current sensor sensitivity.";
        reportf("Current calibration rejected: sensitivity %.2f mV/A is implausible.", sens);
        return false;
    }

    cal.iSecSens = sens;
    cal.iCalMethod = method;
    saveCalibration();
    refreshCalStatus();

    reportf("Reference %.3f A, load signal %.2f mV, sensitivity %.2f mV/A. Saved.",
            referenceA, r.isCorr_mV, sens);

    return true;
}

bool calibrateSecondaryCurrentMeter(float referenceA)
{
    if (!inRange(referenceA, 0.02, 30.0))
    {
        reportf("Invalid ammeter reading.");
        return false;
    }

    if (loadsOn() == 0)
    {
        reportf("Switch at least one load ON first.");
        return false;
    }

    if (!calibrateCrosstalk()) return false;

    delay(1500);

    Measurement m = sampleAll(CAL_CYCLES);
    Readings r = computeReadings(m);

    return applySecondarySensitivity(r, referenceA, CAL_METER);
}

bool calibrateSecondaryCurrentOhm()
{
    int n = loadsOn();

    if (n == 0)
    {
        reportf("Needs at least one load ON.");
        return false;
    }

    if (!requireMains()) return false;

    Measurement m = sampleAll(CAL_CYCLES);
    Readings r = computeReadings(m);

    float referenceA = r.secV * n / LOAD_RESISTANCE_OHM;

    reportf("Vsec %.2f V x %d loads / %.0f ohm = %.3f A reference",
            r.secV, n, LOAD_RESISTANCE_OHM, referenceA);

    return applySecondarySensitivity(r, referenceA, CAL_OHM);
}

bool autoCalibrate()
{
    reportf("===== AUTO CALIBRATION (39 ohm loads) =====");

    if (!calibrateCrosstalk())
    {
        reportf("Auto calibration stopped.");
        return false;
    }

    bool s1 = load1State, s2 = load2State, s4 = load4State;

    reportf("Load 1 + Load 2 ON for current calibration...");

    load1State = true;
    load2State = true;
    load4State = false;
    updateRelays();

    delay(1500);

    bool ok = calibrateSecondaryCurrentOhm();

    load1State = s1;
    load2State = s2;
    load4State = s4;
    updateRelays();

    reportf(ok ? "Auto calibration finished OK." : "Auto calibration: current step FAILED.");

    return ok;
}

bool setSensorModel(float sens)
{
    if (!(fabs(sens - 66.0) < 0.5 || fabs(sens - 100.0) < 0.5 || fabs(sens - 185.0) < 0.5))
    {
        reportf("Unknown sensor type. Use 66, 100 or 185 mV/A.");
        return false;
    }

    cal.iSecSens = sens;
    cal.iCalMethod = CAL_MODEL;
    saveCalibration();
    refreshCalStatus();

    reportf("Current sensitivity set to %.0f mV/A from sensor type. Saved.", sens);
    reportf("Run the zero action with mains ON for best accuracy.");

    return true;
}

void resetCalibration()
{
    setDefaultCalibration();
    saveCalibration();
    refreshCalStatus();
    autoCalDone = false;

    reportf("All calibration reset to defaults. Saved.");
    reportf("Auto calibration will run again when mains is detected.");
}

// ============================================================
// LOAD STEP TEST - UNCHANGED
// ============================================================

void runLoadStepTest()
{
    if (!requireMains()) return;

    bool s1 = load1State, s2 = load2State, s4 = load4State;

    const bool cfg[4][3] =
    {
        {false, false, false},
        {true,  false, false},
        {true,  true,  false},
        {true,  true,  true }
    };

    reportf("Loads | Vmains | Vsec  | Isec   | Expected | ACS raw mV | ACS load mV");

    float firstRaw = 0.0, lastRaw = 0.0;

    for (int i = 0; i < 4; i++)
    {
        load1State = cfg[i][0];
        load2State = cfg[i][1];
        load4State = cfg[i][2];
        updateRelays();

        delay(1500);

        Measurement m = sampleAll(CAL_CYCLES);
        Readings r = computeReadings(m);

        if (i == 0) firstRaw = r.isFund_mV;
        if (i == 3) lastRaw = r.isFund_mV;

        reportf("  %d   | %6.1f | %5.2f | %6.3f |  %6.3f  |  %7.2f   |  %7.2f",
                loadsOn(), r.mainsV, r.secV, r.secI, r.expectedSecI,
                r.isFund_mV, r.isCorr_mV);
    }

    load1State = s1;
    load2State = s2;
    load4State = s4;
    updateRelays();

    reportf("");
    reportf("ACS raw signal change from 0 to 3 loads: %.2f mV", fabs(lastRaw - firstRaw));
    reportf("With the ACS712 in the load path this should be tens of mV.");
    reportf("If it is near 0, the sensor is not seeing the load current.");
}

// ============================================================
// SERIAL COMMANDS (bench fallback; the API does the same)
// ============================================================

void processSerialCommands()
{
    if (!Serial.available())
    {
        return;
    }

    String command = Serial.readStringUntil('\n');
    command.trim();
    command.toUpperCase();

    if (command.length() == 0) return;

    opLog = "";

    if (command == "AUTOCAL")         { autoCalibrate(); autoCalDone = true; return; }
    if (command == "ZERO")            { calibrateCrosstalk(); return; }
    if (command == "STEP")            { runLoadStepTest(); return; }
    if (command == "RESET")           { resetCalibration(); return; }
    if (command == "IP")              { Serial.println(WiFi.localIP()); return; }
    if (command.startsWith("CALVM ")) { calibrateVoltage(true, command.substring(6).toFloat()); return; }
    if (command.startsWith("CALVS ")) { calibrateVoltage(false, command.substring(6).toFloat()); return; }
    if (command.startsWith("CALIS ")) { calibrateSecondaryCurrentMeter(command.substring(6).toFloat()); return; }

    Serial.println("Commands: AUTOCAL, ZERO, STEP, CALVM <V>, CALVS <V>, CALIS <A>, RESET, IP");
}

// ============================================================
// LIGHT SMOOTHING
// ============================================================

float smoothValue(float previous, float current, float alpha)
{
    if (current == 0.0) return 0.0;
    if (previous == 0.0) return current;
    return previous + alpha * (current - previous);
}

// ============================================================
// AUTOMATIC OFFSET TRACKING WHILE ALL LOADS ARE OFF
// ============================================================

void trackZeroOffset(const Measurement& m, const Readings& r)
{
    zeroTrackingActive = false;

    if (!r.mainsPresent) return;
    if (loadsOn() != 0) return;
    if (millis() - lastRelayChangeMs < RELAY_SETTLE_MS) return;
    if (m.fund[CH_VM] < 20.0) return;

    Cpx kNew = cDiv(m.ph[CH_IS], m.ph[CH_VM]);

    cal.kIs.re += ZERO_TRACK_ALPHA * (kNew.re - cal.kIs.re);
    cal.kIs.im += ZERO_TRACK_ALPHA * (kNew.im - cal.kIs.im);

    zeroTrackingActive = true;
}

// ============================================================
// SERIAL DIAGNOSTICS
// ============================================================

void printDiagnostics(const Measurement& m, const Readings& r)
{
    Serial.printf("#%lu Vm %.1f V (%.1f mV) | Vs %.2f V (%.2f mV) | Is %.3f A (raw %.2f, load %.2f mV) | exp %.3f A | T %.1f C | %s\n",
                  (unsigned long)sequence,
                  r.mainsV, m.fund[CH_VM], r.secV, m.fund[CH_VS],
                  r.secI, m.fund[CH_IS], r.isCorr_mV, r.expectedSecI,
                  transformerTemperature, calStatus.c_str());
}

// ============================================================
// READ ALL SENSORS
// ============================================================

void updateSensors()
{
    Measurement m = sampleAll(UPDATE_CYCLES);
    Readings r = computeReadings(m);

    // Automatic current calibration only if never calibrated before.
    if (AUTO_CALIBRATE_ON_FIRST_MAINS && r.mainsPresent && !autoCalDone && cal.iCalMethod == CAL_NONE)
    {
        opLog = "";
        autoCalibrate();

        m = sampleAll(UPDATE_CYCLES);
        r = computeReadings(m);
    }

    if (r.mainsPresent)
    {
        autoCalDone = true;
    }

    trackZeroOffset(m, r);

    mainsVoltage     = smoothValue(mainsVoltage,     r.mainsV, 0.5);
    secondaryVoltage = smoothValue(secondaryVoltage, r.secV,   0.5);
    mainsCurrent     = smoothValue(mainsCurrent,     r.mainsI, 0.5);
    secondaryCurrent = smoothValue(secondaryCurrent, r.secI,   0.5);
    expectedSecondaryCurrent = r.expectedSecI;

    transformerTemperature = readTemperature();
    temperatureProbeOk = (transformerTemperature != -127.0 && transformerTemperature != 85.0 &&
                          isfinite(transformerTemperature) &&
                          transformerTemperature > -55.0 && transformerTemperature < 125.0);

    lastM = m;
    lastR = r;
    sequence++;

    printDiagnostics(m, r);
}

// ============================================================
// HTTP HELPERS
// ============================================================

void sendJson(int code, JsonDocument& doc)
{
    String out;
    serializeJson(doc, out);
    server.sendHeader("Cache-Control", "no-store");
    server.send(code, "application/json", out);
}

void sendError(int code, const char* message)
{
    JsonDocument doc;
    doc["ok"] = false;
    doc["error"] = message;
    sendJson(code, doc);
}

// Constant-time string compare so token length/prefix is not leaked by timing.
bool tokenMatches(const String& supplied, const char* expected)
{
    size_t n = strlen(expected);
    if (supplied.length() != n) return false;

    unsigned char diff = 0;
    for (size_t i = 0; i < n; i++)
    {
        diff |= (unsigned char)(supplied[i] ^ expected[i]);
    }
    return diff == 0;
}

bool requireAuth()
{
    if (strlen(API_TOKEN) == 0) return true;

    String header = server.header("Authorization");
    if (!header.startsWith("Bearer "))
    {
        sendError(401, "Bearer token required.");
        return false;
    }

    if (!tokenMatches(header.substring(7), API_TOKEN))
    {
        sendError(401, "Invalid token.");
        return false;
    }

    return true;
}

bool parseBody(JsonDocument& doc)
{
    if (!server.hasArg("plain") || server.arg("plain").length() == 0)
    {
        sendError(400, "JSON body required.");
        return false;
    }

    if (deserializeJson(doc, server.arg("plain")))
    {
        sendError(400, "Invalid JSON body.");
        return false;
    }

    return true;
}

// ============================================================
// JSON BUILDERS
// ============================================================

void fillLoads(JsonObject o)
{
    o["load1"] = load1State;
    o["load2"] = load2State;
    o["load4"] = load4State;
    o["loads_on"] = loadsOn();

    // Backend relay_states tuple: [K1, K2, K3, K4]. K3 is not wired in this build.
    JsonArray states = o["relay_states"].to<JsonArray>();
    states.add(load1State);
    states.add(load2State);
    states.add(false);
    states.add(load4State);
}

void fillCalibration(JsonObject o)
{
    o["mains_v_factor"]     = cal.vMainsFactor;
    o["secondary_v_factor"] = cal.vSecFactor;
    o["secondary_i_sens_mv_per_a"] = cal.iSecSens;
    o["mains_i_sens_mv_per_a"]     = cal.iMainsSens;
    o["crosstalk_k_is"]     = cAbs(cal.kIs);
    o["crosstalk_k_im"]     = cAbs(cal.kIm);
    o["current_method"]     = calMethodName(cal.iCalMethod);
    o["current_calibrated"] = currentSensorOk;
    o["status"]             = calStatus;
    o["zero_tracking_active"] = zeroTrackingActive;
    o["auto_calibration_done"] = autoCalDone;
}

void fillReadings(JsonObject o)
{
    o["device_id"] = DEVICE_ID;
    o["boot_id"]   = bootId;
    o["sequence"]  = sequence;
    o["uptime_ms"] = millis();
    o["mains_present"] = lastR.mainsPresent;

    // Primary = mains side, secondary = load side. Units: V RMS, A RMS, degC.
    o["primary_v"]           = mainsVoltage;
    o["primary_current_a"]   = mainsCurrent;
    o["primary_current_method"] = USE_MEASURED_MAINS_CURRENT ? "measured" : "calculated";
    o["primary_current_measured_a"] = lastR.mainsIMeasured;

    o["secondary_v"]         = secondaryVoltage;
    o["current_a"]           = secondaryCurrent;
    o["expected_current_a"]  = expectedSecondaryCurrent;

    if (temperatureProbeOk) o["surface_c"] = transformerTemperature;
    else                    o["surface_c"] = nullptr;
    o["temperature_probe_ok"] = temperatureProbeOk;

    o["current_calibrated"] = currentSensorOk;
    o["calibration_status"] = calStatus;
    o["relay_output_configured"] = true;

    fillLoads(o["loads"].to<JsonObject>());
    JsonArray states = o["relay_states"].to<JsonArray>();
    states.add(load1State);
    states.add(load2State);
    states.add(false);
    states.add(load4State);

    JsonArray flags = o["quality_flags"].to<JsonArray>();
    if (!lastR.mainsPresent)  flags.add("mains_absent");
    if (!temperatureProbeOk)  flags.add("surface_invalid");
    if (!currentSensorOk)     flags.add("current_uncalibrated");
    if (lastM.samples < 200)  flags.add("sampling_short");

    JsonObject raw = o["raw"].to<JsonObject>();
    raw["primary_fund_mv"]    = lastM.fund[CH_VM];
    raw["secondary_fund_mv"]  = lastM.fund[CH_VS];
    raw["current_raw_mv"]     = lastM.fund[CH_IS];
    raw["current_corr_mv"]    = lastR.isCorr_mV;
    raw["current_dc_mv"]      = lastM.mean[CH_IS];
    raw["primary_current_raw_mv"]  = lastM.fund[CH_IM];
    raw["primary_current_corr_mv"] = lastR.imCorr_mV;
    raw["samples"]            = lastM.samples;
}

// ============================================================
// HTTP HANDLERS
// ============================================================

void handleHealthz()
{
    JsonDocument doc;
    doc["ok"] = true;
    doc["device_id"] = DEVICE_ID;
    doc["boot_id"] = bootId;
    doc["firmware"] = "esp32_integration";
    doc["uptime_ms"] = millis();
    doc["sequence"] = sequence;
    doc["last_update_age_ms"] = millis() - lastSensorUpdate;
    doc["chip"] = ESP.getChipModel();
    doc["free_heap"] = ESP.getFreeHeap();
    doc["auth_required"] = strlen(API_TOKEN) > 0;

    JsonObject wifi = doc["wifi"].to<JsonObject>();
    wifi["connected"] = WiFi.status() == WL_CONNECTED;
    wifi["ssid"] = WIFI_SSID;
    wifi["ip"] = WiFi.localIP().toString();
    wifi["rssi_dbm"] = WiFi.RSSI();
    wifi["mdns"] = String(MDNS_HOSTNAME) + ".local";

    JsonObject sensors = doc["sensors"].to<JsonObject>();
    sensors["mains_present"] = lastR.mainsPresent;
    sensors["temperature_probe_ok"] = temperatureProbeOk;
    sensors["current_calibrated"] = currentSensorOk;

    sendJson(200, doc);
}

void handleReadings()
{
    if (!requireAuth()) return;

    JsonDocument doc;
    fillReadings(doc.to<JsonObject>());
    doc["ok"] = true;
    sendJson(200, doc);
}

void handleLoadsGet()
{
    if (!requireAuth()) return;

    JsonDocument doc;
    doc["ok"] = true;
    fillLoads(doc["loads"].to<JsonObject>());
    sendJson(200, doc);
}

void handleLoadsPost()
{
    if (!requireAuth()) return;

    JsonDocument req;
    if (!parseBody(req)) return;

    bool changed = false;

    // Form A: {"load": 1, "state": true}
    if (req["load"].is<int>())
    {
        if (!req["state"].is<bool>())
        {
            sendError(400, "\"state\" must be true or false.");
            return;
        }

        int load = req["load"].as<int>();
        bool state = req["state"].as<bool>();

        if (load == 1)      { load1State = state; changed = true; }
        else if (load == 2) { load2State = state; changed = true; }
        else if (load == 4) { load4State = state; changed = true; }
        else
        {
            sendError(400, "Invalid load. Use 1, 2 or 4 (relay 3 is not wired).");
            return;
        }
    }

    // Form B: {"load1": true, "load2": false, "load4": true} (any subset)
    if (req["load1"].is<bool>()) { load1State = req["load1"].as<bool>(); changed = true; }
    if (req["load2"].is<bool>()) { load2State = req["load2"].as<bool>(); changed = true; }
    if (req["load4"].is<bool>()) { load4State = req["load4"].as<bool>(); changed = true; }

    if (req["load3"].is<bool>() && req["load3"].as<bool>())
    {
        sendError(400, "Relay 3 is not wired in this build.");
        return;
    }

    if (!changed)
    {
        sendError(400, "Provide {\"load\":N,\"state\":bool} or load1/load2/load4 booleans.");
        return;
    }

    updateRelays();
    Serial.printf("Loads via API: L1 %s, L2 %s, L4 %s\n",
                  load1State ? "ON" : "OFF", load2State ? "ON" : "OFF", load4State ? "ON" : "OFF");

    JsonDocument doc;
    doc["ok"] = true;
    fillLoads(doc["loads"].to<JsonObject>());
    sendJson(200, doc);
}

void handleCalibrationGet()
{
    if (!requireAuth()) return;

    JsonDocument doc;
    doc["ok"] = true;
    fillCalibration(doc["calibration"].to<JsonObject>());
    sendJson(200, doc);
}

void handleCalibrationPost()
{
    if (!requireAuth()) return;

    JsonDocument req;
    if (!parseBody(req)) return;

    String action = req["action"] | "";
    float value = req["value"] | 0.0f;

    opLog = "";
    bool ok = false;

    if      (action == "mains_voltage")     ok = calibrateVoltage(true, value);
    else if (action == "secondary_voltage") ok = calibrateVoltage(false, value);
    else if (action == "current_meter")     ok = calibrateSecondaryCurrentMeter(value);
    else if (action == "sensor_model")      ok = setSensorModel(value);
    else if (action == "auto")              { ok = autoCalibrate(); autoCalDone = true; }
    else if (action == "zero")              ok = calibrateCrosstalk();
    else if (action == "reset")             { resetCalibration(); ok = true; }
    else if (action == "step_test")         { runLoadStepTest(); ok = true; }
    else
    {
        sendError(400, "Unknown action. Use mains_voltage, secondary_voltage, current_meter, sensor_model, auto, zero, reset or step_test.");
        return;
    }

    // Refresh the published readings so the next GET reflects the new factors.
    updateSensors();
    lastSensorUpdate = millis();

    JsonDocument doc;
    doc["ok"] = ok;
    doc["action"] = action;
    doc["log"] = opLog;
    fillCalibration(doc["calibration"].to<JsonObject>());
    sendJson(ok ? 200 : 422, doc);
}

void handleNotFound()
{
    sendError(404, "Unknown route. See /healthz, /api/readings, /api/loads, /api/calibration.");
}

// ============================================================
// WIFI
// ============================================================

void startWifi()
{
    WiFi.mode(WIFI_STA);
    WiFi.setHostname(MDNS_HOSTNAME);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    lastWifiAttemptMs = millis();

    Serial.print("Connecting to WiFi");

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_BOOT_WAIT_MS)
    {
        delay(500);
        Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED)
    {
        Serial.print("WiFi connected, IP: ");
        Serial.println(WiFi.localIP());
    }
    else
    {
        Serial.println("WiFi not connected yet; will keep retrying in the background.");
    }
}

void maintainWifi()
{
    static bool mdnsStarted = false;

    if (WiFi.status() == WL_CONNECTED)
    {
        if (!mdnsStarted)
        {
            if (MDNS.begin(MDNS_HOSTNAME))
            {
                MDNS.addService("http", "tcp", HTTP_PORT);
                mdnsStarted = true;
                Serial.printf("mDNS: http://%s.local\n", MDNS_HOSTNAME);
            }
        }
        return;
    }

    mdnsStarted = false;

    if (millis() - lastWifiAttemptMs < WIFI_RETRY_INTERVAL_MS) return;

    lastWifiAttemptMs = millis();
    Serial.println("WiFi down, reconnecting...");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// ============================================================
// SETUP
// ============================================================

void setup()
{
    Serial.begin(115200);
    Serial.setTimeout(1500);

    delay(1000);

    memset(&lastM, 0, sizeof(lastM));
    memset(&lastR, 0, sizeof(lastR));

    bootId = String(esp_random(), HEX) + String(esp_random(), HEX);

    loadCalibration();

    analogReadResolution(12);

    analogSetPinAttenuation(ZMPT_MAINS_PIN, ADC_11db);
    analogSetPinAttenuation(ZMPT_SECONDARY_PIN, ADC_11db);
    analogSetPinAttenuation(ACS_MAINS_PIN, ADC_11db);
    analogSetPinAttenuation(ACS_SECONDARY_PIN, ADC_11db);

    pinMode(RELAY_1_PIN, OUTPUT);
    pinMode(RELAY_2_PIN, OUTPUT);
    pinMode(RELAY_4_PIN, OUTPUT);

    // Default states: loads 1 and 2 ON, load 4 OFF (same as tested sketch).
    load1State = true;
    load2State = true;
    load4State = false;

    updateRelays();

    temperatureSensor.begin();

    startWifi();

    // WebServer only exposes headers that are explicitly collected.
    const char* headerKeys[] = { "Authorization" };
    server.collectHeaders(headerKeys, 1);

    server.on("/healthz",         HTTP_GET,  handleHealthz);
    server.on("/api/readings",    HTTP_GET,  handleReadings);
    server.on("/api/loads",       HTTP_GET,  handleLoadsGet);
    server.on("/api/loads",       HTTP_POST, handleLoadsPost);
    server.on("/api/calibration", HTTP_GET,  handleCalibrationGet);
    server.on("/api/calibration", HTTP_POST, handleCalibrationPost);
    server.onNotFound(handleNotFound);

    server.begin();

    Serial.printf("HTTP API started on port %u (device %s, boot %s, auth %s)\n",
                  HTTP_PORT, DEVICE_ID, bootId.c_str(), strlen(API_TOKEN) ? "on" : "OFF");

    updateSensors();

    lastSensorUpdate = millis();
}

// ============================================================
// LOOP
// ============================================================

void loop()
{
    maintainWifi();

    server.handleClient();

    processSerialCommands();

    if (millis() - lastSensorUpdate >= UPDATE_INTERVAL_MS)
    {
        lastSensorUpdate = millis();
        updateSensors();
    }
}
