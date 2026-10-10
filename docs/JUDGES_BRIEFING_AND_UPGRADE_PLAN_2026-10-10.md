# NeuraTwin Halo: judges' briefing and upgrade plan

Date: 10 October 2026  
Status: Core additions implemented locally. See [the implemented features and verification scope](BRIEFING_FEATURES.md). The planning requirements below remain the acceptance reference; field validation and new pressure hardware are not claimed.

Reconciled with [the briefing corrections](../../NEURATWIN_HALO_BRIEFING_CORRECTIONS_2026-10-10.md) and the current local working tree on 10 October 2026. The corrections reference the same Git commit, but their description of uncommitted frontend work predates the user-requested loading and Demo health changes. Preserve those authorised changes; distinguish them from the backend assessment.

## Briefing captured by the team

The following points were reported from the judges' briefing:

- Pressure buildup can exceed a transformer's enclosure capability and cause rupture. Identify pressure abnormalities and assess the usefulness of pressure sensors.
- Identify short circuits and explain how they are discriminated from other conditions.
- Address rated capacity, short-circuit capacity, transformer impedance, overload capacity and percentage impedance. The briefing mentioned 4.5–5% impedance.
- Address hot-spot temperatures and protection of distribution transformers.
- Include predictive maintenance.
- Keep the implementation economical and consider smart-meter data.
- The briefing cited an Indian transformer failure rate around 6–7%, with a desired reduction below 2%.
- The note “thermal capacity marketing” needs clarification before being quoted as a formal requirement; it may refer to thermal capacity or rating/marking.
- “DTRs” likely means distribution transformers in this context; do not automatically interpret it as dynamic thermal rating.

The failure figures and impedance range are briefing notes, not independently verified universal values. Below 2% is an intended field outcome, not a result established by this prototype.

## Direction

Show how Halo distinguishes faults, predicts worsening conditions and supports an appropriate response at a practical cost. Use the interface and 3D model to explain these decisions through visible cause and effect.

Existing foundations include transformer profiles with parameter provenance, observation-only assessment and hidden-ground-truth challenges, industrial thermal modelling, forecasts, intervention comparisons, parameter-corner checks, event replay and a maintenance work-order lifecycle. Extend these capabilities instead of rebuilding them. The main new work is electrical fault discrimination, impedance-based fault modelling, pressure monitoring and complete PDF reporting.

| Area | Existing capability to reuse | Extension |
| --- | --- | --- |
| Electrical model | Ratings, losses, limits and parameter provenance | Percentage impedance, frequency, consistent bases and source assumptions |
| Diagnosis | Observation-only assessment and blind challenges | Electrical classes, suitable signals and explicit abstention |
| Thermal studies | Oil/winding models, forecasts and intervention studies | Controlled cold-versus-hot paired demonstration |
| Maintenance | Ownership, priority, investigation, verification and closure | Route new findings through existing acceptance checks |
| Pressure | Existing gas scenarios are distinct from pressure | Explicit pressure scenarios/model and decisions |
| Reporting | Full retained industrial-run JSON/CSV/HTML ZIP | Immutable report snapshot and direct PDF |

Keep the physical bench and industrial simulation distinct:

- Prototype: the team's single-phase transformer labelled 12-0-12 V, voltage sensing, secondary-current acquisition, a DS18B20 surface-temperature probe, ESP32 and relay-controlled resistive load bank. Report installed channels' actual acquisition and calibration status. Independent primary-current measurement is not established: the reviewed firmware defaults to `USE_MEASURED_MAINS_CURRENT = false` and calculates primary current. The team reports four 39-ohm/10 W resistors; the Wi-Fi frontend currently exposes three active branches and one virtual cutoff demonstration. The user-supplied 1 A rating is the declared prototype loading reference, subject to transformer/winding verification.
- Active mapping: M1 → `load1`, M2 → `load2`, M3 → `load4`; M4 has no hardware branch and requests all three active branches OFF. An acknowledgment establishes a controller response, not independently verified contact opening or transformer isolation.
- Industrial: an explicitly simulated distribution transformer with its own ratings and modelled oil/winding thermal states. Do not reuse the bench's 1 A rating as an industrial rating.
- Preserve the existing frontend voltage/current demonstration logic during these upgrades unless a change is explicitly requested.
- Keep both indicator paths explicit. The backend combines multiple stresses and may withhold its condition index. The separate frontend **Demo health** indicator now exists, following the user's explicit request, and uses displayed secondary-current loading against 1 A: `score = 100 - clamp(loading_percent - 80, 0, 100)`. It is a current-only demonstration indicator, not validated physical asset health or failure probability. Do not substitute it into backend protection, stored health history or withheld assessments.

## P0. Channel provenance and display snapshot

Preserve the intentional frontend fallback and its existing formulas:

