# NeuraTwin Halo — Neura Rangers / CPRI Track 2

A distribution-transformer condition-monitoring prototype with an inspectable decision chain:
**observe → freeze a forecast → reveal later data → compare interventions → verify follow-up → export evidence.**

Start with [the submission dossier](web/submission-guide.html), [the current hardware handoff](web/hardware-guide.html) and [the model specification](docs/DUAL_MODE_TWIN.md).

The [synchronized operations workspace](docs/SYNCHRONIZED_OPERATIONS.md) adds a condition dial, illustrative phase waveforms, continuous simulation controls, an inline intervention comparison and recorded-state replay at `/app#operate`. Hardware remains single-phase and RMS-only; unavailable measurements stay unavailable.

See the [v6 model and evidence release record](docs/MODEL_AND_EVIDENCE_UPGRADE_V6.md) for measured gains and remaining checks.

## Current model and evidence upgrades

- **Assess readings** in Digital twin runs the observation-only assessor on the selected run and revision. Scenario names, declared cooling, fault labels and future readings are excluded. A changed revision invalidates the review.
- **Reviewed winding forecast reference** identifies rise and time constant from a healthy oil + reported hot-spot prefix, validates against two baselines, and applies only to qualified projections. Diagnostic holds are unchanged. Oil-only and surface-probe records cannot enable it. See [qualification and development results](docs/REVIEWED_WINDING_REFERENCE.md).
- **External public-data forecasting** in Evidence executes frozen numeric models on the original ETTh1 recording. Validation selected gradient boosting, which was about 1% worse than persistence on the later test segment. All candidates, losses, provenance and a forecast/reveal demonstration remain visible. Results use source units, not verified degrees Celsius. See [the complete public-data experiment](docs/EXTERNAL_ETT_FORECAST.md).
- The earlier v5 release and its evaluation remain historical; current source matching is checked separately. This release does not establish fivefold superiority, field accuracy or a guaranteed competition result.

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

Keep **one selected industrial run** throughout this main story. Its source, run ID and clock stay visible. Independent recordings are a separately introduced experiment, never substituted for this asset.

1. **0:00–0:40 — Rehearsal → Prepare a new rehearsal run.** Identify the labelled simulation, warning, modelled hot-spot and critical reference. Open **Review this run** in Digital twin.
2. **0:40–1:30 — Inspect signals and recorded response.** Distinguish immediate electrical response from delayed heating. Select **Assess readings** beside the warning and show its observation-only assessment, including any forecast hold. The review is invalidated when the run changes.
3. **1:30–2:30 — Digital twin → Review scenario study.** Explain that this conditional action study uses declared cooling. Inspect a proposed reduction, peak and curtailed energy; apply it only when a nonzero proposal exists. Advance the same simulation five minutes. A 240-minute sensitivity study is not independently validated four-hour forecasting.
4. **2:30–4:00 — Open run maintenance.** Record an owner, inspection, action and numerical acceptance rules. Demonstrate a hold or temporary stabilization while cooling is impaired. Only demonstrate closure after the configured stable recovery window and all checks pass. No invented repair or prefilled technician observations.
5. **4:00–5:00 — Export this run and open Evidence's evaluation results.** Identify the dataset-level comparison separately from the selected run. Show additional warning lead time, false alarms, error tails and coverage together. The frozen fresh synthetic experiment and known-corpus regression remain distinct. Show the external ETTh1 experiment separately, including its loss against persistence.

Optional technical follow-up: import an independently supplied recording using Evidence's source-bound workflow, freeze its assessment before revealing later rows, and export the review. A recording known to its uploader is a retrospective holdout. Show Physical prototype only when demonstrating actual commissioned acquisitions; otherwise its unavailable channels are the correct result.

The dossier uses this same sequence. The offline walkthrough is a labelled synthetic fallback, not a replacement for recorded evidence.

## What is new in the submission workflow

- Warning/critical state takes precedence over a Healthy condition badge. The weighted index remains labelled as a screening heuristic, not a failure probability.
- Sensor disagreement asks for an independent check and withholds the affected forecast.
- Forecasts copy settings, inputs, origin and provenance before future observations. Scoring preserves failures, changed-input samples and missing evidence. Hashes detect changes relative to a retained record; they are not signatures.
- Intervention studies enumerate demand reductions and delays, enforce declared thermal/load constraints and retain rejected candidates. Stale recommendations cannot be applied. Application only changes the selected simulation.
- Maintenance closure enforces a recorded stable duration, maximum load/temperature, qualified uninterrupted observations, restored cooling and a forward thermal corner check. Temporary stabilization is distinct from resolution. Legacy orders without structured rules retain their historical status and visibly fail current verification.
- A committed blind experiment withholds seed, scenario and future observations until the observation-only assessment is frozen. Extra hidden-state fields cannot enter the assessor. Evidence displays fault-specific errors, misses, nuisance alarms and withheld forecast counts.
- Reviewed oil-reference CSV fitting uses a bounded first-order model and chronological 70/30 validation. A surface-temperature file is rejected. Fitted oil parameters can initialize a new run; winding/rating/absolute-loss assumptions stay illustrative.
- Run exports include all retained history, event trail, frozen predictions/scores, intervention studies and maintenance records in JSON, CSV and readable HTML with a SHA-256 manifest.

