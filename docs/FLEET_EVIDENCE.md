# Fleet decisions and model evidence

Open **Fleet decisions** at `/app#portfolio`. **Fleet map** at `/app#fleet` is the separate asset-scoped simulation and field-work rehearsal; both are retained. Their API paths and page identifiers are isolated, and recordings are not silently treated as live fleet assets. This extension uses Halo's existing glass theme and authenticated API/record store. It does not change GPIOs, relay handlers, physical acquisition or commissioning gates.

## Operator workflow

1. Create the 25-asset demonstration or import an oil-temperature CSV. Saved recordings survive refresh. The built-in fleet uses a two-store oil/radiator plant independent of the fitted one-node predictor. It is not connected to 25 real transformers.
2. Review the attention queue. Select an asset to see observed limits, stale/missing evidence, model disagreements, held-out errors and qualification holds. An observed overload stays visible even if its forecast is withheld.
3. Inspect the model report card. Forecasts exist only when the recording passes the declared screening policy. The chart separates observations and future conditional projections.
4. Assign a triage case. It freezes readings, reasons and model evidence and appears in Maintenance. Findings and follow-up use revision checks. `review_complete` means the review is complete, not that equipment recovered. Physical intervention verification remains in the existing Maintenance desk.
5. Evaluate a transfer on a declared tie. The backend checks simultaneous observations, qualified thermal evidence, fitted load domain, loading/thermal limits, voltage evidence and equal-kVA balance. Passing is not switching authorization. Compatible power factor is assumed; phase balance, network load flow, protection coordination and switching order are outside the calculation. No hardware endpoint is called.
6. Add laboratory gas reports separately. Combustible totals and per-day trends are arithmetic on entered reports, not ESP32 gas measurements or fault classifications.
7. Compare complete deployment costs for the same asset count and period. Unknown fields require deliberate entries; vendor prices and avoided-failure rates are not invented.
8. Download PDF and JSON evidence. JSON retains samples, the frozen report, cases, lab additions, saved transfer/cost studies and hashes. Study inputs and outputs are retained together. Hashes detect changes to retained content; they do not prove independent authorship or field validation.

## Qualification policy: fleet-screening-1

- Target: top-oil temperature, not surface or winding temperature.
- Regular 1-10 minute observations. Missing temperatures and gaps prevent fitting.
- At least 180 rows, plus sufficient disjoint windows for the selected cadence. Chronological split: 60% fit, 20% calibration, 20% test.
- Fit rated rise and time constant on the first block. Loss ratio 5 and thermal exponent 0.8 are disclosed assumptions. Reject boundary fits and Jacobian condition number above 1000.
- Forecast approximately 30 minutes using only the temperature, load and ambient available at each origin. Future measured loading is never supplied to forecast evaluation.
- The nominal 90% empirical band uses maximum error per disjoint calibration trajectory and a finite-sample quantile. Test errors never select parameters or the band.
- Require at least nine calibration and eight test trajectories. Report test MAE, persistence MAE, P95 error, achieved trajectory coverage and band radius.
- Withhold when MAE exceeds 2 C, improvement over persistence is below 5%, test trajectory coverage is below 80%, the latest complete trajectory exceeds the band, or current inputs leave the fitted range. These are prototype screening cutoffs, not IEC requirements.
- An asset more than 20 minutes behind the newest portfolio observation is stale relative to that recording. Recordings are never described as live.
- Qualification is limited to the recording, target and operating range. Synthetic qualification remains synthetic; imported observations remain uploader-supplied and unverified.

Triage is an inspectable priority score, not a failure probability: load +30, oil +45, voltage +20, forecast +20, drift +15, missing/stale +35; criticality adds 0-12 when a reason exists; total capped at 100. Contributing reasons are visible.

## Cost and laboratory scope

Period cost per asset = hardware + installation + commissioning + years * (annual connectivity + annual service) + one period replacement allowance. Fleet cost multiplies this by asset count. Optional break-even count divides Halo's total cost by the entered value of an avoided incident, rounded up. It does not predict that incidents will be avoided. Taxes, discounting, inflation and grants must be included in assumptions or assessed separately.

Combustible gas total = H2 + CH4 + C2H6 + C2H4 + C2H2 + CO in ppm; CO2 excluded. Rates use consecutive, timezone-aware lab sample times. No Duval zones or diagnosis thresholds are invented. Background reference: [US Bureau of Reclamation, Transformers: Basics, Maintenance, and Diagnostics](https://usbr.gov/tsc/techreferences/mands/mands-pdfs/Trnsfrmr.pdf). This does not validate sampling procedures or instruments.

## Existing workspace corrections

- Offline physical equipment cannot receive a green all-clear merely because an independent simulation is running. Simulation alarms retain explicit labels; physical condition remains unknown.
- Physical-source oil, pressure, level and model-trip annunciators identify study outputs. Offline values are not described as normal physical conditions.
- Maintenance shows the accepted profile revision and calibration evidence beside the decision. Assumed profiles disclose absent measured predictive validation.
- Physical ageing scenarios initialize thermal defaults from the maintenance profile. Explicit overrides remain labelled. The ageing formulation stays separate and is not a calibrated lifespan estimate.

## API and storage

`/api/halo/portfolio` uses the existing operator session. Immutable recordings, append-only lab history and revision-checked cases use SQLite/Supabase's existing record abstraction. No schema migration is required. Calculations are persisted with their inputs, result, actor, timestamp and content hash. A small catalog avoids loading every time series when listing recordings.

Limits: 25 assets, 20,000 total samples, 2,016 samples per asset, 4 MB CSV and 100 lab records per asset recording. This is a bounded prototype portfolio workflow, not a streaming million-asset platform. Existing live bench/industrial sources remain separate.

The implementation is original. Public competitor work informed capability selection; no competitor code was copied or executed.

## Verification

The complete merged backend suite passed (566 tests), and the complete JavaScript suite passed (101 tests). Fleet-specific tests were rerun after final export/storage changes. Browser checks covered saved recordings after reload, asset filtering, case creation and review in Maintenance, a constrained transfer, deployment costs, laboratory entry and PDF download. The phone layout was checked at 390 px with no page overflow; evidence PDFs were rendered and inspected. QA used an isolated SQLite database with hardware commands and external integrations disabled. None of these checks establishes physical or field accuracy.
