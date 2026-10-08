# NeuraTwin: Industrial and Prototype modes

Implemented against `transformer_digital_twin_spec.md`, supplied on 8 October 2026.

Open **Digital twin** at `/app#operate`. The two sources share the telemetry contract,
condition analysis, trends, alerts and monitoring view. Their physical meaning and
actuation paths remain distinct. Existing Bench inspector, Action Lab, Evidence,
Maintenance, Commissioning and Grid Rescue features are retained.

## Quick demonstration

1. Select **Industrial** and create a run. The assumed asset is a balanced three-phase
   630 kVA, 11 kV / 433 V transformer. All values in this mode are synthetic.
2. Apply **Sustained overload**. Loading becomes 140% of rated secondary current.
   A critical loading signal appears; the breaker initially remains closed.
3. Start the simulation. Each tick advances the selected amount of simulated time;
   **Advance 5 min** explicitly steps the same model. With default settings,
   sustained critical loading trips after 120 simulated seconds.
4. Inspect the trip record, zero secondary current, retained thermal state, historical
   stress and maintenance recommendations. The trip contains the triggering values,
   thresholds, pre-trip and post-trip telemetry. No hardware command is created.
5. Reduce requested loading below 100%, clear any injected disturbance, restore
   cooling/oil level if needed, and record **Fault investigation** with a note.
   Run the clock until temperature is below 95 °C and recovery conditions have held
   for 60 simulated seconds. Only then can **Reconnect simulation** close the breaker.
6. Download the report: printable HTML, complete retained telemetry CSV, JSON state
   and event history, and a SHA-256 manifest. A manifest detects alterations relative
   to itself; it is not a signature or proof of measurement truth.
7. Select **Prototype**. Disconnected hardware displays unavailable values. A physical
   demonstration requires commissioned and calibrated hardware; software tests do
   not establish that the physical rig is safe or working.

Other scenarios: normal operation, cooling failure, surge, thunderstorm, historical
degradation and fault/recovery. Fault injection additionally supports overvoltage,
undervoltage, overcurrent, short circuit, heating, low oil, gas indication, combined
stress and a synthetic temperature-sensor offset. Storm severity determines the
resulting voltage disturbance; a low-severity storm does not automatically trip.

**New run is the reset operation.** It preserves previous runs and their evidence.
Changing scenarios cannot clear an existing trip. Maintenance cannot erase ageing.

## Architecture and persistence

```text
Industrial plant model ──> normalized Telemetry ──┐
                                                ├─> shared analyse()
ESP32 -> USB bridge -> authenticated frames ─────┘       |
  |                                                     +-> condition index
  +-> optional normalized device API                    +-> temporal anomalies
                                                        +-> maintenance advice
                                                        +-> protection decision
                                                               |
                              industrial simulated breaker <───┤
                              prototype gated all-OFF request <─┘
```

Code: `neuratwin/twin_core.py` and `neuratwin/twin_api.py`. Existing auth middleware
and storage provide roles, audit records and Supabase persistence. No new database
migration is required: `twin_run` and `twin_prototype` use the existing private,
revision-controlled records table. SQLite remains an explicit local development mode.

Run commands include a unique request ID and expected revision. Identical retries
are idempotent; different payloads reusing an ID and concurrent edits are rejected.
Reads do not advance time or change simulation state. Simulation progress is driven
by authenticated step requests. Hidden tabs and disconnected clients do not silently
simulate elapsed wall time. Reloading restores the persisted state; a running run
continues ticking only while its view is visible. The screen shows 240 recent samples
and 100 recent events; the report contains the full retained run. A run is bounded at
5,000 samples/commands; export it and create another rather than silently losing data.

## Electrical and thermal model

Industrial voltages are **line-to-line RMS**; currents are line RMS. Loading is
requested current as a percentage of rated secondary current, not three independent
random electrical channels. The illustrative model uses:

```text
I_rated = S_rated / (sqrt(3) * V_secondary_rated)
I_secondary = load_pu * I_rated
V_secondary = V_secondary_rated * voltage_pu * (1 - 0.035 * load_pu)
losses = core_loss * voltage_pu² + copper_loss * load_pu²
I_primary = (sqrt(3) * V_secondary * I_secondary + losses)
            / (sqrt(3) * V_primary)
```

Unity power factor is assumed **only in this industrial simulation**. Prototype V×I
is apparent power; voltage/current RMS alone cannot establish watts, efficiency or
losses. The demonstration's 1 A hardware rating is not reused as an industrial rating.

