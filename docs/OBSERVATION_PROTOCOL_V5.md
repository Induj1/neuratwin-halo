# Observation protocol v5: measured RMS loading and accountable evaluation

This document supersedes the current-method sections of [protocol v4](OBSERVATION_PROTOCOL_V4.md), which remains a historical record. Version 5 changes the observation projection and oil-reference input contract, then evaluates the frozen implementation on both a known regression corpus and previously unused internal synthetic seeds. It does not add field validation or a physical transformer trial.

## Observation model and phase scope

The assessor receives an observed prefix: elapsed time, oil temperature, ambient temperature, aggregate loading, voltage, and a reported hot-spot channel only when declared. Surface temperature from the portable bench is not oil or winding hot-spot temperature. Oil-only assessment scores oil; an inferred winding state is not an observed alarm or validated operating deadline.

Complete optional three-phase RMS current magnitudes can have arbitrary amplitude ratios within the declared 0–60% maximum-deviation imbalance envelope. The supplied aggregate loading is interpreted as **mean-current loading**, so its provenance and nameplate calibration remain prerequisites. Equal phase winding resistances are assumed. Oil copper heating uses RMS-equivalent loading; the winding model uses maximum phase loading:

```text
Imean = (IA + IB + IC) / 3
thermal_loading = mean_loading × sqrt((IA² + IB² + IC²) / 3) / Imean
maximum_phase_loading = mean_loading × max(IA, IB, IC) / Imean
```

The zero-current case is handled explicitly. A scalar imbalance without complete currents retains the labelled illustrative `[1+u, 1, 1-u]` amplitude assumption. With no optional phase data, aggregate input retains an explicitly disclosed balanced assumption. Once phase data is declared, a later missing/inconsistent sample withholds phase-dependent modelling instead of silently supplying balance or zeros.

Neutral RMS, when provided, is a separate measurement. Generic RMS triangle bounds check whether it can be compatible with the three current magnitudes. No neutral value, phase angle, vector group, sequence component or harmonic spectrum is inferred from current magnitudes. Copper heating alone does not account for harmonic eddy losses or unequal winding resistances. Separate consistency tests cover optional phase inputs; the two synthetic benchmark plants do not provide independent phase-physics validation.

## Voltage-aware oil fitting and direct conditional projection

`twin_observer.reference_rows()` validates optional phase scope and substitutes RMS-equivalent loading into the oil reference. The fitter includes recorded per-unit voltage squared in the core-loss term. A legacy calibration file with no voltage column explicitly assumes nominal voltage; a partially populated declared voltage column is rejected. Oil-reference fitting does not identify winding parameters, sensor calibration, insulation condition or fault causes.

The observation projection directly advances nominal oil and winding thermal equations from the last qualified observations. It does not construct an industrial scenario state or read a latent cooling/fault setting. Future voltage, loading and ambient remain constant. Forecast horizons are limited to 1–30 minutes; independent synthetic scoring uses 5, 15 and 30 minutes. Future operating changes and unmodelled faults are not bounded. Real power and served energy are unavailable because current magnitudes alone do not establish power factor.

The separate intervention planner is scenario-informed: it knows the declared cooling and injected conditions of the simulated industrial run. Its 240-minute corner study and action execution checks are internal model-consistency evidence, not independent long-horizon validation, a calibrated interval or proof of real maintenance benefit.

## Evaluation contract

The full pipeline, without-CUSUM ablation and true threshold-only comparator share acquisition/domain gates but retain their own model requirements. A valid observed limit breach is preserved when forecasting is withheld. Threshold-only does not call the residual model, CUSUM or projection and does not inherit the residual model's warm-up requirements.

The complete expected signal set, any warning, and warning before a true synthetic critical crossing remain separate outcomes. Earlier warning categories are retained; an earlier discrepancy indication is not relabelled as a forecasting advantage. The report adds:

