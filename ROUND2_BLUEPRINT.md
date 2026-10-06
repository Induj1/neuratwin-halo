# Neura Rangers: Round 2 solution blueprint

Prepared 22 September 2026. Status: researched proposal, not an implemented or validated Round 2 system. The organizer's detailed dataset, scoring rubric and hardware requirements are still unknown.

## Recommended concept: NeuraTwin

**A distribution-transformer digital twin that turns electrical and thermal measurements into an explained maintenance decision, with a forecast of what changes if the operator acts.**

The main demonstration should answer four questions: What is happening? Is the measurement trustworthy? What might happen next? Which feasible action improves the forecast?

Start with one configurable mineral-oil distribution transformer. Its rating, cooling arrangement, losses, insulation assumptions and operating limits must be explicit. These are provisional scope choices, not facts supplied by the organizer. Add a small fleet view once one asset works end to end.

Commercial transformer monitoring already combines sensor streams and asset-management insights; Hitachi Energy's TXpert is one example. Our proposed distinction is an inspectable, reproducible workflow connecting measurement confidence, thermal forecasts and comparative action simulation. This is a product direction, not a claim of worldwide novelty. [Hitachi Energy](https://www.hitachienergy.com/products-and-solutions/transformers/the-txpert-ecosystem)

## What the organizers have actually published

