#include <WiFi.h>
#include <WebServer.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Preferences.h>
#include <math.h>
#include <string.h>
#include <stdarg.h>

// ============================================================
// WIFI - UNCHANGED
// ============================================================

const char* WIFI_SSID = "YOUR_SSID";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";

WebServer server(80);
Preferences preferences;

// ============================================================
// ESP32 DEV MODULE PIN MAPPING - UNCHANGED
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
// MEASUREMENT SETTINGS
// ============================================================

const float MAINS_FREQUENCY_HZ = 50.0;

const int UPDATE_CYCLES = 20;          // 400 ms per dashboard update
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

// Current calibration methods (saved in flash).
const int32_t CAL_NONE  = 0;
const int32_t CAL_OHM   = 1;
const int32_t CAL_METER = 2;
const int32_t CAL_MODEL = 3;

// ============================================================
// TYPES
// Declared before any function so the Arduino IDE's
// auto-generated prototypes can see them.
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
float transformerTemperature = 0.0;

unsigned long lastSensorUpdate = 0;
unsigned long lastRelayChangeMs = 0;

bool autoCalDone = false;
bool zeroTrackingActive = false;
bool currentSensorOk = false;
String calStatus = "Current not calibrated yet";

Measurement lastM;
Readings lastR;

String opLog;

// ============================================================
// LOGGING (Serial + text returned to the dashboard)
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
// CALIBRATION ROUTINES
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
        reportf("Unknown sensor type.");
        return false;
    }

    cal.iSecSens = sens;
    cal.iCalMethod = CAL_MODEL;
    saveCalibration();
    refreshCalStatus();

    reportf("Current sensitivity set to %.0f mV/A from sensor type. Saved.", sens);
    reportf("Press Zero current offset with mains ON for best accuracy.");

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
// LOAD STEP TEST
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
// SERIAL COMMANDS (optional; the dashboard does the same)
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
    if (command.startsWith("CALVM ")) { calibrateVoltage(true, command.substring(6).toFloat()); return; }
    if (command.startsWith("CALVS ")) { calibrateVoltage(false, command.substring(6).toFloat()); return; }
    if (command.startsWith("CALIS ")) { calibrateSecondaryCurrentMeter(command.substring(6).toFloat()); return; }

    Serial.println("Commands: AUTOCAL, ZERO, STEP, CALVM <V>, CALVS <V>, CALIS <A>, RESET");
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
    Serial.printf("Vm %.1f V (%.1f mV) | Vs %.2f V (%.2f mV) | Is %.3f A (raw %.2f, load %.2f mV) | exp %.3f A | %s\n",
                  r.mainsV, m.fund[CH_VM], r.secV, m.fund[CH_VS],
                  r.secI, m.fund[CH_IS], r.isCorr_mV, r.expectedSecI,
                  calStatus.c_str());
}

// ============================================================
// READ ALL SENSORS
// ============================================================

void updateSensors()
{
    Measurement m = sampleAll(UPDATE_CYCLES);
    Readings r = computeReadings(m);

    // Automatic current calibration only if never calibrated before.
    if (r.mainsPresent && !autoCalDone && cal.iCalMethod == CAL_NONE)
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

    lastM = m;
    lastR = r;

    printDiagnostics(m, r);
}

// ============================================================
// HTML PAGE
// ============================================================

