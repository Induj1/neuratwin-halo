# Observation protocol v4: phase scope and fair comparators

**Historical v4 record.** Current methods are documented in [Observation protocol v5](OBSERVATION_PROTOCOL_V5.md). The symmetric-only phase family, 120-degree neutral-consistency assumption and nominal-voltage-only fitting described below apply to the retired v4 observation contract, not the current observer. The industrial simulator retains its explicitly declared illustrative phase family. V4 results and raw records are archived as `reports/pipeline-v4-before-v5-benchmark.json`, `reports/pipeline-v4-before-v5-forecasts.csv` and `reports/pipeline-v4-before-v5-decisions.csv`.

This correction uses the existing v3 corpus and numerical settings. Evaluation seeds remain 91001–91024, development seeds remain 3101–3112, and the plant families, injected conditions, thresholds, noise levels, forecast origins and forecast horizons are unchanged. The evaluation cases were inspected during earlier review. This run is a **fixed-protocol regression**, not a new unseen evaluation or evidence of physical accuracy. No thresholds were tuned to improve these scores.

The previous report and raw records are retained as `reports/pipeline-v3-before-v4-benchmark.json`, `reports/pipeline-v3-before-v4-forecasts.csv` and `reports/pipeline-v3-before-v4-decisions.csv`. The archived v4 report identifies `observation-pipeline-4` and records hashes of its numerical sources.

## Optional phase observations

The six original columns remain the required aggregate contract: `elapsed_s`, `oil_c`, `hotspot_c`, `ambient_c`, `load_percent`, and `voltage_pu`. In declared oil-only mode the reported hot-spot column is not required or used.

Optional columns are `phase_current_a`, `phase_current_b`, `phase_current_c`, `neutral_current`, `phase_imbalance_percent`, `max_phase_loading_percent`, and `thermal_loading_percent`. Missing optional columns are omitted, rather than inserted as zero. A reported imbalance alone can specify the supported amplitude model. Complete three-phase RMS currents can identify the same relative model. Partial current sets, missing promised phase samples, negative/nonfinite values or incompatible phase summaries withhold phase-dependent forecasts.

The supported phase family is a permutation of mean RMS current multiplied by `[1+u, 1, 1-u]`, for `0 ≤ u ≤ 0.6`. Oil copper heating uses the mean-square loading factor `1 + 2u²/3`; winding response and overload checks use maximum phase loading. If neutral current is supplied with phase currents, it must be consistent with the assumed fundamental 120-degree phasors. This limited contract does not establish measured phase angles, arbitrary amplitude patterns, harmonics, vector groups, winding connections or sensor calibration. Phase-current ratios are relative to the supplied aggregate loading; absolute current-to-nameplate calibration remains an external prerequisite.

When all phase columns are absent, legacy observations retain the previous balanced-loading assumption and explicitly disclose it. An absent measurement is not evidence that the phases are balanced. If a time series starts declaring phase data, a later missing phase sample does not silently revert to aggregate mode. Historical observations before the declared scope constitute a gap for the phase-dependent reference; new contiguous evidence is required.

Oil-reference fitting must use `twin_observer.reference_rows()` for phase-scoped recordings. It validates phase scope and supplies RMS-equivalent loading to the existing oil fitter. The fitter still assumes nominal voltage and does not calibrate winding parameters. An oil-only assessment uses phase-aware oil heating and can display electrical imbalance severity, but it never presents its inferred hot-spot as an observed alarm or validated countdown.

The phase regressions reproduce the previous 70% mean-load, 20%/60% imbalance counterexamples. Operations and the observation assessor now retain the imbalance warning/critical severity, while expected phase heating does not become a spurious channel-disagreement hypothesis. Agreement with the industrial simulation is an internal consistency test. The fixed synthetic benchmark corpus does not independently validate unbalanced physical transformers.

## Three distinct comparators

| Comparator | Uses | Excludes |
| --- | --- | --- |
| Full pipeline | Valid observed thresholds, short-window thermal residual, channel agreement, CUSUM and qualified conditional forecast | Fault labels, hidden state and future observations |
| Without CUSUM | The same pipeline with CUSUM disabled | CUSUM only; residuals and forecasts remain |
| Threshold only | Valid observed limits and acquisition/domain holds | Residual model, channel-disagreement inference, CUSUM, forecasts and any cooling/sensor root-cause inference |

Threshold-only and full assessment share available-input, domain and timebase gates. A valid breach in another channel remains visible when a required reference is missing. Instantaneous thresholds do not need the residual model's 15-sample warm-up or healthy commissioning prefix; inheriting those model-specific holds would make the comparator artificial. Threshold-only never calls the residual, CUSUM or projection routines.

