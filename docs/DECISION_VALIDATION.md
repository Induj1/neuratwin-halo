# Decision validation and limits

This document covers the revised industrial software workflow. The physical bench remains separately gated and measures surface temperature, not transformer oil or winding hot-spot.

## What changed

| Defect or gap | Implemented correction | Evidence |
| --- | --- | --- |
| Planner reduced an additive overcurrent disturbance but execution did not | Both use the same requested-demand transition; effective loading includes the remaining disturbance | Overcurrent API regression and 24 executed intervention cases |
| Acceptable present temperature hid a later critical breach | Conditional forward risk appears in operating state, next action and maintenance advice | Historical-run and forecast-warning regressions |
| Coupled parameter changes missed a worse thermal trajectory | All 16 independent ±15% oil/winding rise/time-constant corners; 240-minute thermal assessment separate from the energy horizon | Adverse-corner regression |
| Brief recovery or continued cooling defect could be marked repaired | Numerical acceptance rules, uninterrupted stable window, qualified channels, no active disturbance, restored cooling and forward check | Reproducible isolated workflow rejects closure, records stabilization, then completes simulated repair and verification |
| Oil-model benchmark did not evaluate the deployed hot-spot path | Observation-only pipeline calls the real analysis/projection functions; separate targets and baselines | `reports/pipeline-benchmark.json` and raw CSV |
| Scenario labels could explain the answer | Assessor allowlists measured fields; blind endpoint commits a case before freezing assessment and revealing ground truth | Label-exclusion and reveal-order tests |

Planning remains a discrete enumeration, not a globally optimal dispatch solution. A tested parameter envelope is not a confidence interval or a guarantee against unseen faults. Fault duration is held constant for the consequence study; the app states that assumption. Software protection is illustrative, never a substitute for independent hardware protection.

## Reproducible protocol · v3 corpus / v4 correction

Run `python scripts/benchmark_pipeline.py --split evaluation`. The protocol in `reports/pipeline-v3-protocol.json` was frozen before testing seeds 91001–91024. Development reuses 3101–3112. Each seed is paired across ten conditions and two independently implemented plant families: nonlinear oil cooling and a separate radiator thermal-storage model. The 480 cases are synthetic, not 480 independent physical assets. Disturbance onset varies between minutes 90 and 115.

The first 70 assumed-healthy observations may identify oil parameters. Parameter fitting uses a chronological training/validation split and must beat persistence before activation. Winding parameters remain illustrative. No fault label, future row, true winding temperature or cooling setting enters the assessor. Combined-case detection requires all expected signals concurrently.

The observation contract declares either `oil_only` or `oil_and_hotspot`. Missing a promised hot-spot channel does not silently switch modes. In oil-only mode, observed oil and electrical inputs support residual checks and conditional oil forecasts; hot-spot is a separately labelled estimate with an assumed initial winding equilibrium. It is neither an observed channel nor a validated time to critical. Surface-probe readings cannot be imported as oil.

Missing/out-of-domain values, invalid timing, insufficient contiguous observations, channel disagreement and thermal deviation withhold forecasts. Electrical alarms remain visible but cannot override those holds. The audited optimistic 9-minute countdown is now withheld at the same origin; the subsequent 3-minute critical crossing is retained in the regression.

CUSUM uses actual intervals up to two minutes, non-overlapping blocks ending at the first observed sample at/after five minutes, and innovations normalised to five minutes. Bias uses the first 60 healthy minutes; noise uses the first 60 samples. Threshold and allowance remain the predefined noise-aware screening rule. Gaps disable the commissioning CUSUM; later observations cannot silently become a new healthy reference. The short-window residual remains available after sufficient new contiguous evidence. Voltage-dependent core loss is included in residual prediction. This identifies model disagreement, not a confirmed cooling root cause.

Forecast origins remain 75/90/105/120/135/150 minutes and horizons 5/15/30 minutes. Oil-only and reported hot-spot targets are scored separately. Every withheld/missing target remains in the denominator. Headline scores include unpredictable future disturbances, with disjoint healthy, before-onset, across-onset and after-onset slices. True synthetic target error is also reported separately, never passed into inference. Complete expected diagnostic signals and any warning before the true synthetic 125 °C crossing are separate outcomes; an observed temperature alarm can warn without identifying its cause.

The original observation-pipeline-3 benchmark evaluated 480 paired cases from 24 then-held-out seeds, ten conditions and two synthetic thermal plant families. The current **observation-pipeline-4** reruns that fixed corpus to correct phase scope and comparator semantics. Seeds 91001–91024 have now been inspected; the rerun is regression evidence, not a new unseen evaluation. Thresholds, plant cases, noise, origins and horizons were not tuned for this correction. The earlier 88001–88024 cases remain historical evidence. See `docs/OBSERVATION_PROTOCOL_V4.md` for the phase contract and the separate threshold-only and without-CUSUM methods.

Oil-only mode predicts the observed oil channel. Inferred winding hot-spot is labelled separately and never supplies a validated countdown or measured health input.

| Oil horizon | Model MAE | Persistence MAE | P95 error | Scored / possible |
| --- | ---: | ---: | ---: | ---: |
| 5 min | 0.683 °C | 1.311 °C | 2.243 °C | 2367 / 2880 |
| 15 min | 1.205 °C | 3.486 °C | 3.536 °C | 2335 / 2880 |
| 30 min | 2.654 °C | 7.107 °C | 7.986 °C | 2247 / 2880 |