## Reproducible evaluation

```powershell
python scripts/benchmark_submission.py
python scripts/benchmark_pipeline.py
python scripts/rehearse_submission.py
python -m pip install -r requirements-dev.txt
python -m pytest tests -q --junitxml=reports/halo-submission-tests.xml
python scripts/package_submission.py
```

This machine has a legacy `pyreadline` conflict with Python 3.14; the process-local test workaround is:

```powershell
python -c "import sys; sys.modules['readline']=None; import pytest; raise SystemExit(pytest.main(['tests','-q','--junitxml=reports/halo-submission-tests.xml']))"
```

The current **observation-pipeline-5** has two separately identified evaluations:

- **Known-corpus regression:** `reports/pipeline-benchmark.json`, with paired lead-time, diagnostic coverage, nuisance-alarm burden and scored/unscored forecasts. Historical v4 outputs remain in `reports/pipeline-v4-before-v5-*`.
- **Fresh frozen synthetic evaluation:** `reports/pipeline-v5-fresh-protocol.json` binds the source, unused randomly selected seeds, scenarios, horizons and metrics before generation. Its single consumed run and report are in `reports/pipeline-v5-fresh-protocol-run/`. These are internally generated synthetic cases, not external recordings or field validation; they become known after this run.

Evidence displays both results with source hashes and retained protocol/report integrity. Point forecasts have no calibrated safety interval. Independent forecast scoring stops at 30 minutes; the 240-minute scenario planner establishes model sensitivity and execution consistency only. False alarms, missed warnings, signed error tails, target availability and withheld predictions remain in the reports.

The [v5 method](docs/OBSERVATION_PROTOCOL_V5.md) describes voltage-aware oil fitting and complete RMS current observations. The [evaluation protocol and external recording guide](docs/EVALUATION_PROTOCOL_AND_EXTERNAL_RECORDINGS.md) explains reproduction and importing data without relabelling it as prospective or physical evidence. The [release record](docs/RELEASE_READINESS_2026-10-09.md) identifies final verification and remaining evidence boundaries.

The supplied CPRI spreadsheet provides acceptance examples, not longitudinal labelled fault-training data. The saved Laya evaluation abstained in five demonstration cases; optional language interpretation is not established transformer diagnosis. Actual remaining life and calibrated failure probability are unavailable. The official brief permits simulated data and later sensor extension.

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

## Submission verification · 9 October 2026

Current test counts and browser results are recorded in `reports/halo-release-tests.xml`, `reports/halo-release-js-tests.txt`, `reports/halo-release-browser.json` and the [release record](docs/RELEASE_READINESS_2026-10-09.md). The earlier hardening reports remain historical evidence.

Imported oil recordings now have their own immutable source/assessment → inspection → action → comparable follow-up → reference-review closure → export workflow. Its [rehearsal](reports/observation-workflow-rehearsal.json) uses labelled synthetic fixtures, never physical repair claims. Physical maintenance rejects calibration/configuration changes and inconsistent raw evidence. Frames retain their acquisition configuration; durable pending analysis drains continuously with leased claims, oldest-due-first scheduling, retry backoff and command-free recovery. See [hardware provenance](docs/HARDWARE_PROVENANCE_AND_RECOVERY.md).

Run `python scripts/smoke_submission.py` after packaging to extract the allowlisted archive and validate its actual contents; `reports/submission-package-smoke-current.json` identifies the tested ZIP by SHA-256 and remains alongside the archive to avoid a self-referencing manifest. Physical commissioning and independent field evaluation remain outstanding.

## Bench lab: capture → compare → replay

Open `/app#lab`. The software emulator is isolated from physical acquisition, calibration activation and relay commands. Start an emulator experiment, freeze a three-minute surface forecast, advance 60 seconds three times, then inspect model error against persistence. Change the virtual load and freeze a second forecast to inspect recovery. Changed-input samples remain separate. Stop the experiment and export JSON, CSV, an interactive offline HTML replay and a SHA-256 manifest.

For actual hardware, select Physical ESP32 only after fresh acquisition is available. Inspect chip/configuration agreement, sequence gaps, boot changes, raw RMS/bias/range values, channel flags and calibrated readings. Reference checks attach to an exact acquisition and retain entered tolerance, instrument and reviewer; scale proposals do not automatically activate a calibration. Use a physical proposal in the existing calibration draft and verify additional operating points before saving. Missing model/calibration/ambient or stale data blocks forecasting. Event annotations do not certify a repair. This workflow never issues physical load commands.

```powershell
python scripts/rehearse_bench_lab.py
python scripts/rehearse_recovery.py
python scripts/device_emulator.py --output reports/emulated-device.ndjson
```

The first script exercises the entire emulator workflow in disposable SQLite and writes `reports/bench-experiment-rehearsal.zip`. The recovery script terminates and restarts a separate loopback API process and reopens its durable bridge queue after a deliberately lost acknowledgement. Original acquisition time, exact-once storage, stale status and zero physical commands are checked. Unit regressions additionally cover stale configuration, USB silence, mismatched device/boot/chip, queued-command revocation and late acknowledgements. These are software checks; actual electrical contact state and physical watchdog timing remain unmeasured.
