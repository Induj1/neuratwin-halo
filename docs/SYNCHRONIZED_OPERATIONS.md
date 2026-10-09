# Synchronized transformer operations

Implemented 8 October 2026 for the NeuraTwin Halo Track 2 demonstrator.

Open `/app#operate`. The model, waveforms, condition dial and readings share one selected telemetry/assessment packet. Load and phase-imbalance sliders apply continuously to the selected industrial simulation. Electrical values change on input; temperature changes only as the simulation clock advances.

## Presenter sequence

1. Create a new industrial run. The initial thermal state is an illustrative starting condition, not a measured or necessarily steady-state transformer.
2. Increase load to about **112%** and imbalance to **6%**. Read the phase amplitudes, neutral current and loading contribution. These inputs remain below the default immediate-trip loading threshold, but are an overload demonstration, not a permitted hardware operating point.
3. Start the thermal response. Use **Advance 5 min** to reveal slower temperature changes. The illustration uses the selected run's configured thermal thresholds. A voltage warning alone does not turn the transformer into a thermal alarm.
4. Inspect **Choose the next hour**. Compare unchanged demand with the recommended reduction: central peak temperature, curtailed energy and the separate 240-minute sensitivity peak. The comparison assumes held inputs and ignores protection to show consequences; it is not a forecast of the protection system's actual operation.
5. Apply the recommendation. Current changes immediately; stored heat cannot disappear instantly. Temperature can continue rising briefly after a reduction. Imbalance ratios remain until the phase allocation is changed; demand reduction is not phase balancing or cooling repair.
6. Select **Explore recorded history**, an active signal or a timeline event. Replay pauses this industrial run, labels the selected observation and disables operating commands. Scrub from the baseline through the event and mitigation. Exit replay; the current run remains paused until explicitly started.

## What the instruments mean

| Instrument | Source and limitation |
|---|---|
| Health screening dial | Existing weighted screening calculation. Not a failure probability, validated remaining life or certification of health. |
| Operating stress index | Separate existing score shown when health is withheld. Higher values mean less modelled stress; active severity always remains visible and controls the ring colour. |
| Contribution bars | Thermal, electrical, loading, accumulated, ambient and oil stresses. Zero means no contribution indicated by this calculation; N/A means unavailable. These are unweighted stress components, so their numbers do not sum directly to the dial. The electrical component is the capped maximum of 200 × voltage deviation (pu) and 2 × current imbalance (%), an illustrative heuristic rather than a standard. |
| 3D highlight | An explanatory link to a sensor/component or whole-asset context. It does not localize a physical defect. Industrial geometry does not claim a sensor at every bushing or winding. |
| Industrial currents | Mean RMS demand multiplied by `[1+u, 1, 1-u]`, with assumed 120° phase angles. Neutral is the phasor return sum. No harmonics, measured phase angles, sequence network or vector-group diagnosis. |
| Industrial heating | Mean-square phase current affects copper loss; maximum phase loading affects the winding rise and overload checks. The balanced default preserves the earlier model. |
| Waveform | Illustrative sine reconstruction, peak = √2 × RMS, 50 Hz assumed. Animation is slowed. The hardware firmware supplies RMS summaries, not sample buffers. |
| Waveform scale | Industrial current uses a stable scale based on 160% of rated phase RMS current; larger peaks expand the axis. Prototype views auto-scale. Axis bounds and units are stated. |
| Prototype | Single-phase primary/secondary voltage and available current only. One secondary current sensor does not supply primary current. No oil or insulation-history contribution is claimed. Surface temperature is not winding or oil temperature. |
| Intervention | Enumerated, conditional simulation actions. 16 parameter corners over 240 minutes; one-hour energy display. The action is rechecked against the current run revision before application. No physical relay command. |
| Replay | Stored readings, settings, assessment and input context. Older rows without component snapshots show N/A, not a score recalculated with current settings. Same-time timeline actions use a recorded event cursor where available; otherwise ambiguous same-time events are omitted. |

The waveform supports channel selection, pause/resume, pointer inspection and keyboard time inspection. Reduced-motion preference starts visual motion paused. Hidden/offscreen panels stop animating. Changing a waveform's visual pause does not pause the transformer simulation; the two controls are labelled separately.

## Implementation and verification

- `web/halo-command.js`: synchronized instrument rendering, contribution availability, causal explanations and replay projection.
- `web/halo-waveform.js`: RMS reconstruction, phasor neutral, plotting and inspection.
- `web/halo-operate.js`: revision-aware actions, coalesced sliders, source isolation and replay controls.
- `neuratwin/twin_core.py`: phase state, losses, thermal response, protection and retained assessments.
- `neuratwin/twin_studies.py`: same-state consequence comparison and candidate checks.
- `neuratwin/twin_study_api.py`: read-only preview and recorded/apply workflow.

The preview endpoint is `GET /api/halo/twin/runs/{id}/intervention-preview?revision=N&horizon_min=60&max_delay_min=0`. It writes no plan or event; stale revisions fail. Applying first records a plan, then uses the existing revision-checked apply endpoint.

Tests cover phase cancellation, imbalance, losses, temperature lag, planner/execution agreement, read-only preview, stale revisions, prototype isolation, nullable-health exports, RMS scaling, missing channels and historical-state leakage. See `reports/halo-synchronized-tests.xml`, `reports/halo-synchronized-browser.json`, `tests/test_synchronized_twin.py`, `tests/test_waveform.mjs` and `tests/test_command.mjs`.

An additional evidence-view regression is fixed: a valid observed threshold breach remains prominent even if no diagnostic hypothesis is established or a missing channel blocks the forecast. Oil-only inference is not promoted to an observed hot-spot alarm. The numerical forecast and diagnostic-evaluation semantics are unchanged; see `tests/test_observer_severity.py`.

## UI review

| Before | After | Why |
|---|---|---|
| Small condition number and detached readings | Large dial beside geometry and waveform, with linked contributions | Makes the cause and response inspectable in one workspace |
| Static current summaries | Explicitly illustrative phase/neutral curves with an amplitude reference | Shows the electrical effect without inventing measured waveforms |
| Intervention available on another screen | Two curves and the apply action beside the warning | Puts the decision beside its consequences |
| Historical trend only | Recorded-state scrub with disabled operating actions | Explains incidents without confusing past and current state |
| Score could overwhelm an alarm | Severity-coloured dial and explicit health-withheld label | A reassuring aggregate cannot erase an observed breach |

Remaining physical work: identify and commission the transformer and sensors, calibrate acquisition, verify ADC and relay interfaces, and record a supervised load experiment. These software changes do not certify the 230 V assembly or establish field predictive accuracy. The internal competitor action plan is separate from the submission package.
