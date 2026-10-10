# Briefing features — 10 October 2026

The Digital twin now includes industrial electrical and pressure studies, a blind electrical challenge, paired thermal forecasts, and direct PDF reports for both sources.

The [Life & risk scenario panel](LIFETIME_SCENARIOS.md) adds condition screening, conditional time to a limit, modelled remaining life and simulated thermal-ageing risk with editable assumptions and PDF inclusion. Existing voltage/current acquisition and frontend fallback calculations remain unchanged.

## Using the new features

1. Select **Industrial simulation** and create a run. **Scenarios, disturbances & model settings** contains rated capacity, percentage impedance, source/cable impedance on the same transformer base, X/R ratios and pressure thresholds. Settings are editable before the run starts. Asset passport records impedance provenance separately from thermal provenance.
2. **Electrical & thermal studies** shows prospective symmetrical RMS fault current. The short-circuit scenario uses this impedance model. A balanced bolted fault overrides load imbalance; reducing ordinary load does not remove fault current.
3. Use **Compare cold / hot** on an energised run without an injected disturbance. The two forecasts share demand, ambient, cooling and parameters; only initial thermal state differs. Neither forecast changes the selected run.
4. Use **Blind fault challenge → Electrical waveforms → New blind event → Freeze diagnosis → Reveal event**. The assessor sees sampled-current/voltage features and acquisition context. The hidden event label and seed are excluded until reveal. Repeated assessment returns the frozen result.
5. **Review electrical readings** reviews the selected run's recorded RMS observations. It withholds inrush/internal/external discrimination when independent, aligned and compensated waveforms are absent. The separate blind experiment supplies synthetic waveform evidence; it is not a diagnosis of the selected physical transformer.
6. Inject **pressure**, or select **Tank pressure rise**, then advance the simulation. Pressure level, rise rate, alerts, simulated trip events, replay and maintenance findings remain in the same run. **pressure sensor** demonstrates an unavailable pressure channel. **Open maintenance** uses the existing investigation, verification and closure workflow.
7. **Export PDF** downloads a report for the selected source. Leave dates empty for all retained records, or select a reporting interval. Export remains available for retained Prototype records while the board is offline.

## Prototype readings

The existing voltage/current acquisition, frontend fallback values and waveform calculations are preserved. Loading still uses the displayed secondary current against the team's 1 A reference; Demo health remains a current-only score.

Reports distinguish measured channels, firmware-calculated primary current, frontend estimates and unavailable channels. The firmware power-balance calculation assumes efficiency 0.80. The separate frontend fallback uses secondary voltage divided by effective resistance, then an ideal unity-power-factor primary estimate. Missing current and a reported near-zero current have distinct descriptions, without changing the existing fallback eligibility.

The implemented Wi-Fi load mapping is M1 → load1, M2 → load2, M3 → load4; M4 requests all three OFF and is not a fourth active branch. Relay commands do not prove contact position. The temperature probe measures surface temperature. This bench does not supply oil, hot-spot, pressure or three-phase measurements.

## Report coverage

PDFs contain source/configuration details, current assessment, charts, complete retained interval readings, events and linked studies/work orders. Prototype acquisition tables include raw reported electrical readings, surface and ambient values where available, relay states, configuration/calibration references and raw channels. Browser estimates and Demo health appear separately with their calculation basis.

An export freezes its data before rendering and retains its source snapshot with a SHA-256 digest. Industrial revision checks prevent exporting a different run revision silently. Prototype acquisition/event retrieval pages past the dashboard's default limits. Missing values remain unavailable.

The browser display buffer is limited to 300 newly received samples and clears on board reboot. Earlier displayed estimates cannot be reconstructed as if they had been retained. The report states that limit and preserves raw acquisitions separately. Selected-interval readings are distinct from the current assessment and linked study context.

## Evaluation and limits

- Electrical observer: 140 controlled synthetic events across seven classes; 100% exact fixture-class match, 85.7% non-abstained coverage, 0 false alarms in 20 normal events. The current-threshold baseline matches 28.6%. Per-class metrics, confusion matrix and detection delays are retained in `reports/electrical-observer-evaluation.json`. These results exercise a shared synthetic fixture and deterministic rules; they do not establish field accuracy or robustness to arbitrary CT saturation, low-harmonic inrush or overlapping faults.
- The current thermal source has a new frozen evaluation in `reports/pipeline-v8-fresh-protocol-run`: four previously unused paired seeds, 80 generated cases, source hashes and complete scoring records. This smaller check is distinct from the historical v6 evaluation. The v7 protocol was consumed and interrupted during code review before examining scored output; its interruption record is retained.
- ETTh1 forecasting was rerun because the PDF dependency changed the dependency fingerprint. Data, split, features, candidate settings and selection policy were unchanged. This is revalidation on the same known public split, not fresh independent evidence. Validation still selected gradient boosting; its test MAE remains approximately 0.4261 at one hour and 1.0788 at six hours, in source units. Losses against persistence remain visible.
- Industrial pressure is an explicitly scripted gas-space scenario in kPa gauge, with declared cadence, filtering, hysteresis and thresholds. It is separate from the gas scenario. It does not establish a tank rupture threshold or implement physical pressure relief.
- Fault current is symmetrical RMS on a common three-phase transformer base. Peak making current, DC offset, withstand capacity and field protection coordination are not established by this model.

No physical control commands, firmware changes or current/voltage recalibration are part of these additions.

## Verification

460 Python tests and 46 focused JavaScript tests pass. A comparison against the original ESP32 module preserves voltage/current scope values, history and quality across 32 measured, missing, near-zero, load and stale cases. Browser checks cover offline Prototype export, Industrial studies/export, blind freeze/reveal, pressure-to-maintenance navigation, lifetime assumptions and mobile width without JavaScript errors. Lifetime checks also verify displayed-current provenance, unchanged underlying readings and duplicate-safe ageing while offline. PDF tests include 625 retained acquisitions and 125 events, exceeding the dashboard query limits; exported pages were also rendered for visual review.