```text
R_eff = 39 ohms / active branches
I_secondary_est = V_secondary / R_eff
I_primary_est = V_secondary * I_secondary_est / V_primary
```

The frontend primary-current estimate assumes ideal power balance, unity power factor and no losses. The firmware's calculated-primary path separately uses an efficiency setting of 0.80. Identify the actual method; do not change these formulas or treat their results as independent measurements.

Current working-tree policy: the frontend scope and annotations use the existing fallback; prototype loading and the separate Demo health dial now consume that displayed current. Backend raw current, protection and multivariable assessment remain separate. This is newer than sections 4–5 of the correction document.

Required work:

- Record value-level sources: `measured`, `firmware_calculated`, `frontend_estimated`, `simulated`, `unavailable`; calibration and freshness remain separate properties.
- Preserve raw values alongside displayed estimates, with timestamp, sample/boot identity, active branches, voltage inputs, assumptions, fallback reason and calculation version.
- Fix the confirmed provenance defect: `zeroCurrent()` currently treats missing current as near-zero current. Missing must not be described as “measured 0 A.” Any missing-data estimation needs a separate eligibility policy and explanation.
- Keep stale/cache status attached to estimates. The scope now freezes on stale/unreachable packets; this does not by itself correct every source-label or historical-report issue.
- Do not use a derived primary current as independent evidence for differential protection, measured losses, efficiency or internal fault identification.
- Version both backend indicators and the separate demo calculation in reports; preserve withheld historical scores and their reasons. Never replace a withheld historical result with a demo score of 100.

Acceptance covers nonzero measured current, finite near-zero current, missing channels, stale data, no active branches and board reboot. Selected display values, source labels and PDF snapshot values must agree. These corrections are planned; this document update does not implement them.

## 1. Fault discrimination

Extend the existing observation-only assessment and hidden-ground-truth challenge contracts to distinguish normal operation, overload, energisation inrush, external short circuit, suspected internal fault, sensor failure and insufficient evidence/ambiguous cases. Do not create a second challenge interface unnecessarily.

The judge selects or randomly triggers an event. The diagnostic logic receives the resulting signals, not the injected event's name. The interface then shows:

1. Suspected condition and uncertainty.
2. Signals supporting the decision.
3. Important missing evidence or competing explanations.
4. Recommended response.
5. A replay and comparison of the outcome with and without intervention.

Keep scenario ground truth separate from diagnostic inputs so that evaluation measures actual discrimination. Exclude answer-revealing scenario identifiers, hidden plant state and future samples. Freeze the assessment before revealing ground truth; uncertain and incorrect results must remain in the record.

Evaluate held-out parameter sets or recordings, normal cases, noise, missing channels and overlapping conditions. Do not split adjacent windows of one event between training and test sets. Include challenging inrush/CT-saturation cases if claiming robustness to them. Report class counts, per-class precision/recall, a confusion matrix, abstention coverage, a defined false-alarm denominator and detection delay from known onset, against a declared simple baseline. Keep synthetic evaluation separate from field evidence.

High current alone does not establish a short circuit: energisation inrush can also produce high current. Advanced discrimination can use compensated differential currents, harmonics and waveform features, with attention to CT saturation and limitations of harmonic-only methods.

The current ESP32 RMS telemetry and frontend reconstructed sine waves do not establish those waveform features. Demonstrate advanced discrimination with explicitly simulated or recorded waveform data unless appropriate acquisition is implemented and validated. Differential analysis requires independent time-aligned current observations and applicable ratio/phase compensation; estimated primary current does not qualify. A browser/cloud workflow is supervisory; it does not replace local protection relays or establish protection-speed performance.

## 2. Transformer ratings and percentage impedance

Extend the existing transformer profile and electrical model with percentage impedance and its provenance, frequency, voltage/current bases, connection assumptions and source-impedance assumptions. Reuse existing ratings and limits. Replace the current hardcoded short-circuit voltage/load multiplier within a declared scope; the existing load-dependent voltage-drop approximation is not a measured nameplate impedance.

For a simplified transformer-limited terminal fault with a stiff upstream source:

```text
Prospective short-circuit current ≈ rated current / impedance in per unit
At 5% impedance: prospective current ≈ 20 × rated current
```

Label the result as a simplified prospective symmetrical RMS fault current on the selected base, not instantaneous peak or asymmetrical making current. Declare fault type, location and source strength. Combine transformer, source and cable impedances on consistent units/bases, not arbitrary percentages. Reject or withhold missing, zero and invalid impedance. Prospective current is different from interrupting rating, short-circuit withstand and permissible overload current/duration.

Acceptance: changing impedance changes current; the 5% example is reproducible; bases and assumptions travel into replay and PDF. All short-circuit demonstrations remain simulated, with no physical short-circuit tests on the bench.

