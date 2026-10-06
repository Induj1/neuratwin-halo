# NeuraTwin EdgeBox X1 - Hardware instruction kit

**Round 2 track:** Digital Twin for Intelligent Health Monitoring and Predictive Maintenance of Distribution Transformers
**Team:** Neura Rangers
**Build target:** a safe tabletop transformer surrogate with industrial-style sensing, NFC asset identity, a physical cooling intervention, and a digital-twin dashboard that explains the evidence behind each alert.

## The build judges should see

1. Tap an NFC tag on the enclosure. The dashboard opens the matching asset passport.
2. Turn the load knob or select the labelled overload replay. Phase voltage/current, load and thermal state move together.
3. The twin forecasts a thermal limit approach and shows the evidence chain.
4. Introduce sensor drift or a disconnected probe. The sensor-trust panel changes and the system distinguishes measurement quality from equipment condition.
5. Start the 12 V fan or choose the recommended load reduction. The counterfactual forecast improves and a maintenance work order is created.

This is a prototype decision-support system. It must never switch, probe or control a live distribution transformer.

## Recommended architecture

- **Physical bay:** certified 12/24 V isolated transformer surrogate, a fused low-voltage load, two PT100 probes, a fan, an accelerometer, a leak/level test point and three labelled fault controls.
- **EdgeBox X1:** ESP32-S3, protected 12 V to 5 V power, isolated RS485, two MAX31865 RTD converters, I2C NFC/OLED/accelerometer bus, local status LED and a ring buffer.
- **Electrical source:** preferred: an electrician-installed SDM630-Modbus V2 on a safe test panel. Fallback: labelled replay data or a certified isolated low-voltage harness. Never connect a DIY ADC front-end to mains.
- **Uplink:** Wi-Fi first; optional SIM7600 LTE/GPRS module for a field-backhaul story.
- **Twin:** physical thermal state plus data-quality checks, anomaly evidence, forecast bands and a comparison of continue versus recommended action.

## Build sequence

### 0. Inventory and label - 30 minutes
Label every part `POWER`, `SENSE`, `BUS`, `ACTUATE` or `NFC`. Put the ESP32 and converters on a labelled carrier plate before wiring. Keep the high-energy test panel separate from the EdgeBox.

### 1. Power first - 45 minutes
Bring 12 V into the enclosure through a fuse and strain-relieved cable gland. Generate 5 V for the ESP32 and modules with a buck converter. Verify rails before inserting the MCU. Add one emergency power switch.

### 2. Thermal channels - 60 minutes
Connect the tank/transformer PT100 to MAX31865 #1 and ambient PT100 to #2. Route shielded cable away from the fan and modem antenna. Test open, short and unplugged states; these lower confidence and raise a sensor-quality alert.

### 3. Identity and local status - 45 minutes
Install PN532 behind a non-metallic face panel and attach an NTAG tag labelled `NR-104`. Add OLED and RGB LED. NFC payload contains only an asset ID and versioned configuration reference.

### 4. Electrical telemetry - 60 to 120 minutes
Preferred: read the certified meter over isolated RS485. If it is not available, run the same firmware with the replay adapter and label the electrical stream `SIMULATED REPLAY`.

### 5. Physical intervention - 45 minutes
Drive a 12 V fan with a logic-level MOSFET and flyback diode. Attach the fan to the surrogate bay so the thermal response changes visibly. Never connect it to a transformer control circuit.

### 6. Firmware and integration - 90 minutes
Sample thermal and vibration at 1 Hz; electrical at 1 to 5 Hz; publish a 5-second packet and retain a local ring buffer. Add timestamps, units, sequence number, firmware version and quality flags to every packet.

## Calibration and acceptance

- RTD: compare a room point and ice-water point; record offset and probe serial.
- Electrical: compare each R/Y/B channel against a reference. The supplied draft workbook uses a <=1% check; confirm the final procedure with CPRI.
- Current trip: the draft workbook lists a 50 A set-current check. Do not create 50 A on a student bench. Demonstrate the same logic with replay or a certified current source.
- Temperature trip: the draft workbook lists 60 deg C checks. Use a software threshold or controlled low-energy heater; do not heat transformer oil.
- Data quality: disconnect a probe, duplicate a timestamp, send an out-of-order packet and hold a stale value. Each must change confidence and appear in the incident view.
- Intervention: start the fan and show a lower counterfactual temperature trajectory; log the action and its assumptions.

## Judge runbook

1. **Identity:** tap NFC; show asset passport and provenance.
2. **Baseline:** show measured versus inferred temperature tracking with lag.
3. **Stress:** trigger overload; show phase values, health index, warning and forecast window.
4. **Explain:** open the causal chain from measured signal to state, risk and action.
5. **Trust:** inject a probe fault; show a measurement-quality alert rather than an invented transformer diagnosis.
6. **Act:** run the fan or load-reduction what-if; show improved forecast.
7. **Handoff:** create a work order with asset, evidence, urgency and verification step.

## Safety boundary

- No live transformer connection is part of this student prototype.
- Mains measurement is only by a certified meter, in an enclosed test panel, installed and checked by a licensed electrician.
- Keep the EdgeBox on an SELV supply. Keep mains, meter CTs and student electronics in separate enclosures.
- Do not use a breadboard for mains, expose terminals, defeat fusing or put NFC electronics on a metal tank wall.

## References

- CPRI/PowerNext draft files: `Track 2 - DT/DT Problem Statement.pdf` and `Track 2 - DT/Draft Data for Condition Monitoring.xlsx`.
- ESP32-S3: https://documentation.espressif.com/esp32-s3_datasheet_en.pdf
- ADS131M04: https://www.ti.com/lit/ds/symlink/ads131m04.pdf
- MAX31865: https://www.analog.com/en/products/max31865.html
- PN532: https://www.nxp.com/docs/en/nxp/data-sheets/PN532_C1.pdf
- SIM7600: https://www.simcom.com/product/SIM7600NAG.html
- SDM630 manual: https://www.eastrongroup.com/eastrongroup/2024/08/21/eastronsdm630modbusv2usermanual2020v1.4.pdf
- IEC 60076-7: https://webstore.iec.ch/en/publication/34351