The public statement asks for continuous monitoring, health assessment, anomaly detection, early warning, maintenance recommendations and an intuitive dashboard. Detailed information, datasets and instructions are to be emailed to the team lead after registering for a problem. Each problem has a maximum of ten teams. [Official problem statements](https://www.powernext-ai.in/problem-statements)

The published preparation period is 21 September–9 October 2026, followed by the finale on 10–11 October. The main page lists finalist registration ending 20 September. Check the existing registration confirmation and team-lead inbox, including spam; if the detailed pack is missing, contact the organizers. This blueprint does not establish whether your problem allocation is confirmed. [Official timeline and contact](https://www.powernext-ai.in/)

## Core implementation

| Component | Proposed behavior | Evidence shown to the judge |
|---|---|---|
| Asset and telemetry layer | Store the asset configuration, timestamped readings, units, data source and quality flags. Support replay first, then a live adapter if available. | The same measurement stream drives the model, charts and alerts. Replay is labelled as replay. |
| Dynamic thermal twin | Update estimated oil and winding thermal states as load and ambient conditions change. Fit uncertain parameters using suitable observations. | Measured versus expected temperature, thermal lag, model residual and parameter provenance. |
| Forecasting | Predict temperature over candidate 30-, 60- and 120-minute horizons where sampling permits. | Forecast bands, assumptions about future load/ambient, and historical errors by horizon. |
| Anomaly reasoning | Combine input-quality checks with persistent departures from the expected thermal/electrical response. | Evidence, onset, duration, severity, plausible causes and missing evidence. |
| Health assessment | Show a transparent thermal-condition index and separate electrical-stress, ageing-exposure and data-confidence indicators. | A drill-down showing why each indicator changed and which measurements are unavailable. |
| Maintenance support | Rank evidence-linked actions and log operator acknowledgement and follow-up. | A maintenance card with asset, reason, urgency, proposed inspection and verification step. |
| What-if simulation | Compare continued operation with an operator-specified load reduction or another physically supported intervention. | Forecasts from the same initial state, predicted limit exposure, uncertainty and feasibility assumptions. |

A health index is initially an engineering screening score. Its weights must be visible, and it must not be described as a calibrated failure probability or percentage of life remaining. Missing condition data should lower confidence rather than make an asset appear healthy.

## Modelling choices

Use a compact thermal model with memory: current state plus incoming load and ambient conditions determine the next state. Oil and winding heating/cooling need different response times. Learn an additional residual correction only if it improves held-out forecasts over the physical model and simple baselines.

IEC 60076-7 covers mineral-oil transformers, operating temperatures, loading and thermal ageing. Its public catalog establishes the relevant scope; the full standard has not been inspected for this proposal. Obtain the applicable equations, parameters and limits from legitimately available technical material or the organizer before claiming standards compliance. A dry-type transformer would require a different model and applicable guidance. [IEC 60076-7:2018](https://webstore.iec.ch/en/publication/34351)

Estimate a winding hot-spot only when asset parameters support it. If there is no independent hot-spot measurement, label this an estimated state; oil-temperature prediction accuracy alone does not validate it. Likewise, a temperature-based ageing exposure estimate does not reveal absolute remaining service life without insulation condition and operating history.

For electrical stress, compute phase loading and voltage deviations when those channels exist. Harmonic analysis needs suitable waveforms or measured harmonic information. Slow aggregate RMS telemetry cannot establish a harmonic spectrum. Transformer-internal fault diagnosis may need additional evidence such as oil analysis; commercial DGA monitoring actually measures gases in oil. [Vaisala OPT100 measurement description](https://docs.vaisala.com/r/M211858EN-AC/en-US/GUID-EA8C57F8-663B-4E30-801F-C8AE56C6FFB4)

## Measurement confidence is the key engineering feature

Distinguish measurement-quality alarms from equipment-condition alarms. Check timestamps, units, missingness, impossible values, stale readings, implausible rates of change and agreement with independent channels.

A rising thermal residual can indicate impaired heat rejection, altered losses, a sensor bias or model mismatch. One temperature channel may not identify which explanation is correct. In that case, show “unexplained thermal deviation—verify measurement and cooling condition,” list the evidence, and recommend the next discriminating check. Demonstrate specific sensor-fault diagnosis only when independent evidence supports it.

Maintain an anomaly-detection reference so online parameter adaptation does not silently learn a developing fault as normal. Quarantine suspect intervals from automatic calibration and log model updates.

Reuse Round 1's ingestion, testing and reproducibility discipline, but rebuild its model assumptions for this task. Its learned current boundary and thermal hinge are not field-transformer laws. Its duplicate-input invalidity rule is also unsuitable for ordinary time series: equal readings at different timestamps can be legitimate. Detect retransmissions using asset ID, timestamp and message identity; evaluate stuck sensors using time and changing operating conditions.

## Data strategy

1. **Organizer data:** first choice for the final schema, model fit and evaluation. Inspect sampling, units, asset IDs, nameplate information, measured targets and fault/maintenance labels before selecting the final algorithms.
2. **Public forecasting benchmark:** ETT-small provides load-related features and oil temperature from two transformers. It can support an external oil-temperature forecasting experiment. Its listed columns do not supply the ambient, nameplate, maintenance-event or failure labels needed to validate the entire proposed twin. Do not interpret its load feature names as physical phase-current channels without documentation. [Dataset authors](https://github.com/zhouhaoyi/ETDataset)
3. **Independent scenario simulator:** create clearly labelled synthetic streams for overload, changing ambient temperature, reduced heat rejection, sensor drift, dropouts and timestamp failures. Vary parameters and noise between development and test scenarios. A model tested only against its own generating equation is not independently validated.

ETDataset's repository contains a CC BY-ND 4.0 license. Keep attribution and provenance; review the terms before bundling or redistributing dataset material. Use independently generated synthetic cases for fault injection instead of presenting altered public data as observed failures. [Repository license](https://github.com/zhouhaoyi/ETDataset/blob/main/LICENSE)

## Dashboard: four focused views

**Fleet overview:** asset cards ranked by condition and evidence quality, latest reading time, active alerts and queued inspections. A map is optional; condition ranking is the useful first view.

**Asset twin:** nameplate/configuration, a simple transformer schematic, measured and estimated states, load and temperature history, forecast bands and a clear separation between measured and inferred values.

**Incident investigation:** alert timeline, observed-versus-expected behavior, channels supporting or contradicting each hypothesis, confidence and the next recommended check.

**Action comparison:** change the proposed load trajectory and compare predicted thermal exposure. Display the operator's assumptions. Actual switching or load transfer is outside the prototype; any future transfer recommendation would also need network topology and receiving-asset capacity.

A plain-language maintenance card can use deterministic templates initially. If an LLM is added, it should explain structured model outputs and cite their evidence; numerical states, alarm limits and diagnoses must still come from the evaluated pipeline.

## Judge demonstration: one coherent incident

1. Replay normal operation and show the twin tracking measured temperature with its expected lag.
2. Increase load in a labelled simulated scenario. Show the projected approach to an asset-configured temperature limit before that limit is reached.
3. Introduce a separate sensor-bias scenario. Where independent channels distinguish it, raise a measurement alert; where they do not, explicitly show diagnostic uncertainty.
4. Compare “continue as forecast” with a proposed load reduction. Recompute both futures from the same initial state and show the change in predicted thermal exposure.
5. Create a maintenance recommendation containing the evidence, proposed action, urgency and check needed to close the incident.
6. Open the evaluation panel: display forecast errors, alert performance, data origin and unresolved limitations.

Exact temperatures, lead times and savings must come from the eventual model run. They are not prewritten success numbers. Forecast time to a configured temperature limit is conditional on the future-load scenario; it is not time to transformer failure.

## Validation that makes the claim defensible

| Claim | Proposed test | Report |
|---|---|---|
| Useful temperature prediction | Chronological held-out periods; hold out whole assets when enough exist. Fit preprocessing on training only. | MAE/RMSE by horizon and operating regime, compared with persistence, a seasonal baseline and the thermal model alone. |
| Useful warning | Held-out labelled incidents or independently generated scenarios, evaluated separately. | Event precision/recall, false alarms per asset-day, detection delay and warning lead time. |
| Honest forecast uncertainty | Reserve a time-ordered calibration segment and test separately. | Empirical interval coverage and width; no untested coverage guarantee. |
| Resilient telemetry handling | Missing/stale/out-of-order readings, reconnects, unit errors and legitimate repeated values. | Correct state handling, confidence changes, alert behavior and replay reproducibility. |
| Useful action comparison | Known interventions in a separate simulator or observed intervention records where available. | Forecast response and sensitivity to model/parameter uncertainty. Real cost savings remain unclaimed without field evidence. |

Never use actual future load or ambient as though it were available at forecast time. Such a run is an explicitly labelled oracle experiment. Freeze the test partition and acceptance criteria before repeated tuning. NIST identifies verification, validation and uncertainty quantification as central to credible digital-twin decision support. [NIST credibility research](https://www.nist.gov/publications/credibility-consideration-digital-twins-manufacturing)

## Proposed build sequence

| Dates | Deliverable |
|---|---|
| 22–24 September | Confirm the detailed pack; define asset/data contracts, replay pipeline, baseline forecast and frozen evaluation protocol. |
| 25–29 September | Implement the dynamic twin, quality checks, residual alerts and forecast evaluation. |
| 30 September–3 October | Complete the asset dashboard, incident explanations and action comparison. |
| 4–6 October | Run held-out tests and failure scenarios; produce evidence tables and fix observed failures. |
| 7–9 October | Freeze the demo, prepare an offline replay, documentation and pitch, and rehearse judge questions. |

These are proposed internal milestones, not organizer deadlines. Adapt the scope when the official dataset and submission instructions arrive. Hardware is an optional extension until required; a supervised low-voltage educational demonstration can validate the telemetry path, but cannot substitute for full-scale transformer validation.

The first engineering milestone is **one asset, one timestamped stream, one validated thermal forecast, one explained alert, and one recomputed action scenario**. Fleet polish and additional diagnostic modules follow that working loop.