- Paired first-warning time differences overall and by condition/family, with missed warnings counted explicitly.
- False-alarm case-minutes, affected cases, contiguous episode durations, and episodes per 100 labelled inactive synthetic case-hours.
- Separate oil and reported hot-spot coverage, paired persistence comparisons, MAE/RMSE, signed and absolute error distributions, underprediction tails and condition/family/time partitions.

All eligible target windows remain in coverage denominators, including future missing targets and withheld forecasts. Overlapping origins and paired seeds are dependent. No significance test, independent-asset confidence interval, field alarm rate or failure probability is claimed.

## Frozen run and retained history

The known-corpus report uses the previously inspected seeds 91001–91024. Its role is implementation regression, not fresh evidence. The preceding v4 artifacts are preserved as:

- `reports/pipeline-v4-before-v5-benchmark.json`
- `reports/pipeline-v4-before-v5-forecasts.csv`
- `reports/pipeline-v4-before-v5-decisions.csv`

The fresh internal synthetic protocol was frozen **before case generation** at `2026-10-08T19:18:36.296682+00:00`. Its 24 randomly selected seeds exclude 91 known reported/development seeds. It covers 480 paired cases across two internal plant families and ten conditions; it does not turn those cases into independent assets.

Protocol: [`pipeline-v5-fresh-protocol.json`](../reports/pipeline-v5-fresh-protocol.json). SHA-256 of its canonical content excluding its own digest field: `40a5e88c54daba826a7e4e83715b90744fd9d478b37403beaff12a8ab212d612`.

The protocol binds eight numerical/evaluation source files and records settings, origins, horizons, comparator definitions and a no-tuning rule. The exclusive run claim and completed manifest bind one execution and the exact report/CSV bytes. This is a local protocol with reproducible hashes, not external preregistration or tamper-proof authorship. Preserve any failures, holds and misses; do not tune from these results and present the same seeds as unseen again.

See [evaluation and external recording instructions](EVALUATION_PROTOCOL_AND_EXTERNAL_RECORDINGS.md) for metric definitions, run semantics and an authenticated externally supplied CSV evaluation path. External recordings must supply truthful source, channel, unit, calibration and configuration evidence; upload does not verify it.

## Completed results — retained without tuning

The single fresh run `EVAL-738d5bf6676f4fee9499b082c4cfcffc` started at `2026-10-08T19:18:49.768494+00:00` and completed at `2026-10-08T19:24:56.875448+00:00`. The report, protocol, claim, manifest and all eight current source hashes agree. The report retains 480 paired cases, 17,280 forecast-target records and 53,280 decision records.

Fresh artifacts: [benchmark](../reports/pipeline-v5-fresh-protocol-run/benchmark.json), [forecasts](../reports/pipeline-v5-fresh-protocol-run/forecasts.csv), [decisions](../reports/pipeline-v5-fresh-protocol-run/decisions.csv), [manifest](../reports/pipeline-v5-fresh-protocol-run/manifest.json). Manifest canonical SHA-256: `14f4f3e410fdc65201f70013edc6dff6e12c86593a8f021e042113399b43a476`. The exact benchmark file's SHA-256 is `f8aa4425b54149088ed27d94a3e247167283e7ba4a5519a57658ff2b4657fea8`.

The 480 fresh cases contain 432 disturbed cases and 48 healthy controls. There are 87 true synthetic critical crossings and 19,206 labelled inactive case-minutes. Oil fitting qualifies in 280 cases; other cases retain labelled default assumptions. Prefixes are shared across conditions, so these are not 280 independently calibrated assets.

| Fresh method | Complete expected signal set / 432 | Any warning / 432 | Warning before critical / 87 | False episodes / minutes |
| --- | ---: | ---: | ---: | ---: |
| Full pipeline | 386 | 409 | 87 | 2 / 47 |
| Without CUSUM | 361 | 397 | 87 | 0 / 0 |
| Threshold only | 192 | 349 | 87 | 0 / 0 |

