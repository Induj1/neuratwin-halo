# NeuraTwin Halo — historical v5 submission release record

Superseded by [the v6 model and evidence release](MODEL_AND_EVIDENCE_UPGRADE_V6.md). The results and screenshots below describe v5.

This release closes the actionable software findings from the current review. It does not claim a judging score, field predictive accuracy or electrical commissioning. The original Track 2 brief permits simulated datasets and later sensor extension.

## Changes and evidence

| Previous finding | Implemented result | Verification |
| --- | --- | --- |
| Thermal fitting assumed nominal voltage even when voltage was recorded | Squared-voltage core losses in fit, rollout and forecast; incomplete declared voltage is rejected; omitted voltage explicitly remains an assumption | Varying-voltage closed-form identification, API import/retry/rejection tests |
| Phase observations had to fit the simulator's symmetric amplitude pattern | Complete RMS currents independently determine copper heating and maximum-phase winding loading; no phase angles, PF or neutral phasor are invented | Asymmetric phase cases, permutations/scaling, independent exponential solutions and existing simulator consistency tests |
| Observation forecasts passed through scenario-state machinery | Separate observation-only 1–30 minute projection with explicit decision scope; scenario metadata cannot influence it | Hidden-field invariance and thermal consistency checks |
| Recovery stopped at the first 100 jobs on restart | Continuous oldest-due-first worker, durable leased claims, fenced commits, capped backoff, graceful stop, authenticated diagnostics | More-than-100 backlog, poison-job fairness, concurrent ownership, retry, shutdown and cloud-CAS tests |
| Physical decision provenance omitted an explicit analyzer/rule version | Analyzer and rule versions retained alongside acquisition/configuration/calibration identity | Physical provenance regressions |
| Accuracy headlines obscured incremental value and error tails | Paired warning lead times and missing timestamps, false-alarm burden, forecast availability, signed/absolute errors, underprediction and subgroup distributions | Hand-calculated metric tests; regression and separately frozen synthetic evaluation |
| No executable protocol for fresh evidence | Source-bound local protocol before generating unused seeds, exclusive consumed run, report/CSV hashes; documented external recording freeze/reveal API workflow | Replay/overwrite/source-change rejection tests and imported synthetic-recording rehearsal |
| Main reading hierarchy and identical comparison curves confused the decision | Critical temperature/reference moved above instruments, explicit simulated oil input, single trajectory when no intervention exists, readable model, same-run review guide | JavaScript tests and desktop/mobile browser review |

## UI review

| Before | After | Why |
| --- | --- | --- |
| Important temperatures appeared below the instruments | Hot-spot, critical reference, loading and electrical readings precede the instrument row | A projector audience can read the operating decision immediately |
| Health and oil-input scores looked interchangeable | Screening estimate and simulated oil-condition input have separate labels and explanations | Prevents inferred health and scenario inputs from looking like independent measurements |
| Zero-reduction plans displayed two identical alternatives | A single unchanged-input trajectory and explicit no-intervention state | Avoids suggesting an action when none is proposed |
| Maintenance could retain an imported-recordings selection | Guided navigation explicitly selects and checks the current simulation run | Preserves source identity through the demonstration |

## Current verification artifacts

Full suite: **334 Python tests and 47 JavaScript tests passed**. The local HTTP rehearsal completed **264/264 successful requests**, 12 isolated simulation runs and four concurrent clients; observed p95 was **333.360 ms**. This is a defined local workload, not a fleet SLA.

The fresh synthetic evaluation warns earlier in **6/87** critical cases (81 ties), with two false-alarm episodes. Its 30-minute oil MAE is **2.803 °C**; reported hot-spot MAE is **8.899 °C**, P95 **35.038 °C**, with **1870/2880** hot-spot windows scored. Large disturbance errors remain and cannot justify a safe operating countdown.

- Full Python suite: `reports/halo-release-tests.xml`.
- JavaScript suite: `reports/halo-release-js-tests.txt`.
- Desktop/mobile and guided-navigation review: `reports/halo-release-browser.json` and corresponding images.
- Same-source imported reference assessment, inspection, action, comparable follow-up and verified export: `reports/observation-workflow-rehearsal.json`.
- Current known-corpus evaluation: `reports/pipeline-benchmark.json` and its score CSVs.
- Frozen fresh synthetic protocol: `reports/pipeline-v5-fresh-protocol.json`; consumed claim: `reports/pipeline-v5-fresh-protocol-claim.json`; completed report/manifest: `reports/pipeline-v5-fresh-protocol-run/`.
- Isolated local HTTP performance rehearsal: `reports/local-api-performance.json`; its scope is a local synthetic-run workload, not physical fleet certification.
- Extracted submission validation: `reports/submission-package-smoke-current.json`, retained beside the archive to avoid a self-referencing manifest.

The earlier hardening reports and v4 benchmark are historical snapshots. Current benchmark source hashes and the fresh protocol/report binding are also checked by the application's Evidence view.

## Demonstration and acceptance

README and the submission dossier use the same five-minute sequence: one selected simulation → inspect signals → conditional scenario action → same-run maintenance → export and clearly separate dataset-level evidence. Imported recordings are introduced as a new identified source, not substituted for that run. The guided review does not fill in an inspection, claim a repair or operate physical relays.

## Evidence boundaries that remain explicit

- Fresh synthetic seeds are internally selected under a locally frozen protocol. They are not third-party data, new physical assets or a prospective field trial. No tuning is permitted based on this report while retaining a fresh-evaluation claim.
- Forecast errors, missed diagnoses and nuisance alarms remain visible. A sensitivity band is not a calibrated prediction interval, and a 240-minute scenario study is not validated four-hour prediction.
- The health index is an inspectable screening heuristic; actual RUL, failure probability and causal maintenance savings remain unavailable.
- RMS heating assumes equal phase winding resistances and declared mean-current loading. Harmonic eddy loss, phase angle, vector group and general electromagnetic behaviour remain outside the model.
- Physical measurements need reviewed hardware identity, safe commissioning and calibration. Surface temperature is never renamed oil or hot-spot. No hardware was operated during this release work.
- The recovery implementation is stronger, but cloud deployment soak tests and multi-device fleet capacity require their own measured evidence. Local performance results disclose workload and environment.
