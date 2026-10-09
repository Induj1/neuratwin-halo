# Public ETTh1 oil-temperature forecasting

This statistical forecasting experiment is separate from Halo's observed thermal-reference model, industrial scenario simulator and physical bench. It predicts the public dataset's reported oil-temperature target; it does not diagnose faults, identify remaining life or validate physical hardware.

## Source and permitted representation

Source: Haoyi Zhou and collaborators, [ETDataset](https://github.com/zhouhaoyi/ETDataset/tree/1d16c8f4f943005d613b5bc962e9eeb06058cf07), ETTh1 hourly series. The upstream authors describe collected transformer data and six external power-load channels. The columns retain their original meanings: `date,HUFL,HULL,MUFL,MULL,LUFL,LULL,OT`. No load column is renamed current, voltage, ambient temperature or rated loading. No corresponding nameplate or calibration has been supplied.

The [pinned README](https://github.com/zhouhaoyi/ETDataset/blob/1d16c8f4f943005d613b5bc962e9eeb06058cf07/README.md) identifies OT as oil temperature but does not state its physical unit. Results are therefore **source units**, never claimed °C. Timestamp timezone is unspecified. Actual CSV intervals must be hourly; README wording for the separate minute series is not used to infer this file's cadence.

The upstream [CC BY-ND 4.0 license](https://github.com/zhouhaoyi/ETDataset/blob/1d16c8f4f943005d613b5bc962e9eeb06058cf07/LICENSE), original README and raw CSV are preserved byte-for-byte under `data/external/ett/`. Provenance includes the pinned URL and SHA-256 of each file. The dataset is not republished as a transformed table. Features are constructed locally in memory; report metrics and numeric model parameters are our analytical outputs. Preserve source attribution and license when distributing the unchanged source material. The upstream authors do not endorse Halo.

Citation: Haoyi Zhou et al., *Informer: Beyond Efficient Transformer for Long Sequence Time-Series Forecasting*, AAAI 2021, 35(12), 11106–11115. [Paper](https://arxiv.org/abs/2012.07436).

## Frozen experiment

`reports/external-ett-protocol.json` is written before fitting and scoring. It binds the two new source files, dependency specification, dataset hash, features, candidate settings, splits and selection rule. `external-ett-claim.json` exclusively consumes one execution. Failures are retained; do not delete the claim to seek a preferred result.

| Partition | Raw row indices, half open | Purpose |
| --- | --- | --- |
| Training | 0–8640 | Fit scaler, Ridge and gradient boosting only |
| Validation | 8640–11520 | Select the lowest-MAE candidate independently for each horizon |
| Test | 11520–14400 | One final comparison of every frozen candidate |
| Remaining rows | 14400 onward | Excluded; no tuning or alternative test selection |

These fixed 12/4/4 blocks use 30-day-month benchmark arithmetic, not calendar-month boundaries. They are one chronological split, not a claim of representative industrial assets or independent prospective field observations. The public series is already widely available; local test withholding is not third-party custody.

Forecast horizons are **1 hour and 6 hours**. Each origin uses the previous 169 hourly observations including its current reading. Features comprise past OT differences at hours 1–24/48/72/168, current OT, causal rolling oil means and standard deviations, current/lagged/rolling original power-load channels, and calendar hour/weekday cycles. No future load, temperature, fault state or target enters the features. Every target must stay inside its partition; the final horizon-sized block of origins is purged. Validation/test prefixes may use earlier observed history, as a deployed forecaster would.

Missing/nonfinite required observations, duplicate timestamps or a nonhourly prefix withhold the forecast. Missing targets remain in coverage counts. No missing measurement is filled with zero.

## Predeclared candidates and selection

- Persistence: predict the last observed OT.
- Seasonal persistence: predict the observed OT from 24 hours before the target timestamp.
- Ridge regression, alpha 100: train-only standardized features predict change from current OT.
- HistGradientBoostingRegressor: absolute-error loss, learning rate 0.05, 180 iterations, maximum 15 leaves, minimum 40 samples per leaf, L2 10, random seed 17, no early stopping. It predicts OT change with the same causal features.

The lowest validation MAE determines the selected model separately for each horizon, including the option of selecting persistence. Ties follow candidate order. Models are not refitted on validation. Numeric models and validation results are saved before test scoring; test outcomes cannot switch the deployed selection. Poorer candidate results and test losses are retained. There is no promised improvement factor.

Report metrics use identical available targets for all candidates: coverage, MAE, RMSE, median/P95/maximum absolute errors, signed bias and underprediction tails. Paired wins/losses and calendar-month subgroups expose heterogeneity. Overlapping windows are dependent; no significance claim or calibrated prediction interval is made.

## Run and verify

The source CSV is pinned at:

`https://raw.githubusercontent.com/zhouhaoyi/ETDataset/1d16c8f4f943005d613b5bc962e9eeb06058cf07/ETT-small/ETTh1.csv`

SHA-256: `f18de3ad269cef59bb07b5438d79bb3042d3be49bdeecf01c1cd6d29695ee066`.

```powershell
python scripts/evaluate_external_forecast.py freeze
python scripts/evaluate_external_forecast.py run
python -m pytest tests/test_external_forecast.py -q
```

An existing protocol or claim cannot be overwritten. Completed files remain the authoritative first run. Reproduction of a known result must use a distinct, honestly labelled experiment; the tool intentionally provides no overwrite or preferred-result retry option.

`forecast-models.json` stores numeric coefficients/scaler values and numeric tree nodes. No pickle, dynamic import from the artifact, or serialized executable is loaded. Exported tree predictions are checked against the fitted sklearn estimator before test scoring. The production helper checks model/report/protocol/claim/source binding and upstream bytes. Hashes detect changes against retained files, not authorship.

## Application contract

- `neuratwin.external_forecast.public_status()` returns the source-bound report with `available`, `status`, `integrity`, provenance, selected models, validation/test metrics, paired comparisons and subgroup results. A missing report is explicitly unavailable; altered evidence raises an error.
- `predict_prefix(prefix, horizon_hours)` accepts only the observed prefix, loads the selected numeric artifact and returns a forecast for a frozen horizon. There is no physical control or generic hardware-model promotion.
- `demo(origin_index=11520, history_hours=48)` displays a deterministic origin within 11520–14393. Forecasting receives only the preceding 169 observations. Later actuals are added separately for a clearly labelled **retrospective historical comparison**. They are not part of model inference.

The default demonstration origin is predeclared, not selected for an impressive successful forecast. A slider may inspect any permitted test origin, including poor predictions. User inspection after evaluation cannot create a new unseen-validation claim.

## Limits

The dataset supplies no reviewed fault-onset labels, maintenance outcomes, sensor calibration or hardware-side pairing. This benchmark cannot establish failure detection, physical repair, Indian distribution-transformer transfer, causality, or operational safety. Statistical oil forecasting and a physics-informed twin answer different questions; neither's error can be compared to another system without matching units, task, horizon, split and coverage.

## Completed first run: no superior-accuracy claim

Run `ETT-bafa2cf5b9fa4c9baaf738b8c9b8b887` completed with all candidates and the validation selection retained. Protocol digest: `18d863834ad5cc9f08adfb6ee373b629ff7fec3b5945a26ca771d334761b3cc4`. Report canonical digest: `42a688b21c32fba74bc2fdb081fc957f3f9e264770ab6f21a249d3929702c99f`. Model canonical digest: `6b608448de29311361dfe5dffd84cdf6b0de630443ae7bf9a9faf6c77c927e37`.

The source contains 17,420 observations; only the frozen first 14,400 participate in this experiment. The chronological test targets end on 20 February 2018, with test origins starting 24 October 2017. This is a retrospective public-data study.

| Horizon / model | Validation MAE | Test MAE | Test RMSE | Test P95 absolute error |
| --- | ---: | ---: | ---: | ---: |
| 1h persistence | 0.60838 | **0.42023** | 0.59307 | 1.19600 |
| 1h seasonal persistence | 1.97347 | 1.52667 | 1.96461 | 3.93910 |
| 1h Ridge | 0.58781 | 0.43237 | 0.58755 | 1.24212 |
| 1h gradient boosting — validation selection | **0.56478** | 0.42608 | 0.59179 | 1.25960 |
| 6h persistence | 1.59457 | 1.06946 | 1.41466 | 2.88500 |
| 6h seasonal persistence | 1.97438 | 1.52512 | 1.96360 | 3.93935 |
| 6h Ridge | 1.33229 | **1.03976** | 1.32260 | 2.63067 |
| 6h gradient boosting — validation selection | **1.25655** | 1.07883 | 1.40993 | 2.92262 |

All errors are **source units**. Coverage is 2,879/2,879 eligible one-hour targets and 2,874/2,874 eligible six-hour targets, after the respective predeclared boundary purges.

Gradient boosting wins validation at both horizons but its **test MAE is 1.39% worse than persistence at one hour and 0.88% worse at six hours**. One-hour paired test comparisons favour it on 1,371 targets and persistence on 1,508; six-hour counts are 1,399 and 1,475. Six-hour Ridge is 2.78% lower-MAE than persistence on test, but it was not the validation-selected model. It cannot be silently promoted using this observed test result and then represented as an untouched evaluation.

The outcome supports retaining the simple baseline and treating the frozen gradient-boosting selection as a research comparison, not a production accuracy champion. The report preserves test-month subgroups and every candidate loss. Subsequent model development requires a separately documented experiment and genuinely unused evaluation evidence; this run remains known evidence. No model, feature, split or hyperparameter was tuned after inspecting these results.

Verification: 22 focused tests passed across causality, purging, missing-data holds, numeric-model parity, unsupported horizons, safe tree traversal, exclusive protocol creation and evidence-chain tampering. `public_status()` verifies the complete live evidence chain; the default historical demo has been executed successfully from the retained numeric artifact.