Oil and winding rise use separate first-order states with exact exponential updates
within 5-second integration steps. The default oil and winding time constants are
120 and 7 minutes. Oil heating depends on normalized core/copper losses, ambient and
cooling effectiveness; winding rise depends on load^1.6. Cooling factors are 1.0,
0.6 and 0.3 for normal/degraded/failed states. Opening the simulated breaker removes
energization and load, while both temperatures cool gradually. No oil/winding value
is inferred from the physical surface probe.

Surges and short circuits are deterministic **supervisory RMS scenarios**, not
electromagnetic-transient, insulation-withstand or relay-coordination simulations.
Oil level/condition and gas indication are explicitly injected or accumulated model
variables. Gas indication is not measured DGA, a gas concentration or a fault diagnosis.

## Health, history and prediction

The screening index subtracts weighted stress from 100:

| Contribution | Weight |
| --- | ---: |
| Electrical deviation | 18% |
| Loading stress | 20% |
| Thermal stress | 22% |
| Environmental stress | 5% |
| Historical exposure | 25% |
| Oil-condition scenario | 10% |

Stress terms are bounded to 0–100 and shown in the interface. Weights are documented
heuristics, not learned reliability estimates. Warning/degraded/high-risk bands and
protection thresholds are configurable before the run starts. A healthy-looking
instantaneous state does not erase historical stress. Unknown/uncalibrated physical
data produces an unavailable index, not a healthy default.

Independent temporal checks detect rapid temperature rise at nearly constant load,
abrupt voltage changes, current/load inconsistency, and a synthetic temperature-channel
residual against the industrial model. They are distinct from threshold checks.

Equivalent ageing integrates a hypothetical Arrhenius factor:
`exp(15000/383.15 - 15000/(hotspot_C + 273.15))`. The reference thermal budget defaults
to 180,000 hours and is an **illustrative assumption**, not a manufacturer lifetime.
The conditional life display holds the current modelled hot-spot constant and reports
results above 50 years as outside its planning horizon. It omits moisture, oxygen,
insulation chemistry, mechanical damage and many failure mechanisms. It is neither
actual RUL nor evidence that equipment may safely operate for that duration.

Historical degradation seeds an explicitly recorded 48% thermal-budget history and
additional historical stress; it does not pretend that minutes of operation caused
years of wear. Oil service restores only the oil scenario variables; insulation
ageing and the trip/event record remain. Repeated voltage events, overload exposure,
thermal trends, low oil/gas indication and historical damage drive different advice.

The industrial forecast projects time to the configured critical hot-spot threshold
over four hours with present inputs/fault held constant and protection ignored. It
is a conditional trajectory, not a failure probability or held-out validation result.
Prototype forecasts continue to use the existing qualification workflow in Action Lab.

## Protection and recovery

Default industrial thresholds are demonstration settings:

| Quantity | Warning | Critical | Immediate trip | Recovery |
| --- | ---: | ---: | ---: | ---: |
| Loading (% rated current) | 100 | 125 | 160 | below 100 |
| Modelled hot-spot (°C) | 110 | 125 | 140 | below 95 |
| Voltage deviation (pu) | 0.10 | 0.20 | 0.30 | below 0.10 |

Sustained critical conditions trip after 120 seconds. Gas indication or oil level
below 40% also generates a simulated trip. Recovery requires an investigation after
the latest trip, no active disturbance, normal cooling, adequate oil level, and 60
seconds inside the recovery envelope. Recovery eligibility never automatically
recloses the breaker. Disabling protection in the simulator has no effect on hardware.

### Physical cutoff behaviour

Existing `HALO_ALLOW_CONTROL=0`, commissioning holds, firmware verification flags,
host timeout and K4 lock are preserved. `automatic_cutoff_enabled` is a new bench
configuration field, default **false**, editable through the existing administrator
commissioning API/UI. This change has not enabled it on the user's rig.

Authenticated telemetry is evaluated even when the dashboard is closed. A qualified
critical measurement latches a decision. A physical all-OFF request is issued only
when automatic cutoff, server control, commissioning and reported relay-output
configuration permit it. Otherwise the withheld action is logged. It never sends
automatic ON commands. The command uses the existing queue, five-second expiry,
firmware response and acknowledgment chain. Its states distinguish requested,
acknowledged, rejected and expired. Acknowledgment **never** proves contact opening
or mains isolation. These load relays do not disconnect the transformer primary.

Reset requires fresh calibrated data, current below 90% of the reviewed current
limit, surface temperature at least 5 °C below its limit, no critical condition,
reported OFF GPIO states and an investigation note. Resetting the latch sends no ON
command. Independent fusing, hardware protection and qualified electrical review
remain prerequisites. This networked software is not protective relay equipment.

## Prototype telemetry and optional primary current

