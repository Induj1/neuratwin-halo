# Measured and estimated readings

New browser captures use `prototype-display-2`. Each observed channel retains its raw value, unit, method and quality. Valid measured zero stays zero. Missing, invalid, stale and firmware-calculated values cannot fill measured channels. Calibration status remains separate from the sensor reading.

The load-bank calculation is retained as a separate estimate:

- `R_eff = 39 ohms / commanded active branches`
- `I_secondary_est = V_secondary / R_eff`
- `I_primary_est = V_secondary * I_secondary_est / V_primary`
- Measured and estimated loading each use the 1 A reference independently.

These estimates assume nominal equal resistors, commanded relay states and, for primary current, unity power factor and no losses. They do not confirm relay contact position or sensor accuracy. Estimates require live valid voltage and a positive active branch count.

Cards show measured values first and estimates separately. Current scopes and response plots use solid observed lines and dashed estimated lines. Each history sample freezes both values at that acquisition; changing loads does not rewrite history. The sine scope remains a reconstruction from RMS readings, not a captured waveform.

A secondary-current difference greater than `max(0.05 A, 20% of estimated current)` flags disagreement. This is an inspectable screening rule, not a calibrated sensor tolerance or fault diagnosis. Disagreement holds the current screening score and new physics, lifetime and maintenance forecasts instead of silently selecting one input. Uncalibrated readings also hold the current screening score. Forecasts remain conditional model outputs.

Reports retain the observed channels, raw values, separate estimates, assumptions and disagreement flag. Existing version-1 records remain readable with their original provenance; they are not retrospectively relabelled as measurements. Industrial simulations retain their simulated source.
