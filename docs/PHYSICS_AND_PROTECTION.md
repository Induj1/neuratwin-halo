# Physics & protection

Open `/app#control`. The merged Control centre has one source, one transformer model and one set of live graphs. **Overview** contains instruments, alarms and load controls; **Analysis** contains forecasts, fault scenarios, FEM and model assumptions. Observed voltage/current remain separate from load-bank estimates. The former `/app#operate` and `/app#physics` links both open this surface.

The same panel now includes a [maintenance decision and verification workflow](MAINTENANCE_WORKFLOW.md): uncertainty and entered-cost comparison, frozen job cards, technician evidence, post-action verification, model revisions and a transient FEM study. The steady sensor-placement study below remains available separately.

## Demonstration

1. Select Industrial simulation, create a run and increase loading to 140%.
2. Inspect the two-hour forecasts, apply the proposed reduction, then advance the source clock.
3. Switch Assembly to Thermal field. Expand Finite elements & sensor placement to compare one, two and three sensors.
4. Under Model & fault scenarios, inject a pressure surge for a sealed tank, or accumulating gas for a conservator. Advance the source clock for accumulating faults. Reset starts a new model window at the latest sample.
5. Export report retains readings, assumptions, source matrix, forecasts, events and FEM summary. Download physics data also includes the mesh and nodal temperatures.

## Thermal and fluid model

The independent oil study uses a loading-guide-style lumped model:

```
K = observed secondary current / rated current
target = ambient + rated_rise * ((1 + R*K*K) / (1 + R))**0.8 / cooling
oil_next = target + (oil_previous - target) * exp(-dt_model / tau)
dt_model = dt_source * clock_scale
```

Prototype rated current is 1 A. Initial surface temperature seeds a **virtual oil scenario**, not an oil measurement. Industrial mode seeds from its modelled top-oil. Subsequent temperatures are predictions from loading and assumptions, not continuous fitting to the probe. Supply at or below 1 V is treated as de-energized and cools toward ambient. Removing all secondary loads while energized retains assumed no-load heating.

Defaults: rated oil rise 55 C, load/no-load loss ratio 5, time constant 90 minutes. The visible 60x model clock accelerates the demonstration; 1x is selectable. These defaults have not been experimentally identified for the bench or an industrial asset. This is not a complete IEC compliance implementation.

Bulk oil is approximated as `ambient + 0.8 * (top_oil - ambient)`. With a 25 C reference:

```
expanded_litres = 0.0007 * initial_oil_litres * (bulk_C - 25)
gas_litres = initial_gas_litres - expanded_litres + leaked_litres
pressure_gauge_kPa = 101.325 * (bulk_C + 273.15) / 298.15
                    * initial_gas_litres / gas_litres - 101.325
```

Sealed mode assumes rigid walls, a fixed gas mass, common gas/bulk temperature and no relief flow. Pressure becomes unavailable below 5% of initial gas volume. It does not model a fully oil-filled flexible tank, gas dissolution, arcing, shock waves or rupture strength.

Conservator mode is vented and has no gas-cushion pressure output. Its fill starts at 40% of declared capacity, then changes with expansion and injected leakage. Sealed mode shows remaining oil inventory. Tank dimensions, fill and limits are assumptions: current and voltage alone cannot identify actual internal pressure or oil level.

## Intervention and fault scenarios

The study enumerates reductions over 120 model minutes, in 5% demand steps for industrial simulation or discrete active equal-resistance branches for the prototype. Prototype projections assume proportional current sharing at unchanged voltage. It proposes the smallest candidate satisfying declared oil/pressure margins and model-domain checks. This is a conditional study, not certified protection or a guarantee.

- Oil leak withdraws 0.001% of oil volume per model second.
- Conservator gas injection adds 0.1 mL per model second; illustrative alarm/trip levels are 100/200 mL.
- Sealed pressure surge adds an offset equal to the configured pressure limit. It is not inferred from a current step or presented as a measured Buchholz event.
- Oil, pressure and low-oil conditions produce model warnings and latched trips. Future curves exclude injected faults; shedding does not repair a leak or clear gas.

No injected event automatically commands hardware. Explicit operator actions request bench loads OFF through the existing authorized ESP32 endpoint, checking server control availability, live source and recommendation freshness. This sheds secondary loads and does not establish primary isolation. Board acknowledgement is not contact feedback. This feature adds no firmware or BOOT-button behavior.

## Finite elements and sensor placement

The field solves `-div(k grad T) = q` using P1 triangular finite elements and a Robin boundary. Its declared 0.30 x 0.40 m section, 0.20 m depth, has 648 elements and 361 nodes. Effective conductivities are core 15, winding 2, oil 0.3 W/mK; boundary convection is 8 W/m2K. Illustrative heat is 2 W core plus `10*K*K` W copper, zero when de-energized.

This is a separate steady geometry study, not a calibrated field of the bench or transient oil model. Effective conduction does not resolve oil circulation/CFD. The UI exposes heat input, rejected heat and balance residual. Tests check energy conservation, load response, de-energized behavior and mesh refinement.

Sensor selection uses 60 synthetic training loss cases and greedily chosen accessible boundary nodes. Noise-regularized linear reconstruction is evaluated on 30 held-out loss cases with assumed 0.25 C Gaussian noise. The one/two/three-sensor RMSE comparison supports cost-versus-observability discussion; it does not establish field accuracy, universal optimal locations, industrial pressure-sensor replacement or financial savings.

## Coverage and limitations

The model replays the supplied bounded source window. Duplicates add no exposure; boot changes, invalid channels and gaps above 10 seconds (prototype) or 65 seconds (industrial) exclude integration. Cached offline inputs freeze the response and disable physical commands. Reset discards earlier exposure. Trips latch only within the retained replay window, not in a persistent safety controller: refreshing or losing the triggering history can clear them.

The source matrix preserves observed current and separate estimates with provenance. Missing, invalid or stale readings never fall back to an estimate. Current disagreement holds new prototype forecasts. Historical version-1 captures retain their original display provenance. Apparent primary/secondary power differences are not treated as measured losses. Reports distinguish raw acquisition from display estimates. Input digests detect changes relative to retained records; they are not signatures.

## Research basis and next validation

- [Oil expansion and pressure in an oil-filled bushing](https://www.mdpi.com/1996-1073/14/23/7908): supports the thermal-expansion/gas-pressure mechanism, not whole-transformer validation.
- [Sealed-transformer thermal/structural modelling](https://www.witpress.com/Secure/elibrary/papers/SU12/SU12016FU1.pdf): motivates adding tank compliance beyond the current rigid approximation.
- [Transformer temperature-field reduced modelling](https://ietresearch.onlinelibrary.wiley.com/doi/full/10.1049/hve2.12446): motivates a field solver with an efficient online model; our solver does not reproduce the paper's validated results.
- [Physics-informed sensor placement](https://arxiv.org/html/2502.00552v1): motivates measurement-location design; the implementation here is greedy FEM-based selection, not the paper's PINN/MILP method.

Next validation requires measured load steps, identified thermal parameters, independent oil/hot-spot/pressure references on appropriate equipment, and uncertainty bounds. The present work demonstrates a low-instrumentation decision workflow. Improved industrial reliability and reduced deployed cost remain outcomes to validate.