Use the briefing's 4.5–5% range as an illustrative industrial profile only until a particular transformer's nameplate or test data supports it. Do not assign it to the bench transformer as a measured property.

## 3. Thermal margin and intervention

Add a paired view/preset with identical transformer parameters, ambient conditions, cooling and imposed load, differing only in declared initial thermal state. Reuse existing oil/winding models, intervention assumptions and parameter-corner checks to explain differences in margin and time to a configured limit.

Show:

- Measured versus modelled temperature, with units and source.
- Conditional time to a configured thermal limit.
- The trajectory if current conditions continue.
- The trajectory after a proposed load reduction or cooling intervention.
- Applicable equipment limits and model assumptions.

The bench sensor measures surface temperature. Do not relabel it as winding hot-spot or oil temperature. Predicted overload duration is conditional on the model and declared limits; it is not a blanket operating clearance.

## 4. Pressure monitoring

Add pressure level, rate of rise and escalation events to the industrial oil-filled transformer twin. Define tank arrangement, sensing location, units, gauge versus absolute reference, sample cadence, filtering, hysteresis and sensor-failure states. Pressure thresholds/delays require equipment references or explicit scenario assumptions; do not invent universal rupture thresholds.

Pressure is distinct from the existing gas scenario. Label a scripted pressure trace as a scenario signal unless a physical model has actually been implemented and validated. Abnormal pressure alone does not confirm an internal fault or guarantee rupture prediction. Missing pressure stays unavailable without suppressing unrelated electrical alarms. Pressure findings must feed replay, work orders and PDF consistently.

The present bench has no oil-filled tank or pressure sensor. Keep its pressure channel unavailable. An optional separate low-pressure sensor demonstration can illustrate acquisition and detection, but must not be presented as tank-pressure measurement from the bench transformer.

Distinguish functions clearly: a pressure sensor or sudden-pressure relay detects a condition; a pressure-relief device physically limits overpressure. Detection alone does not prove prevention of tank rupture.

## 5. Predictive maintenance and economical deployment

Route findings into the existing work-order lifecycle, including evidence links, owner, priority, action and acceptance criteria. Reuse investigation, verification and closure checks. Unresolved conditions, missing required evidence or failed recovery checks must prevent unsupported closure. A closed software record does not establish a physical repair.

Responses must match the finding: compare load reduction for overload; request cooling inspection for abnormal thermal response; explain uncertainty for suspected inrush; demonstrate simulated protection/clearing and investigation for suspected short circuits; escalate abnormal industrial pressure; and request channel verification for missing/inconsistent data. Do not use “reduce load and recover” as the universal outcome. Preserve distinctions between simulated protection, physical command request, acknowledgment and verified contact state.

Show a basic tier that uses available meter data and an extended tier that adds sensors only where they improve diagnostic capability. Document component, installation, communications and maintenance costs when actual estimates are available; do not claim savings from an unpriced concept.

Treat smart meters as an available data source subject to their actual channels, cadence and access. Slow meter summaries cannot substitute for fast waveform acquisition needed by certain protection methods.

## 6. PDF export: all readings and reports

User-requested addition: export readings and reports as a downloadable PDF for both Industrial and Prototype modes.

Provide a clear **Export PDF** action for the selected run/session, with a time-range option when needed. The export should produce a self-contained, readable document rather than a screenshot of the dashboard.

### Shared content

- Report title, actual asset/run/session identity when available, selected mode, reporting interval, timezone and generation time. Do not invent identifiers.
- Transformer profile, ratings and the configuration/model version relevant to the selected records.
- Summary of observations, alerts, analysis and recommended actions.
- All readings retained for the selected interval, with timestamps, units and quality/source labels in a paginated appendix. Do not silently export only the recent points visible on screen.
- Charts for available voltage, current, loading and temperature channels; additional channels only when available for that mode.
- Fault/event history, decisions, interventions, maintenance records and available comparison/forecast reports relevant to the selected interval.
- Data gaps, stale/cached periods and unavailable channels preserved explicitly; missing values must not become zero.
- Clear distinctions between measured data, estimates, frontend demonstration values and industrial simulation results.

### Industrial report

Include rated kVA, voltages/currents, percentage impedance when configured, scenario inputs, phase currents and imbalance where available, modelled oil/hot-spot temperatures, loading, screening results, forecasts, intervention comparisons, simulated breaker events and maintenance history.

Include new fault-discrimination and pressure results once those features exist. Label simulated pressure, fault events and protection actions as simulated. Record assumptions behind thermal predictions and capacity calculations.

### Prototype report

Include primary/secondary voltage and current, surface temperature, loading relative to the user-specified 1 A rating, relay command states, connection/data-quality status, and observed events.

If displayed current is estimated or simulated by the frontend, export the same displayed value and its source label. Preserve any distinct raw sensor value separately where available. The report must not silently substitute a backend zero for the displayed estimate or present an estimate as a measured current.