The existing `/api/halo/telemetry` frame API remains supported. `current_a` means
secondary load-bank current; new `primary_current_a` is optional. Existing immutable
frame retries remain compatible when the new channel is absent.

Alternatively post canonical names to `/api/halo/device/twin-telemetry`, using the
device bearer credential. Include `source: "prototype"`, `transformer_id: "BENCH-001"`,
device ID, boot ID, sequence, uptime, timezone-aware acquisition time, calibration ID
and the measured fields. Canonical names are `primary_voltage`, `primary_current`,
`secondary_voltage`, `secondary_current`, `transformer_temperature` (surface) and
`ambient_temperature`. Ambient still needs its source and observation time. Oil,
winding and arbitrary source fields are rejected. The endpoint routes through the
same ordering, identity, freshness and immutable-frame checks as USB ingestion.

Firmware now supports a fourth optional ADC channel, `PRIMARY_CURRENT_ADC=-1` until
verified. It reports `primary_current_rms_mv` and its bias/range diagnostics. The USB
bridge applies a separately recorded `primary_current_a_per_mv` and
`primary_current_noise_mv`. Its GPIO must be unique and valid for the actual chip's
ADC1 profile. No GPIO, sensor isolation, supply budget or mains connection has been
assumed. Setting an absent channel to null is correct. Existing firmware is not
silently treated as measuring both currents.

Compile-only checks remain `scripts/check_firmware.ps1 -Target esp32` and
`-Target esp32s3`. Uploading and testing real hardware are separate qualified tasks;
no serial port was opened for this implementation.

## References and limits

The modelling and measurement boundaries are informed by primary sources; the
implementation is a simplified demonstrator, not an implementation certified to a
loading/protection standard:

- [Hitachi Energy transformer digitalization](https://www.hitachienergy.com/products-and-solutions/transformers/the-txpert-ecosystem): thermal, electrical and condition information serve different monitoring needs.
- [Hitachi transformer digital twin applications](https://www.hitachi.com/en/insights/hitachihyoron/hitachi-technology/2026/07/): thermal models and calibration are central to load-management applications.
- [Fluke Norma 5000](https://www.fluke.com/en-th/product/electrical-testing/power-quality/norma-5000): transformer efficiency requires appropriate synchronous power measurements.

Validation evidence: `reports/halo-dual-mode-tests.xml`, compile logs and browser
captures. Synthetic tests establish software behaviour only. Real primary-current
measurement, sensor calibration, cutoff contact timing, electrical safety, utility
datasets, field accuracy and actual remaining life are not established by these tests.


## Asset-scoped submission workflow

`halo-session.js` owns the visible source and selected industrial run. `halo-case.js`
uses `/api/halo/twin/runs/{id}/case`; industrial Evidence/Action Lab/Maintenance do
not read a bench snapshot. Independent studies require explicit source selection.

`twin_studies.py` freezes a hot-spot trajectory, copied settings/inputs/profile and
SHA-256 before future rows exist. Scoring rejects cross-run or altered records,
deduplicates elapsed instants, excludes unqualified channels and reports changed
inputs separately. The simulated source establishes internal consistency only.
The ±15% rise/tau sensitivity is not a confidence interval. Recorded history from
older versions without channel qualification is withheld from comparable scoring.

Planning enumerates 0–100% reduction in 10% steps and declared delays, choosing
least curtailed simulated energy among passing candidates. It rejects thermal,
post-load and protection-delay violations. Application checks origin revision,
run ownership, current qualification and zero delay; it never issues hardware
commands. Critical/fault scenarios may yield no admissible plan.

Work records retain owner, due simulated time, acceptance text and origin. State
order is open → in_progress → verification_pending → closed. Closure requires a
later simulated instant with NORMAL status, closed breaker and qualified signals;
this is verification within the simulation, not evidence of a physical repair.

Reviewed oil-reference fitting requires finite chronological CSV readings with
load excitation and oil response. The first 70% identifies oil rise/time constant;
the remainder is scored against persistence using recorded inputs. Surface files
are rejected by contract. Only an identifiable, improving fit can initialize a
new run; other model assumptions remain illustrative. Operator-provided provenance
is an assertion, not independent verification of an uploaded document.

The separately generated benchmark uses noisy, mismatched dynamics and retains
mild-fault misses and false alarms. See `scripts/benchmark_submission.py`, the
three `reports/submission-*` files and root README for protocol/results. It tests
the oil-reference/residual methods, not field accuracy or every industrial feature.

Run the primary demonstration from `/app#demo`; use the current dossier at
`/static/submission-guide.html` and current physical handoff at
`/static/hardware-guide.html`. Archived development notes are not build instructions.
