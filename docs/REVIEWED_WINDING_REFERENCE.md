# Reviewed winding reference: observer v6 development protocol

The candidate identifies the winding temperature rise and time constant from a separately reviewed healthy reference containing reported hot-spot and oil temperatures. It never treats the bench surface probe as either channel. It does not estimate winding coefficients from oil alone, infer sensor calibration, adapt to a fault online, or relax the existing residual, CUSUM or forecast holds.

`thermal_adaptation.fit_winding(observer.winding_reference_rows(prefix), settings, reviewed_healthy=True)` returns evidence and candidate parameters. `apply_winding(settings, evidence)` returns a copied settings dictionary with separate `winding_forecast_reference` evidence when `qualified` is true. It does not replace the base winding coefficients. The observer uses the fitted coefficients only after all configured diagnostic and acquisition holds pass, and only in the forecast projection. Monitoring assessments continue to use saved references; they do not invoke the fitter.

## Identification and qualification

The fitted observation is reported hot-spot minus oil. Maximum-phase loading drives the winding response; oil fitting separately uses RMS-equivalent loading. Aggregate-only records retain their explicit balanced-loading assumption. Missing or inconsistent declared phase channels block fitting.

The model propagates the winding difference with a first-order response, exponent 1.6 and previous-sample held loading. It uses actual sample intervals. A bounded robust least-squares fit estimates log rise and log time constant on the first 70% of the supplied reference; the remaining 30% is untouched chronological validation. The shared boundary observation initializes validation, but no validation sample refits parameters.

Qualification requires all of the following:

- An explicit healthy-reference review, at least 60 complete samples spanning at least 30 minutes, strictly increasing timestamps and gaps no greater than 120 seconds.
- At least 20 percentage points of training loading variation and 2°C of training winding-difference response.
- Supported oil, hot-spot, loading and difference ranges. These are software calibration gates, not electrical safe-operating limits.
- Rise within 5–60°C and time constant within 1–60 minutes, with fits within 1% of a bound rejected; successful optimization, log-Jacobian condition below 1,000 and no more than 10% training residuals exceeding 4°C.
- Validation RMSE at least 5% and 0.05°C lower than both the configured winding reference and persistence of the measured winding difference, on identical validation targets.
- Validation RMSE no greater than 3°C.

These are preregistered engineering acceptance rules for this development experiment; they are not statistical confidence intervals or certification. The coefficient values, bounds, timestamps, sample counts, fit-input SHA-256, qualification failures and validation comparisons remain inspectable.

## Case integration and compatibility

Synthetic challenges explicitly assume their first 70 observations are a healthy commissioning prefix. Imported records require the existing `healthy_reference_reviewed` oil confirmation and a separate optional `winding_reference_reviewed` flag, default false. The latter applies only in `oil_and_hotspot` mode. The uploader's assertion is recorded; it is not independent verification of a real sensor or transformer.

Existing saved cases, settings and assessments are not refitted. Idempotent retries of older imports without the new field preserve their original digest and record. Changed review consent under the same request ID conflicts rather than silently recalibrating. Newly frozen assessments include the adaptation source hash alongside observer, core, study and oil-reference hashes.

Public qualification reports `winding_fit_used` and `winding_reference`. The former means an eligible winding forecast reference was attached, not that diagnostic screening was recalibrated. A rejected or absent reference leaves configured parameters unchanged. Oil-only imports explicitly report that they have no reported hot-spot winding reference, and oil-only assessment ignores winding projection metadata even if a caller supplies it. Invalid stored projection metadata withholds the forecast rather than silently substituting an assumed parameter.

## Development comparison

The development-only script is `scripts/develop_winding_reference.py`. It uses seeds 3101–3112, two existing internal plant families and ten scenarios: 240 cases. It compares v5-equivalent observer logic plus its oil reference with the same logic plus a prefix-qualified winding projection reference. When a prefix does not qualify, both sides use the same unchanged result. It reads no historical evaluation reports or frozen evaluation seeds. Source hashes are recorded before and after the run, including scoring helpers.