const char MAIN_PAGE[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Transformer Monitor</title>

<style>
body { font-family: Arial, sans-serif; background: #111; color: white; margin: 0; padding: 20px; }
.container { max-width: 950px; margin: auto; }
h1 { text-align: center; margin-bottom: 25px; }
h2 { margin-top: 0; }
h3 { margin: 18px 0 6px; font-size: 16px; color: #ccc; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
.card { background: #1d1d1d; border-radius: 12px; padding: 18px; text-align: center; }
.value { font-size: 28px; font-weight: bold; margin-top: 8px; }
.unit { font-size: 13px; color: #aaa; }
.hint { font-size: 12px; color: #888; margin-top: 4px; }
.fault { color: #ff6b6b; }
.ok { color: #6bd68a; }
.relay { margin-top: 18px; }
.status { font-size: 20px; font-weight: bold; margin: 10px; }
button { padding: 11px 22px; margin: 5px; border: none; border-radius: 8px; font-size: 15px; cursor: pointer; }
.on { background: #198754; color: white; }
.off { background: #dc3545; color: white; }
.tool { background: #3a6ea5; color: white; }
.danger { background: #6b2a2a; color: white; }
input, select { padding: 10px; border-radius: 8px; border: 1px solid #444; background: #111; color: white; width: 120px; font-size: 15px; }
select { width: 190px; }
.row { margin: 6px 0; }
table { width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }
td { padding: 6px 4px; border-bottom: 1px solid #2a2a2a; }
td:last-child { text-align: right; font-family: monospace; }
pre { text-align: left; background: #111; padding: 10px; border-radius: 8px; overflow-x: auto; font-size: 12px; white-space: pre-wrap; }
.footer { text-align: center; color: #777; margin-top: 20px; font-size: 12px; }
</style>
</head>

<body>
<div class="container">

<h1>Transformer Monitoring System</h1>

<div class="grid">
  <div class="card">
    <div>Mains Voltage</div>
    <div class="value" id="mainsVoltage">--</div>
    <div class="unit">VAC</div>
  </div>
  <div class="card">
    <div>Secondary Voltage</div>
    <div class="value" id="secondaryVoltage">--</div>
    <div class="unit">VAC</div>
  </div>
  <div class="card">
    <div>Mains Current</div>
    <div class="value" id="mainsCurrent">--</div>
    <div class="unit">A RMS (calculated)</div>
  </div>
  <div class="card">
    <div>Secondary Current</div>
    <div class="value" id="secondaryCurrent">--</div>
    <div class="unit">A RMS</div>
    <div class="hint" id="secExpected"></div>
  </div>
  <div class="card">
    <div>Transformer Temperature</div>
    <div class="value" id="temperature">--</div>
    <div class="unit">&deg;C</div>
  </div>
</div>

<div class="card relay">
  <h2>Load 1</h2>
  <div class="status" id="load1Status">--</div>
  <button class="on" onclick="relay(1, 'on')">ON</button>
  <button class="off" onclick="relay(1, 'off')">OFF</button>
</div>

<div class="card relay">
  <h2>Load 2</h2>
  <div class="status" id="load2Status">--</div>
  <button class="on" onclick="relay(2, 'on')">ON</button>
  <button class="off" onclick="relay(2, 'off')">OFF</button>
</div>

<div class="card relay">
  <h2>Load 4</h2>
  <div class="status" id="load4Status">--</div>
  <button class="on" onclick="relay(4, 'on')">ON</button>
  <button class="off" onclick="relay(4, 'off')">OFF</button>
</div>

<div class="card relay">
  <h2>Calibration</h2>
  <div class="hint">Mains must be ON. Every value is saved and kept after restart.</div>

  <h3>Voltage (multimeter, AC volts)</h3>
  <div class="row">
    Mains <input id="mainsRef" type="number" step="0.1" placeholder="e.g. 228">
    <button class="tool" onclick="cal('mains', 'mainsRef')">Calibrate mains</button>
  </div>
  <div class="row">
    Secondary <input id="secRef" type="number" step="0.01" placeholder="e.g. 12.4">
    <button class="tool" onclick="cal('sec', 'secRef')">Calibrate secondary</button>
  </div>

  <h3>Current (choose one method)</h3>
  <div class="row">
    Ammeter reading (A) <input id="ampRef" type="number" step="0.001" placeholder="e.g. 0.62">
    <button class="tool" onclick="cal('amps', 'ampRef')">Calibrate current</button>
  </div>
  <div class="hint">True RMS AC ammeter in series with the load return wire, with loads ON.</div>
  <div class="row">
    <select id="model">
      <option value="185">ACS712 5A (185 mV/A)</option>
      <option value="100" selected>ACS712 20A (100 mV/A)</option>
      <option value="66">ACS712 30A (66 mV/A)</option>
    </select>
    <button class="tool" onclick="cal('model', 'model')">Set sensor type</button>
  </div>
  <div class="row">
    <button class="tool" onclick="cal('auto', '')">Auto-calibrate (39 ohm, no meter)</button>
    <button class="tool" onclick="cal('zero', '')">Zero current offset</button>
  </div>

  <h3>Tools</h3>
  <div class="row">
    <button class="tool" onclick="stepTest()">Run load test</button>
    <button class="danger" onclick="resetAll()">Reset all calibration</button>
  </div>

  <pre id="calMsg">Ready.</pre>
</div>

<div class="card relay">
  <h2>Diagnostics</h2>
  <div class="status" id="calStatus" style="font-size:15px">--</div>
  <table>
    <tr><td>Mains ZMPT 50 Hz signal</td><td id="dVm">--</td></tr>
    <tr><td>Secondary ZMPT 50 Hz signal</td><td id="dVs">--</td></tr>
    <tr><td>Secondary ACS raw 50 Hz signal</td><td id="dIsRaw">--</td></tr>
    <tr><td>Secondary ACS load signal (offset removed)</td><td id="dIsCorr">--</td></tr>
    <tr><td>Secondary ACS DC level</td><td id="dIsDc">--</td></tr>
    <tr><td>Current sensitivity</td><td id="dSens">--</td></tr>
    <tr><td>Mains / secondary factors</td><td id="dFac">--</td></tr>
    <tr><td>Samples per channel</td><td id="dN">--</td></tr>
  </table>
</div>

<div class="footer">Readings refresh automatically. Relay I3 is disabled.</div>

</div>

<script>
let busy = false;

function updateData() {
  if (busy) return;
  fetch('/api')
    .then(r => r.json())
    .then(d => {
      document.getElementById('mainsVoltage').innerText = d.mainsVoltage.toFixed(1);
      document.getElementById('secondaryVoltage').innerText = d.secondaryVoltage.toFixed(2);
      document.getElementById('mainsCurrent').innerText = d.mainsCurrent.toFixed(3);
      document.getElementById('secondaryCurrent').innerText = d.secondaryCurrent.toFixed(3);

      const se = document.getElementById('secExpected');
      if (d.secondaryVoltage > 0 && !d.currentOk) {
        se.className = 'hint fault';
        se.innerText = 'current not calibrated / sensor fault';
      } else if (d.secondaryVoltage > 0) {
        se.className = 'hint';
        se.innerText = 'expected ' + d.expectedSecondaryCurrent.toFixed(3) + ' A (' + d.loadsOn + ' loads)';
      } else {
        se.innerText = '';
      }

      document.getElementById('temperature').innerText =
        d.temperature === -127 ? 'ERROR' : d.temperature.toFixed(1);
      document.getElementById('load1Status').innerText = d.load1 ? 'ON' : 'OFF';
      document.getElementById('load2Status').innerText = d.load2 ? 'ON' : 'OFF';
      document.getElementById('load4Status').innerText = d.load4 ? 'ON' : 'OFF';

      const cs = document.getElementById('calStatus');
      cs.innerText = d.calStatus;
      cs.className = 'status ' + (d.currentOk ? 'ok' : 'fault');

      document.getElementById('dVm').innerText = d.vmMv.toFixed(1) + ' mV';
      document.getElementById('dVs').innerText = d.vsMv.toFixed(2) + ' mV';
      document.getElementById('dIsRaw').innerText = d.isRawMv.toFixed(2) + ' mV';
      document.getElementById('dIsCorr').innerText = d.isCorrMv.toFixed(2) + ' mV';
      document.getElementById('dIsDc').innerText = d.isDcMv.toFixed(0) + ' mV';
      document.getElementById('dSens').innerText = d.sens.toFixed(1) + ' mV/A';
      document.getElementById('dFac').innerText = d.vmFactor.toFixed(4) + ' / ' + d.vsFactor.toFixed(4);
      document.getElementById('dN').innerText = d.samples;
    })
    .catch(e => console.log('API error:', e));
}

function relay(load, state) {
  fetch('/relay?load=' + load + '&state=' + state).then(() => updateData());
}

function runRequest(url, waitText) {
  busy = true;
  document.getElementById('calMsg').innerText = waitText;
  fetch(url)
    .then(r => r.text())
    .then(t => { document.getElementById('calMsg').innerText = t; })
    .catch(() => { document.getElementById('calMsg').innerText = 'Request failed. Is the ESP32 reachable?'; })
    .finally(() => { busy = false; updateData(); });
}

function cal(type, inputId) {
  let v = '';
  if (inputId) {
    v = document.getElementById(inputId).value;
    if (v === '') {
      document.getElementById('calMsg').innerText = 'Enter a value first.';
      return;
    }
  }
  let waitText = 'Measuring (about 3 s)...';
  if (type === 'auto') waitText = 'Running... relays will click (about 8 s)';
  if (type === 'amps' || type === 'zero') waitText = 'Running... loads switch off briefly (about 6 s)';
  if (type === 'model') waitText = 'Saving...';
  runRequest('/cal?type=' + type + '&value=' + encodeURIComponent(v), waitText);
}

function stepTest() {
  runRequest('/step', 'Running load test... relays will click (about 15 s)');
}

function resetAll() {
  if (!confirm('Reset ALL calibration to defaults?')) return;
  runRequest('/cal?type=reset&value=', 'Resetting...');
}

updateData();
setInterval(updateData, 1000);
</script>

</body>
</html>
)rawliteral";

// ============================================================
// JSON API
// ============================================================

void handleAPI()
{
    String json = "{";

    json += "\"mainsVoltage\":" + String(mainsVoltage, 2);
    json += ",\"secondaryVoltage\":" + String(secondaryVoltage, 2);
    json += ",\"mainsCurrent\":" + String(mainsCurrent, 4);
    json += ",\"secondaryCurrent\":" + String(secondaryCurrent, 3);
    json += ",\"expectedSecondaryCurrent\":" + String(expectedSecondaryCurrent, 3);
    json += ",\"loadsOn\":" + String(loadsOn());
    json += ",\"temperature\":" + String(transformerTemperature, 2);

    json += ",\"load1\":";
    json += load1State ? "true" : "false";
    json += ",\"load2\":";
    json += load2State ? "true" : "false";
    json += ",\"load4\":";
    json += load4State ? "true" : "false";

    json += ",\"currentOk\":";
    json += currentSensorOk ? "true" : "false";
    json += ",\"calStatus\":\"" + calStatus + "\"";
    json += ",\"calMethod\":" + String(cal.iCalMethod);

    json += ",\"vmMv\":" + String(lastM.fund[CH_VM], 2);
    json += ",\"vsMv\":" + String(lastM.fund[CH_VS], 2);
    json += ",\"isRawMv\":" + String(lastM.fund[CH_IS], 2);
    json += ",\"isCorrMv\":" + String(lastR.isCorr_mV, 2);
    json += ",\"isDcMv\":" + String(lastM.mean[CH_IS], 1);
    json += ",\"sens\":" + String(cal.iSecSens, 2);
    json += ",\"vmFactor\":" + String(cal.vMainsFactor, 4);
    json += ",\"vsFactor\":" + String(cal.vSecFactor, 4);
    json += ",\"samples\":" + String((unsigned long)lastM.samples);

    json += "}";

    server.send(200, "application/json", json);
}

// ============================================================
// CALIBRATION / TEST HTTP HANDLERS
// ============================================================

void handleCal()
{
    String type = server.arg("type");
    float value = server.arg("value").toFloat();

    opLog = "";

    if (type == "mains")
    {
        calibrateVoltage(true, value);
    }
    else if (type == "sec")
    {
        calibrateVoltage(false, value);
    }
    else if (type == "amps")
    {
        calibrateSecondaryCurrentMeter(value);
    }
    else if (type == "model")
    {
        setSensorModel(value);
    }
    else if (type == "auto")
    {
        autoCalibrate();
        autoCalDone = true;
    }
    else if (type == "zero")
    {
        calibrateCrosstalk();
    }
    else if (type == "reset")
    {
        resetCalibration();
    }
    else
    {
        reportf("Unknown calibration type.");
    }

    server.send(200, "text/plain", opLog);
}

void handleStep()
{
    opLog = "";
    runLoadStepTest();
    server.send(200, "text/plain", opLog);
}

// ============================================================
// RELAY HTTP CONTROL
// ============================================================

void handleRelay()
{
    if (!server.hasArg("load") || !server.hasArg("state"))
    {
        server.send(400, "text/plain", "Missing parameters");
        return;
    }

    int load = server.arg("load").toInt();
    String state = server.arg("state");

    if (state != "on" && state != "off")
    {
        server.send(400, "text/plain", "Invalid state");
        return;
    }

    bool newState = (state == "on");

    if (load == 1)      load1State = newState;
    else if (load == 2) load2State = newState;
    else if (load == 4) load4State = newState;
    else
    {
        server.send(400, "text/plain", "Invalid relay");
        return;
    }

    updateRelays();

    server.send(200, "text/plain", "OK");

    Serial.printf("Load %d: %s\n", load, newState ? "ON" : "OFF");
}

// ============================================================
// ROOT PAGE
// ============================================================

void handleRoot()
{
    server.send_P(200, "text/html; charset=utf-8", MAIN_PAGE);
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

    loadCalibration();

    analogReadResolution(12);

    analogSetPinAttenuation(ZMPT_MAINS_PIN, ADC_11db);
    analogSetPinAttenuation(ZMPT_SECONDARY_PIN, ADC_11db);
    analogSetPinAttenuation(ACS_MAINS_PIN, ADC_11db);
    analogSetPinAttenuation(ACS_SECONDARY_PIN, ADC_11db);

    pinMode(RELAY_1_PIN, OUTPUT);
    pinMode(RELAY_2_PIN, OUTPUT);
    pinMode(RELAY_4_PIN, OUTPUT);

    // Default states: loads 1 and 2 ON, load 4 OFF.
    load1State = true;
    load2State = true;
    load4State = false;

    updateRelays();

    temperatureSensor.begin();

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.print("Connecting to WiFi");

    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        Serial.print(".");
    }

    Serial.println();
    Serial.println("WiFi connected");
    Serial.print("ESP32 IP address: ");
    Serial.println(WiFi.localIP());

    server.on("/", handleRoot);
    server.on("/api", handleAPI);
    server.on("/relay", handleRelay);
    server.on("/cal", handleCal);
    server.on("/step", handleStep);

    server.begin();

    Serial.println("Web server started");

    updateSensors();

    lastSensorUpdate = millis();
}

// ============================================================
// LOOP
// ============================================================

void loop()
{
    server.handleClient();

    processSerialCommands();

    if (millis() - lastSensorUpdate >= UPDATE_INTERVAL_MS)
    {
        lastSensorUpdate = millis();
        updateSensors();
    }
}