| Reported hot-spot horizon | Model MAE | Persistence MAE | P95 error | Scored / possible |
| --- | ---: | ---: | ---: | ---: |
| 5 min | 1.629 °C | 2.378 °C | 4.279 °C | 2031 / 2880 |
| 15 min | 3.753 °C | 6.729 °C | 15.907 °C | 1999 / 2880 |
| 30 min | 7.807 °C | 13.337 °C | 29.580 °C | 1911 / 2880 |

Thermal-model disagreement now withholds forecasts and limit countdowns, even during an overload. This fixes the audited case that predicted nine minutes to critical when the independent synthetic plant crossed in three. The health index is withheld during active operational/evidence holds; the separate stress arithmetic remains inspectable.

Cooling signals were detected in 32/48 cases versus 20/48 with CUSUM disabled; combined cooling+overload in 33/48 versus 23/48. Sensor bias: 42/48; overload+sensor bias: 40/48. Two healthy-control false-alarm episodes occurred. All seven critical cooling cases were warned before crossing, while four of 24 critical cooling+overload cases lacked the complete expected signal set before crossing. These limitations remain visible. Zero forecast-validity overrides occurred; all 24 feasible simulated interventions matched execution.

Threshold-only uses valid observed limits and acquisition/domain holds, without residuals, CUSUM, forecasts or inferred cooling/sensor root causes. The without-CUSUM ablation retains residuals and forecasts. The 480 cases include 432 disturbed cases and 48 healthy controls; `comparators.total` counts all cases, while event coverage uses the disturbed cases only.

| Method | Complete expected signal set / 432 | Any warning / 432 | Any warning before critical / 82 | False-alarm episodes / minutes |
| --- | ---: | ---: | ---: | ---: |
| Full pipeline | 381 | 411 | 82 | 2 / 57 |
| Without CUSUM | 359 | 398 | 82 | 0 / 0 |
| Threshold only | 192 | 350 | 82 | 0 / 0 |

False alarms use 20,160 labelled inactive synthetic case-minutes. All three methods warn before all 82 critical crossings, so the corpus establishes no critical-warning recall advantage. The full pipeline completes more diagnostic signal sets and warns in more noncritical disturbed cases at a false-alarm cost. Forecast, partition, family and intervention results are numerically unchanged from the archived v3 report.

Headline forecast scores retain windows with future disturbances. The report also exposes disjoint healthy, before-onset, across-onset and after-onset partitions, per-family results, true synthetic temperature errors and all unscored reasons. Neither better average error nor withholding difficult cases proves safe operating time. Two synthetic families, paired seeds, correlated origins and assumed healthy commissioning still limit generalization.

See the original `reports/pipeline-v3-protocol.json`, the exported regression manifest `reports/pipeline-v4-protocol.json`, current `reports/pipeline-benchmark.json`, raw score CSVs and `docs/OBSERVATION_PROTOCOL_V4.md`. The v4 manifest is not a new preregistration. Historical v1/v2 reports and the pre-correction v3 report/CSVs remain clearly named. No field-accuracy or remaining-life claim is made.

The intervention checks establish simulator consistency, not independent accuracy. The 240-minute sensitivity study is not independently validated at that horizon and is not a confidence interval.

## Blind demonstration and maintenance

Evidence → choose temperature capability → Prepare an unseen case → Freeze observation assessment → Reveal later readings. Oil-only is the default. CSV import uses the same assessor and retains its frozen decision after reload. It requires a reviewed healthy prefix and is labelled retrospective, since its uploader already knows the recording. The server commits a salted digest of the case; reveal returns the observations, plant truth and nonce for verification. The saved assessment cannot be rewritten on a repeated assess request. A hash detects changes against a retained commitment, not authorship; the backend operator is not treated as an adversarial third party. Download the experiment before preparing another.

Work orders encode stable minutes, maximum load, maximum reported temperature, forecast horizon and cooling-restoration requirement. Additional prose is not machine-verified. A stabilized order remains unresolved. Closure records its acceptance result and observations; a later current assessment is separate from the historical record. Legacy records are not silently rewritten or granted new verification.

A declared cooling impairment keeps the industrial operating warning active after demand is reduced. The interface labels this as a scenario condition, separate from observation-only diagnosis. Its condition index is unavailable while active holds remain; the separate operating-stress score preserves the arithmetic without claiming verified health. Reduced loading cannot clear the maintenance hold.

Run `python scripts/rehearse_submission.py` for the complete recovery workflow in disposable SQLite. It loads no `.env`, does not open serial ports and disables hardware control. It replaces only the labelled synthetic rehearsal artifacts under `reports/`.

## Evidence still needed

An asset-specific manufacturer/test reference; independently calibrated physical voltage/current/surface acquisition; verified controller/winding identity and protection; recorded healthy and fault data from more than one real asset; timing/dropout/endurance tests; prospective field assessment with a predefined protocol. The present software cannot establish actual RUL, fault probability, standards compliance, electrical safety or a competition outcome.

## Bench and transport evidence

`/app#lab` provides acquisition diagnostics, exact-sample reference checks, immutable surface forecasts, later-observation scoring, annotated interventions and offline replay exports. The emulator stays outside `halo_frames`, never activates physical calibration/models and cannot pass through the USB bridge. Physical recordings require live acquisition to start and cannot advance a synthetic clock or alter loads. Saving a recovery note is explicitly separate from verified maintenance closure.

`reports/bench-workflow-rehearsal.json` covers the full isolated experiment; `reports/transport-recovery.json` records a real disposable API-process restart plus durable outbox recovery after a lost acknowledgement. Tests cover simultaneous sensor/electrical faults, missing history, stale configuration, boot identity, USB silence, expired acknowledgements and a protection latch appearing before command delivery. These checks do not verify a physical relay or firmware watchdog timing.
