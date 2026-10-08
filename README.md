# NeuraTwin Halo — Neura Rangers / CPRI Track 2

A distribution-transformer condition-monitoring prototype with an inspectable decision chain:
**observe → freeze a forecast → reveal later data → compare interventions → verify follow-up → export evidence.**

Start with [the submission dossier](web/submission-guide.html), [the current hardware handoff](web/hardware-guide.html) and [the model specification](docs/DUAL_MODE_TWIN.md).

## Run the project

Python 3.12+:

```powershell
python -m pip install -r requirements.txt
python scripts/run_local_demo.py
```

Open `http://127.0.0.1:8765/app#demo`. The standalone launcher uses its own SQLite database, binds only to loopback, disables physical control and Laya, and does not read `.env`, open a serial port or start Telegram. It is an explicit local rehearsal; it does not copy or synchronize cloud data. Stop an existing server on this port before launching another.

For the existing configured private backend:

```powershell
python -m uvicorn neuratwin.app:app --host 127.0.0.1 --port 8765 --env-file .env
```

See [backend operations](docs/BACKEND.md) for migrations, team roles and hosting. Keep server secrets in private environment variables. The supplied `.env.example` contains no keys. A static hardware-guide deployment does not run the full application.

## One explicit source across the workspace

| Source | What it means |
| --- | --- |
| Industrial simulation | Persistent illustrative distribution-transformer run. Digital twin, Action Lab, Evidence, Maintenance and Asset passport follow the same run, revision and clock. |
| Physical prototype | Actual ESP32 measurements. Missing, disconnected, stale and uncalibrated channels stay unavailable. Surface temperature is never renamed oil temperature. |
| Reference datasets / studies | Independent bench/distribution replays, supplied acceptance examples, lab records and Grid Rescue. These are explicitly separate studies. |

The main navigation focuses on Digital twin, Action Lab, Maintenance, Evidence and Rehearsal. More tools exposes Asset passport, Commissioning, Inspector, Assistant and the independent Arena. Source selection is always visible.

## Five-minute demonstration

1. Rehearsal → **Prepare a new rehearsal run**: labelled simulation, 110% load, degraded cooling, 35 °C ambient. Review the warning and thermal trajectory.
2. Evidence → freeze a 15-minute forecast, then advance three five-minute steps. Compare later observations against the original frozen curve and persistence.
3. Action Lab → compare 60 minutes with zero delay. Inspect rejected candidates, sensitivity limits and curtailed energy; apply the selected demand reduction to simulation.
4. Maintenance → record an owner, acceptance criteria, investigation and action. Closure requires later qualified readings and recovered operation. A continuing warning correctly blocks closure.
5. Explicitly show Physical prototype. Use real data only after commissioning; otherwise show unavailable channels and outstanding checks. Return to Industrial Evidence, show benchmark misses and export the case.

The dossier includes presenter notes and technical questions. Keep an exported rehearsal case and the precomputed `web/halo-fallback.html` walkthrough available. The latter is a static synthetic fallback, not the numerical application.

## What is new in the submission workflow

- Warning/critical state takes precedence over a Healthy condition badge. The weighted index remains labelled as a screening heuristic, not a failure probability.
- Sensor disagreement asks for an independent check and withholds the affected forecast.
- Forecasts copy settings, inputs, origin and provenance before future observations. Scoring preserves failures, changed-input samples and missing evidence. Hashes detect changes relative to a retained record; they are not signatures.
- Intervention studies enumerate demand reductions and delays, enforce declared thermal/load constraints and retain rejected candidates. Stale recommendations cannot be applied. Application only changes the selected simulation.
- Maintenance records require investigation, action and subsequent recovered-operation evidence before closure.
- Reviewed oil-reference CSV fitting uses a bounded first-order model and chronological 70/30 validation. A surface-temperature file is rejected. Fitted oil parameters can initialize a new run; winding/rating/absolute-loss assumptions stay illustrative.
- Run exports include all retained history, event trail, frozen predictions/scores, intervention studies and maintenance records in JSON, CSV and readable HTML with a SHA-256 manifest.

## Reproducible evaluation

```powershell
python scripts/benchmark_submission.py
python -m pip install -r requirements-dev.txt
python -m pytest tests -q --junitxml=reports/halo-submission-tests.xml
python scripts/package_submission.py
```

This machine has a legacy `pyreadline` conflict with Python 3.14; the process-local test workaround is:

```powershell
python -c "import sys; sys.modules['readline']=None; import pytest; raise SystemExit(pytest.main(['tests','-q','--junitxml=reports/halo-submission-tests.xml']))"
```