Label the frontend current-based health score as a demo score and include its calculation basis. Do not export it as validated physical asset health. Do not add oil, winding hot-spot, pressure or three-phase readings to the prototype report unless those sources actually exist.

### Export implementation and acceptance

- Reuse the industrial ZIP export's full retained run history. Dashboard arrays are limited views. The prototype frame accessor defaults to 600 records and event retrieval to 100; these are query limits, not proof of deletion. Select all retained records for the authenticated report scope/interval, with pagination where needed. The industrial progression guard is 5,000 history entries; report actual coverage.
- The browser estimate buffer is bounded and cleared on reboot. A later calculation from retained inputs must be labelled retrospective, not presented as the exact historical value displayed at the time.
- Capture a consistent report snapshot so live updates cannot make the summary, charts and tables disagree during generation.
- Persist or capture the frontend demo/derived values and their calculation basis if required to reproduce them in a server-generated PDF. State coverage limits if historical displayed values were not retained; do not invent them retrospectively.
- Generate a direct `.pdf` download with selectable text, readable charts, page numbers, repeated table headers and working page breaks.
- Support both complete selected-run/session exports and explicit time-range exports. Summaries may aggregate charts, but the readings appendix must retain every available selected record.
- If a requested period includes data no longer retained, state the actual coverage. Do not describe a partial export as complete.
- Allow exports of retained records while the ESP32 is offline, clearly identifying the last received timestamp and stale status.
- Use the actual existing identities where available and exclude credentials, tokens, environment variables and unrelated internal development notes.
- Verify both modes, long reports, missing channels, disconnection, and consistency between exported readings and the displayed/export snapshot values.
- Verify record counts/identities beyond UI and default query limits, no-data intervals, board reboot and raw-zero versus missing-current cases. Apply existing access controls to the selected records.
- Existing CSV/JSON or printable HTML exports remain useful, but do not by themselves satisfy the requested downloadable PDF feature.

## Build order and demonstration

Revised sequence after the corrections review:

| Priority | Deliverable | Completion evidence |
| --- | --- | --- |
| P0 | Correct hardware/source descriptions, missing-versus-zero provenance and immutable report contract | Consistent labels, mapping and snapshot checks; preserve authorised frontend demo behaviour |
| P1 | Extend electrical profile and impedance-based fault model | Parameter-effect tests, valid bases, explicit assumptions |
| P2 | Extend observation-only electrical discrimination | Frozen blind assessments, baseline comparison, class metrics and abstention results |
| P3 | Direct PDF for Industrial and Prototype | Complete retained records, readable long PDFs and display/snapshot agreement |
| P4 | Pressure scenarios and condition-specific decisions | Source-labelled signals integrated into events, replay and reporting |
| P5 | Integrate paired thermal demonstration, maintenance and presentation | Reuse existing studies/workflow in one rehearsed sequence |

The shared report snapshot contract starts at P0 and continues alongside model work. Every implemented feature should feed the report instead of maintaining a separate presentation-only result.

The demonstration should follow one complete sequence: identify the transformer and sources, introduce an undisclosed event, freeze the diagnosis, reveal ground truth, explain evidence/uncertainty, demonstrate a condition-appropriate response, link maintenance acceptance criteria and export the complete retained evidence as a PDF.

Evaluate detection accuracy, false alarms, warning lead time and simulated intervention outcomes. A demonstrated reduction in real fleet failure rate requires field evidence; it cannot be inferred from a hackathon simulation.

## Technical references

- [SEL: A New Inrush Detection Algorithm for Transformer Differential Protection](https://cdn.selinc.com/assets/Literature/Publications/Technical%20Papers/6643_NewInrush_BK_20140117_Web.pdf?v=20180604-155115) — inrush discrimination and limitations of second-harmonic-only methods.
- [Schneider Electric: transformer available fault-current calculation](https://www.se.com/us/en/faqs/FA105006/) — simplified rated-current/impedance calculation and source assumption.
- [Hitachi Energy: sudden-pressure relay](https://www.hitachienergy.com/us/en/products-and-solutions/insulation-and-components/transformer-insulation-components/measurement-and-safety-devices/pressure-and-flow-devices/sudden-pressure-relay-spr) — detecting sudden gas-pressure rise.
- [Hitachi Energy: pressure-relief device](https://www.hitachienergy.com/jp/ja/products-and-solutions/insulation-and-components/transformer-insulation-components/measurement-and-safety-devices/pressure-relief-device) — limiting tank overpressure and reducing rupture risk.
- [Dynamic thermal rating assessment of oil-immersed power transformers for multiple operating conditions](https://ietresearch.onlinelibrary.wiley.com/doi/full/10.1049/hve2.12333) — thermal rating under hot-spot, oil-temperature, ageing and equipment constraints.
