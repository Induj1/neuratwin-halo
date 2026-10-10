# Maintenance decisions and follow-up

Open `/app#physics` and use **Maintenance desk**, or open the desk from **Maintenance → Asset job cards**. Both use the currently selected prototype or industrial run. No new credentials or hardware are required.

## Operator workflow

1. Review the current conditional thermal action. The plot holds loading and ambient constant; the comparison spans the configured cooling and rated-rise assumptions.
2. Expand **Uncertainty & measurement cost** to inspect every scenario and optionally enter demand, tariff, intervention, inspection and sensor costs. Empty costs remain unknown.
3. Create a job card and enter the technician and acceptance window. The card freezes its source readings, model version, forecast, recommendation, assumptions and available previous maintenance. Each industrial run is a separate asset context; the physical context is `BENCH-001`.
4. Save technician findings and an optional JPEG/PNG. Apply any operating change using the existing source controls. Then **Freeze follow-up forecast**, recording what was actually done. Saving this record issues no equipment command.
5. After new readings arrive, choose **Check new readings**. The app compares them with the frozen post-action forecast. The outcome is improved, stabilized, unresolved or insufficient evidence. This is not automatic certification that an internal fault was repaired.
6. Export the job PDF for the initial assessment, source provenance, forecasts, complete supplied readings, findings, photos and audit history. The main transformer report also includes the linked maintenance records and current asset model.

For a quick software demonstration, choose Industrial simulation, create a run, record a job and action, and advance the source six minutes. Checking immediately after the action gives insufficient evidence; checking after an uninterrupted five-minute acceptance window can establish simulated stabilization. Industrial follow-up is labelled a **simulation consistency check**.

## Model and uncertainty

Physical follow-up compares **surface temperature with surface temperature**. It does not compare the DS18B20 reading with a virtual oil or winding temperature. The independent first-order surface-response profile starts with assumed parameters: 1 A rating, 45 C rated rise, 30-minute time constant, load/no-load loss ratio 5, 25 C ambient and an 80 C configured limit. These defaults are illustrative, not experimentally established ratings. The maintenance forecast uses source minutes, without the virtual oil study's accelerated clock.

Industrial follow-up uses modelled top-oil, the run's rated current/rise/time constant/loss ratio, current simulated ambient and an explicit 95 C default oil limit. Its simplified forecast is independent of the full industrial simulation; differences are reported, not hidden.

The scenario engine tests up to nine cooling/rise combinations, enumerates load reductions in 10-percentage-point steps through the configured maximum, and selects the smallest reduction meeting the temperature limit in every tested scenario. Initial exposure is included: an already-hot source cannot be called safe by ignoring time zero. These are conceptual demand reductions, not an automatic mapping to the bench's discrete relay branches. This workflow does not override existing protection or relay controls.

The plotted blue forecast is the nominal model at the reduction chosen across the scenario set. The displayed scenario range is not a statistical confidence interval. Offline sources, missing channels and loading outside the declared envelope withhold new decisions and action forecasts.

The cost calculation uses curtailed energy over the forecast horizon plus entered intervention cost. A hypothetical cooling inspection resolves the cooling parameter; a calibrated thermal measurement resolves the rated-rise factor. Each comparison retains the other uncertainty. The most favorable avoided action cost is an **optimistic benefit bound**, assuming perfect information about that parameter. It is not expected savings, a real sensor accuracy model, a probability of benefit or an industrial procurement quote. All costs must refer to the same decision period.

## Verification and evidence retention

The action record freezes a new forecast using the post-action loading, temperature, ambient basis and model version. Later readings are excluded when current changes by more than the greater of 1% of rated current or 5% of origin current, ambient changes by more than 2 C, provenance changes, energization changes or the device restarts. Missing channels, gaps over 10 seconds on the prototype or 65 seconds in simulation, or insufficient elapsed coverage prevent a positive result.

Prototype ambient remains an explicit assumption unless independently supplied; the current hardware does not verify ambient stability. A comparison using frontend-estimated current is conditional on that estimate. It does not become an independent electrical measurement. Exact existing display currents and voltages are preserved.

Verification saves the supplied follow-up window. The prototype browser supplies a rolling maximum of 300 samples; check periodically during a longer session to retain evidence before it leaves that window. A new action starts a new follow-up cycle and retains the previous cycle. A job revision guard prevents another operator's edits from being silently overwritten. Refresh assessment reloads current jobs and profile revisions. Creating a job is idempotent for an identical request ID and body.

“Improved” requires operator-reported correction, at least a 1 C decrease after the action, and comparable readings below the limit over the acceptance window. “Stabilized” means the recorded thermal acceptance condition is met. “Unresolved” means comparable observations still cross the limit. None establishes all-cause reliability or actual remaining useful life.

## Asset model revisions

Manual assumptions require a reason and create a new revision. Existing job forecasts retain their original parameters. Notes and photos never alter the model automatically.

**Check calibration evidence** requires fresh physical data, calibrated independent current and measured surface temperature, one uninterrupted boot, at least 120 samples over 20 minutes, a training load span of at least 0.2 pu and a temperature span of 2 C. Frontend current estimates and industrial simulation cannot establish this calibration.

The fit estimates rated rise and time constant on the first 70% of the data, then evaluates the remaining 30%. It rejects poorly identified fits, parameters on bounds, held-out RMSE above 2 C, or less than 20% improvement over a persistence baseline. Accepted proposals still require an explicit **Accept proposed fit** action, bound to the unchanged asset model revision. Recorded job evidence extends the short browser window. Passing this check validates only that acquisition interval, not a fleet or unseen operating conditions.

## Transient finite elements

Expand **Transient thermal field**. Set load before 20 minutes, from 20 minutes, and from 60 minutes; solve a 120-minute profile. The model assembles P1 triangular conduction elements, a lumped heat-capacity matrix and Robin heat-transfer boundaries, then integrates with backward Euler at 30-second steps. It reuses sparse factorizations.

The 0.30 × 0.40 m cross-section and 0.20 m depth have 648 elements. Conductivity / density / heat capacity are core 15 W/mK / 7800 kg/m³ / 460 J/kgK, effective winding 2 / 8960 / 385, and effective oil 0.3 / 870 / 1900. Boundary convection is 8 W/m²K. Declared heating is 2 W core plus `10 K²` W copper when energized. These are illustrative properties and losses; they are not inferred from dependent displayed primary/secondary power differences.

The 3D view extrudes the **solved nodal temperature field** uniformly through depth. It is not a 3D FEM solution or CFD. Playback interpolates the two-minute output frames; the input heat follows the entered step schedule. The downloaded study contains the mesh, material assignments, settings, all output nodal fields and solver residuals.

**Run numerical checks** compares 648 with 2,592 elements, 30 with 15-second steps, and input heat against stored plus rejected heat. For the default reference case, this implementation produced maximum peak differences of approximately 0.0192 C for mesh refinement and 0.00160 C for time refinement; energy residual was below `1e-8 W`. The tests also check a de-energized cooling case and constant ambient equilibrium. These are numerical consistency checks, not physical validation or a general convergence proof.

The UI reports actual warm-solve latency on the current computer. A learned surrogate was not added: direct cached sparse solves already support interactive playback, without introducing surrogate approximation error or claiming unmeasured acceleration.