Both methods receive identical past observations and forecast future temperatures under held observed inputs. Labels, future observations and hidden plant state enter scoring only. All 4,320 forecast windows per method remain in the denominator, including held forecasts and windows crossing disturbances. Jointly available windows are additionally paired so improved error cannot be claimed merely by withholding difficult cases.

The script records 5/15/30-minute error, coverage, common-target error, family and disturbance partitions, complete expected signal sets, warnings before critical temperature, false warning minutes and false warning episodes. Per-minute decisions and forecast rows are exported. Shared prefixes and overlapping horizons make rows statistically dependent; these counts are not independent field trials.

A separate prospective evaluation with frozen sources and previously unused seeds is required after any development promotion. Old v5 fresh results remain historical and must not be renamed as new-model results.

### Rejected first candidate

The first candidate replaced winding coefficients for both projection and diagnostic screening. Its preserved report is `reports/winding-development-candidate/benchmark.json`, with complete forecast and decision CSV files. It qualified 100 of 240 cases (10 of 24 distinct family/seed prefixes). Common-target MAE improved from 1.581 to 1.385°C at 5 minutes, 4.706 to 4.289°C at 15 minutes and 9.647 to 9.050°C at 30 minutes. However, complete expected signal sets fell from 194 to 188: six sensor-bias cases lost their discrepancy signal. Critical warnings and nuisance totals did not reveal that regression.

That candidate is rejected. Forecast-error gains do not justify suppressing a previously detected signal. The revised candidate keeps all screening coefficients and residual/CUSUM rules unchanged and applies fitting only to eligible projections. Its independent rerun of the same development corpus is stored separately at `reports/winding-development-projection-only/`; this is development iteration, not fresh evaluation.

### Projection-only result and promotion

The revised development run completed on 2026-10-09 at 04:00:57 UTC with all recorded source hashes unchanged during execution. It retained exactly the same 2,654 jointly scorable forecast targets out of 4,320 possible targets. No target moved between available and withheld status. Its reference fitted 100 cases, representing 10 of 24 family/seed prefixes; the repeated scenarios share reference data and are not independent fits.

| Horizon | V5-equivalent MAE | Projection-only MAE | V5-equivalent RMSE | Projection-only RMSE | Scored / possible |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5 minutes | 1.59550°C | 1.40000°C | 2.23151°C | 1.97162°C | 906 / 1,440 |
| 15 minutes | 4.71874°C | 4.30263°C | 8.34707°C | 8.06242°C | 894 / 1,440 |
| 30 minutes | 9.64832°C | 9.05403°C | 15.44212°C | 15.11970°C | 854 / 1,440 |

Both plant families improved mean absolute error at each horizon. Healthy-case 30-minute MAE improved from 2.56867 to 2.13037°C. Complete expected signal sets remained 194; there were no lost complete detections. All 54 cases with a critical-temperature crossing retained a warning before crossing. Nuisance remained 36 inactive-case minutes in one episode. Those are dependent synthetic counts, not clinical-style sensitivity or field guarantees.

This supports promoting the projection-only method to observer version 6 for a separately frozen prospective evaluation. The version label was advanced after this development measurement; the numerical candidate in the report is the promoted method. Base diagnostic screening remains conservative even when the fitted projection reference would disagree with it.

The improvement is modest and conditional. At 30 minutes the 95th-percentile absolute error remains 32.17094°C, and only 59.31% of all possible targets are scored. Future disturbances remain unknowable to a constant-input forecast. These results do not support a fivefold improvement, field accuracy, diagnostic certainty or guaranteed safe operating time.

## Verification

Focused tests exercise distinct analytic coefficients, variable cadence, train and validation outliers, missing data, non-exciting input, invalid timestamps, bounds, source-channel identity, phase loading, causal prefix isolation, immutable legacy cases, separate review consent, oil-only gating and frozen source hashes. Analytic fixtures check implementation consistency and do not constitute independent plant validation.

Remaining limits include uncertain hot-spot sensor identity, calibration and placement; synthetic plant dependence; unobserved future loading and ambient changes; unknown cooling physics; no probabilistic coverage guarantee; and no validated remaining-life inference. The physical hardware demonstration still measures transformer surface temperature.