The previous `baseline_*` fields represented the without-CUSUM ablation. They are now named `without_cusum_*`. The report's explicit `comparators` objects expose all three methods at case, class and overall levels. The UI must not label the ablation as threshold-only.

## Two outcomes, with separate false-alarm counts

**Expected-signal-set completion** requires every predefined signal for the injected condition concurrently. It is stricter than raising a warning and still does not establish a real-world root cause. A high-temperature threshold cannot count as identifying cooling failure or sensor bias. Combined scenarios require all expected signals.

**Any warning** counts a valid observed limit, acquisition/domain hold, model-disagreement signal, or an available conditional projection reaching its critical threshold. Insufficient evidence alone is not an alarm. The decision CSV retains the warning kinds, so a forecast warning can be distinguished from an electrical limit or missing-channel warning. A useful warning must occur after the injected onset and before the true synthetic critical crossing. This timing measure does not establish a safe operating deadline or correct diagnosis.

Both outcomes retain their own timing measures. Any-warning false-alarm minutes and contiguous episodes use labelled inactive synthetic minutes as the denominator; historical diagnostic-only false-alarm fields remain separately reported. Adding forecast warnings can raise sensitivity and false alarms together. The comparison does not suppress either cost.

## Completed v4 regression

The 480 cases comprise 432 disturbed cases and 48 healthy controls. The report's comparator `total` counts all cases; event coverage uses only the 432 disturbed cases. Critical-crossing coverage uses the 82 disturbed cases that actually cross the synthetic critical threshold. False alarms use 20,160 labelled inactive case-minutes, including healthy controls and pre-onset minutes.

| Method | Complete expected signal set / 432 | Any warning / 432 | Any warning before critical / 82 | False-alarm episodes / minutes |
| --- | ---: | ---: | ---: | ---: |
| Full pipeline | 381 | 411 | 82 | 2 / 57 |
| Without CUSUM | 359 | 398 | 82 | 0 / 0 |
| Threshold only | 192 | 350 | 82 | 0 / 0 |

All three methods warn before all 82 critical crossings, so this corpus establishes no improvement in critical-warning recall. The full pipeline completes more expected diagnostic signal sets and warns in more noncritical disturbed cases, with two false-alarm episodes. Threshold-only completion covers the predefined electrical/acquisition signal sets; a high-temperature warning does not complete a cooling or sensor-bias diagnostic signal set. Neither result measures real-world diagnostic accuracy.

Cooling expected signals complete in 32/48 cases with the full pipeline and 20/48 without CUSUM; combined cooling+overload completes in 33/48 and 23/48. Four of 24 critical combined cases lack complete diagnostic signals before crossing, although all methods raise a warning before those crossings. Hot-spot and oil forecast scores, partition and family scores, and all 24 simulator intervention checks are numerically unchanged from the archived v3 report. There are zero forecast-validity overrides.

The machine-readable [v4 protocol manifest](../reports/pipeline-v4-protocol.json) records these denominators and the completed run's source hashes. It was exported after this correction and is not a new preregistration. Results are in [the archived v4 benchmark report](../reports/pipeline-v4-before-v5-benchmark.json), with archived raw forecast and decision CSVs alongside it.

## Coverage and remaining limits

The report retains all 480 **paired synthetic cases**, rather than calling them independent assets. Seeds are reused across conditions, origins overlap, and only two plant families are present. Oil and reported hot-spot targets remain separate; missing/withheld targets stay in the denominator. The report exposes error tails and disjoint before/across/after-disturbance partitions. Source hashes demonstrate which code produced a report, not that the model is physically accurate.

All model-disagreement and acquisition holds continue to withhold forecasts and countdowns. An observed critical condition still controls the presentation even when no residual hypothesis is established. Present severity, forecast qualification and diagnostic evidence are separate contracts.

The independent plant benchmark scores only 5-, 15- and 30-minute trajectories. The planner's 240-minute, 16-corner study remains an illustrative sensitivity exercise, not a calibrated confidence interval or independently validated safety bound. The existing 24 intervention checks compare planning and execution within the same industrial simulator. Physical calibration, measured transformer recordings, independent relay/contact and timing evidence, manufacturer-specific references, and a genuinely fresh prospective evaluation remain necessary.

Verification: `tests/test_observer_phase_baselines.py`, `tests/test_observer_severity.py`, `tests/test_decision_validity.py`, and `python scripts/benchmark_pipeline.py --split evaluation`.
