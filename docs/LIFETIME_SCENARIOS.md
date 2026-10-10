# Life and risk scenarios

Digital twin includes a **Life & risk** panel in Prototype and Industrial modes. It reads the selected source and exposes four outputs, two projection charts and expandable assumptions. It never changes source readings, operating inputs or relay commands.

| Output | Meaning |
| --- | --- |
| Condition score | Inspectable screening heuristic: 35% loading stress, 45% temperature stress, 20% voltage deviation. Recent peaks remain visible to the calculation. |
| Time to temperature limit | Conditional first-order temperature projection over four hours. Reports reached, crossing, no crossing or beyond horizon. |
| Modelled remaining life | Conditional median under the assumed thermal-ageing and Weibull survival model. Values beyond 50 years are shown as `>50 yr`. |
| Simulated failure risk | Conditional thermal-ageing probability over the selected horizon. This is not a calibrated all-cause transformer failure probability. |

## Inputs and coverage

Prototype uses **observed secondary current and voltage** and the surface-temperature channel. Separate frontend current estimates never fill missing or zero observations. A current disagreement holds new projections. The reference current remains 1 A. Raw acquisitions, frontend estimates and calculated primary current remain distinct in reports. An assumed surface-to-ageing-temperature offset is not a measured winding hot-spot.

Industrial mode uses retained simulated secondary readings and modelled hot-spot temperature. Its default current rating comes from the run's kVA and secondary voltage. This scenario is separate from the existing qualified industrial forecast and its evidence checks.

The latest five minutes supply time-weighted voltage/temperature means and root-mean-square current for future heating. Peaks and overload duration are recorded separately. A single observation is instantaneous, not an established long-term average. Missing latest channels withhold the projections. Cached readings are explicitly dated and cannot supply current inputs. Historical version-1 captures retain their original display provenance.

Observed equivalent ageing integrates only supplied temperature intervals, deduplicated by sample identity. Gaps beyond the configured cadence allowance and board restarts are excluded. Prototype history is bounded to the browser's 300-sample buffer and clears on reboot; there is **no durable lifetime exposure ledger**. Refreshing or exporting never accumulates age again. Unknown history is represented by the editable assumed equivalent age, not invented measurements.

## Calculation and assumptions

Future current is held at the recent RMS average. Temperature approaches `ambient + rated_rise * (current / rated_current)^2` with an assumed first-order time constant. The projection assumes no protective interruption. Electrical faults above 3 pu current and temperatures outside the model domain withhold lifetime/risk outputs.

Equivalent-age rate is `2^((temperature + offset - reference_temperature) / doubling_temperature)`, bounded by the disclosed floor and cap. This is an illustrative sensitivity model, not a qualified insulation chemistry or standards-based transformer life model. Prototype defaults are a 20 °C offset, 60 °C ageing reference, 10 °C doubling interval, 15-minute time constant and 55 °C surface limit. Industrial defaults use modelled hot-spot temperature with zero offset, a 98 °C reference and the run's thermal settings. These are editable scenario assumptions, not calibrated device properties.

Let `A` be assumed prior equivalent age plus covered observed exposure, `E(t)` projected equivalent exposure, `eta` the characteristic life scale and `beta` the shape. Conditional survival gives:

`P(failure by t | survival to A) = 1 - exp(-[((A + E(t))/eta)^beta - (A/eta)^beta])`.

Remaining life solves this probability at 0.5. The default 20-year scale and shape 3 are illustrative, not learned from failure data; the scale is not the mean lifespan. The survival-function form follows the [NIST Weibull distribution reference](https://www.itl.nist.gov/div898/handbook/eda/section3/eda3668.htm). That reference supplies the mathematics, not validation of these transformer assumptions.

## Usage and export

Open **Model assumptions**, change age, life scale, risk horizon or thermal assumptions, then select **Update model**. **Reset assumptions** restores source-specific defaults. Assumptions persist in this browser per asset/run. These controls affect only the scenario panel.

**Export PDF** includes all four outputs, assumptions, input digest, coverage, component weights and sampled projection curves in the frozen assessment. The current assessment remains separate from any selected readings interval. The preview and export share the same calculation and input adapters.

## Verification

Tests cover analytic temperature crossings and Weibull probabilities, hotter/heavier scenarios, monotonic risk, age sensitivity, missing channels, duplicate samples, gaps, fault-domain holds, displayed-current provenance, revision consistency and matching PDF/preview results. Browser checks cover offline Prototype, Industrial assumptions, unchanged underlying readings, export, source changes and responsive layout.