The full pipeline warns earlier than threshold-only in **6 of 87** critical cases, at the same time in 81 and later in none. All six earlier cases belong to the nonlinear cooling subgroup; every first warning is **model disagreement**, not a conditional limit forecast. Their additional lead is 17–38 minutes, median 18 minutes. The median across all 87 critical cases is **zero**. There is no critical-warning recall improvement in this corpus. Against without-CUSUM, the full method is one minute earlier in one case and tied in 86.

The two fresh false-alarm episodes affect two cases and last 21 and 26 minutes. Their 47 minutes represent 0.245% of labelled inactive time, or 0.625 episodes per 100 inactive synthetic case-hours. All are model-disagreement warnings. Those rates must not be extrapolated to real fleet hours.

| Fresh target | Horizon | Scored / possible | Model MAE °C | Persistence MAE °C | Absolute error P95 °C |
| --- | ---: | ---: | ---: | ---: | ---: |
| Oil | 5 min | 2,369 / 2,880 | 0.711 | 1.324 | 2.180 |
| Oil | 15 min | 2,357 / 2,880 | 1.325 | 3.533 | 3.703 |
| Oil | 30 min | 2,269 / 2,880 | 2.803 | 7.197 | 8.993 |
| Reported hot-spot | 5 min | 1,970 / 2,880 | 1.772 | 2.453 | 4.940 |
| Reported hot-spot | 15 min | 1,958 / 2,880 | 4.574 | 6.860 | 19.192 |
| Reported hot-spot | 30 min | 1,870 / 2,880 | 8.899 | 13.511 | 35.038 |

The model beats persistence on aggregate error, but this is not uniformly accurate forecasting. Fresh 30-minute reported hot-spot coverage is 64.9%, with 1,643 paired wins and 227 losses. Across-disturbance hot-spot windows have MAE 17.825 °C and P95 47.604 °C. The cooling-plus-overload subgroup has hot-spot P95 60.004 °C. Healthy hot-spot windows have MAE 2.300 °C and P95 5.198 °C. These partitions must accompany the overall average.

The largest fresh errors occur in a forecast frozen **before a later cooling-plus-overload disturbance**: nonlinear plant, seed `434603441`, minute 105 origin, 30-minute horizon. Oil is underpredicted by **90.519 °C** and reported hot-spot by **117.617 °C**. Future changes were unavailable to the assessor, but the errors are still retained in the primary scores. They demonstrate why a constant-input trajectory cannot be sold as a safe remaining operating time or an all-fault predictor. Even after-disturbance hot-spot windows retain MAE 4.028 °C and P95 9.803 °C on the 688 of 1,566 eligible windows that remained scorable.

The [known-corpus v5 regression](../reports/pipeline-benchmark.json) retains the v4 aggregate values: full expected-signal completion 381/432; any warning 411/432; all methods early on 82/82 critical crossings; full earlier than threshold in 7, tied in 75; two false episodes totalling 57 of 20,160 inactive minutes. Its 30-minute oil MAE/P95 are 2.654/7.986 °C with 2,247/2,880 coverage; reported hot-spot values are 7.807/29.580 °C with 1,911/2,880 coverage. The v5 method corrections broaden the supported observed-input contract and remove scenario coupling; they are **not evidence of an accuracy gain on these unchanged aggregate cases**.

Both runs retain zero forecast-validity overrides and 24/24 passed simulated action checks. Those verify gating and internal action consistency, not physical accuracy. No model, threshold, metric or scenario was tuned after this fresh result was inspected.

## Remaining validation limits

Synthetic fitting assumes a reviewed healthy prefix and does not establish that a real recording has one. Bounded oil identification and chronological reference-fit validation do not calibrate the winding model. The fresh seeds vary the existing internal plants; they do not add manufacturer diversity, independently measured faults or physical repair evidence. Real asset recordings, ground-truth annotations, calibration, electrical commissioning and a prospective physical evaluation remain necessary before operational claims.