The independent synthetic benchmark contains 30 cases, six seeds and mild/severe overload, cooling degradation, sensor bias, dropout and healthy controls. It uses a different plant with noise, nonlinear cooling and parameter mismatch. The forecaster receives no future inputs; the detector receives no event labels.

| Horizon | Model MAE | Persistence MAE | Scored / possible |
| --- | ---: | ---: | ---: |
| 5 min | 0.926 °C | 1.397 °C | 156 / 180 |
| 15 min | 2.035 °C | 4.113 °C | 156 / 180 |
| 30 min | 3.965 °C | 8.252 °C | 150 / 180 |

Detection: **16/24 fault episodes**, correct-alert precision **93.4%** of alert minutes, false alarms **65/1,386 normal minutes (4.69%)**. Eight misses remain in the report. These test the oil-reference and residual-screening methods; they do not validate every industrial feature or establish field accuracy. Raw per-origin/per-minute CSV and fixed seeds are included.

The supplied CPRI spreadsheet provides 12 acceptance examples, not longitudinal labelled fault-training data. Laya's saved five-case evaluation abstained in all five cases; optional Laya integration is not claimed as established transformer diagnosis. An industrial forecast scored against its own model establishes internal consistency only. Actual remaining life and calibrated failure probability are unavailable.

## Current hardware — must match the software

Use only [HW–002, current handoff](web/hardware-guide.html), not archived guides.

- EXP-PRO 12-0-12 / 1 A package. Asymmetric resistance readings leave primary/secondary/tap identity unresolved. No mains connection is assigned in this software.
- Four 39 Ω / 10 W resistor branches on a four-channel relay board. Board-specific reported contact order: left NO, middle COM, right NC. Physical K4 is locked; overload is simulated.
- Reported relay GPIOs 12/14/27/26. “ESP32 Dev Module” and CP2102 do not establish chip identity. Earlier ADC GPIO4/5 assumptions conflict with classic ESP32; firmware ADC and DS18B20 pins remain unassigned until reviewed.
- Two ZMPT101B modules, one series ACS712, one DS18B20 surface probe. Verify module terminals, isolation, conditioning and reference calibration. Secondary return is not automatically logic ground. USB powers the controller; verify the 5 V module supply budget.
- No installed ambient probe. A documented independent ambient observation can be recorded and expires after 10 minutes. An assumed forecast ambient does not create training evidence.
- Fuse type/rating, enclosure, strain relief, protection, bonding and transformer identity need qualified physical review. No software test establishes electrical safety.

After hardware review, use the commissioning workflow and `firmware/halo_esp32/halo_config.h`. Verification and physical-control flags default false. Compile with the actual board family and ArduinoJson, OneWire and DallasTemperature. Both default locked firmware targets have compile reports in `reports/firmware-esp32*.txt`; compilation is not hardware testing.

Start `python scripts/usb_bridge.py --port COM6` only after the board is reviewed and a private `HALO_DEVICE_TOKEN` is configured. Opening a port may reset the board. No serial bridge is started by the web server. Physical ON requests require all separate permissions, commissioning, calibration, freshness and command gates. A software OFF acknowledgment is not proof of open contacts or an emergency stop.

## Optional and advanced experiences

Reference studies retain the existing 3D inspector, acceptance measurements, reviewed DGA/lab entries, conservative thermal capacity, blind judge challenges and constrained synthetic grid-restoration studies. Their assumptions are documented in `docs/DUAL_MODE_TWIN.md` and `web/halo-arena-guide.html`. They do not silently replace the primary case.

QR/NFC are identity conveniences, not authentication; device/browser support and a reachable full-app URL are required. Telegram requires a separately configured token, allowlisted chats and an explicitly started worker; no live delivery is claimed. Local Laya can be installed with `requirements-laya.txt` and started via `start-halo.ps1`; the core numeric application works without it.

## What remains to establish physically

Qualified electrical review; controller and winding identification; reference calibration; actual acquisition and contact verification; measured acceptance evidence; independent field-fault evaluation. These cannot be replaced by fabricated software records. Live Telegram, NFC and actual device timing require their own tests.

The submission archive intentionally excludes `.env`, runtime databases, private recordings, model weights and compiler toolchains. No submission, public deployment or Git push is performed by building it.

## Submission verification · 8 October 2026

162 automated tests passed. Browser verification covers the complete industrial investigation, persistence after restart, source switching, rejected premature closure, oil-reference fitting, export integrity and 390 px responsive layout. The allowlisted archive starts from a clean extracted folder in isolated SQLite mode; ten smoke checks passed without loading private configuration. See `reports/halo-submission-tests.xml`, `reports/halo-submission-browser.json` and `reports/submission-package-smoke.json`. These are software checks; physical commissioning remains outstanding.
