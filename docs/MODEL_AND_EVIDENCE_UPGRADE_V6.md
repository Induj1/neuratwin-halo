# NeuraTwin Halo v6 — model and evidence release

This release improves eligible winding-temperature forecasts while preserving the previous diagnostic screening. It also adds independently sourced public-data evaluation, a working historical forecast/reveal interface and observation-only review directly in the operations workflow.

## Measured improvement on identical observations

The retained v5 and current v6 fixed-corpus results use the same 480 internally generated cases. All 17,280 target identities match. No coverage changed, and all 53,280 per-minute diagnostic decisions retain the same signals, holds, availability and observed severity.

| Reported hot-spot horizon | v5 MAE | v6 MAE | Reduction | Same scored / possible |
| --- | ---: | ---: | ---: | ---: |
| 5 minutes | 1.62878 °C | 1.39005 °C | 14.66% | 2031 / 2880 |
| 15 minutes | 3.75323 °C | 3.42039 °C | 8.87% | 1999 / 2880 |
| 30 minutes | 7.80750 °C | 7.55796 °C | 3.20% | 1911 / 2880 |

These are paired known-corpus regressions, not fresh evidence or a comparison of competitor accuracy. The independently scored development experiment also improved both plant families. Neither experiment proves fivefold superiority. The 30-minute fixed-corpus P95 absolute error remains 28.97 °C.

Run `python scripts/summarize_model_upgrade.py` to reproduce the paired comparison from retained raw CSVs. The output records their hashes in `reports/model-v6-upgrade.json`.

## How the model changed

`thermal_adaptation.py` identifies winding rise and time constant from the difference between reported hot-spot and oil, driven by maximum-phase loading. A separate healthy-reference review, sufficient input variation, bounded identifiable coefficients, acceptable residuals and chronological validation against both persistence and the configured reference are required.

The first candidate changed both screening and forecasting. It lost six sensor-bias detections and was rejected; its report is retained under `reports/winding-development-candidate/`.

The accepted version applies a qualified reference only after the existing screening and evidence holds pass. It cannot clear a channel-disagreement or cooling-model hold. The accepted development experiment retained all detections, critical warnings and nuisance counts. Oil-only mode explicitly ignores winding calibration. The physical surface probe never becomes a winding or oil sensor. Existing saved cases are not refitted.

## Frozen fresh synthetic evaluation

Sources were frozen before generating 480 cases with 24 previously unused paired seeds. The retained protocol SHA-256 is `ec3a29b467366b197fc0588efcf05abf2fc88bb23fa0a05caf52b0928ee3ebf2`. The one-run claim and raw scoring files match the frozen protocol; the evaluated code was not changed after inspecting the results.

| Target at 30 minutes | Model MAE | Persistence MAE | P95 absolute error | Scored / possible |
| --- | ---: | ---: | ---: | ---: |
| Oil | 2.38326 °C | 6.75787 °C | 7.31963 °C | 2287 / 2880 |
| Reported hot-spot | 6.76219 °C | 12.25352 °C | 24.45211 °C | 1972 / 2880 |

Both the full model and threshold-only policy warned before all 69 critical crossings. The full model was earlier in four, tied in 65 and later in none; overall median additional lead was zero. It completed expected signal sets in 378/432 disturbed cases, versus 347/432 without CUSUM. It had four nuisance episodes / 57 minutes among 20,538 inactive case-minutes; threshold-only had none. There were zero evidence-hold violations. Half the 480 cases qualified for the winding forecast reference.

The v5 fresh run used different seeds. Its error cannot be compared directly with this run as a paired gain; use the identical fixed-corpus comparison above. This is a locally frozen synthetic evaluation, not third-party registration, external fault data or a field trial. An initial freeze command failed before creating a protocol because its own empty stdout log had a JSON extension. The successful freeze included a snapshot of all substantive prior JSON reports, excluding only an unfinished empty stdout log; `pipeline-v6-seed-history-note.json` records this. No scoring run was discarded or repeated.

## External public-data experiment

The unchanged ETTh1 recording, upstream description and license are pinned to their original repository commit. The model sees only a 169-hour prefix. Training, validation and test periods are chronological. All four declared candidates are retained as safe numeric JSON artifacts or numerical baselines; no pickle is loaded.

Validation selected gradient boosting at both horizons. It lost to persistence on the later test segment: MAE 0.42608 versus 0.42023 at one hour, and 1.07883 versus 1.06946 at six hours. These are source units, not verified °C. The six-hour Ridge result was better on test, but selecting it after inspecting test scores would break the evaluation contract, so no substitution was made.

This experiment supplies externally sourced evidence and an inspectable working inference path. It does not establish a forecasting advantage, fault accuracy, physical calibration or a remaining-life model. See `EXTERNAL_ETT_FORECAST.md` for every candidate and the exact split.

## UI review

| Before | After | Why |
| --- | --- | --- |
| Observation-only reasoning was buried in maintenance | Assess readings beside the operating warning | Judges can inspect the evidence without following a scenario label |
| Run navigation and assessment validity shared a run-ID-only guard | Observation reviews also require the exact revision; pending results expire when it changes | Old readings cannot populate a new operating state |
| A withheld health score still showed a confusing 100/100 stress label | The numerical headline is hidden when health is withheld | Missing evidence cannot resemble perfect health |
| Evaluation was internally generated | Separately labelled public-data table and forecast/reveal demonstration | External data, simulations and hardware keep distinct meanings |
| Missing model artifacts exposed filesystem errors | Explicit unavailable response without host paths | Evidence failure remains understandable without disclosing local configuration |

## Verification and remaining limits

The final Python suite passed 409 tests. The JavaScript suite passed 48 tests. The public-data API tests verify units, causal prefixes, integrity failures and absence of simulation/hardware mutations. The paired comparison verifies unchanged screening and coverage. Evaluation status now checks raw scoring CSVs, the report, the frozen protocol and its one-run claim.

A rerun exposed a timing-dependent queue-drain test: the worker continued processing without storage errors, but its hardware-specific 15-second test deadline expired. The test now permits 60 seconds while retaining all 153-job ordering, completion, exactly-once and no-hardware-action assertions. The failed run and successful targeted recheck are retained separately. No production retry rule, diagnostic threshold or numerical model was changed for this test correction.

Browser interaction verified the new observation assessment, explicit holds, public-data score table, forecast and later-observation reveal. Browser control subsequently became unavailable; the final revision-invalidation interaction and mobile visual pass could not be completed. These are marked unverified in `reports/halo-v6-browser.json`. Earlier release screenshots remain historical and are not presented as v6 captures.

Hardware commissioning, measured calibration, independent real-fault evaluation, uncertainty calibration and actual remaining-life inference remain outstanding. The supplied numerical trajectories are conditional decision-support estimates, not safe operating deadlines. The external learned model is a research comparison, not an accuracy champion. No competition outcome or ranking is guaranteed.
