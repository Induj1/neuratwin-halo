# Control panel alarms

Open **Physics & protection**. Alarms follow the selected working source.

- Sound is enabled by default. The first click, tap or keypress anywhere in the app unlocks browser audio, with no separate sound button or confirmation tone. Warnings use a triple chirp; unacknowledged critical alarms use a sharp alternating high/low siren, repeating every two seconds while this panel is visible.
- **Acknowledge** silences current alarms and stops the pulsing beacon. The warning stays visible. Escalation or a different fault triggers a new alarm.
- Browsers may block sound until the first interaction after reloading. Visual alerts work immediately. Use **Acknowledge** to silence current alarms.
- Amber means warning; red means critical. Recovery appears after readings cross the recovery margin. Temperature and pressure use a 2-unit margin, oil level uses 2 percentage points, and gas accumulation uses 2 mL.

Physical temperature alerts use the live surface probe and the prototype's configured temperature limits. Oil, pressure, level and gas alerts use the virtual model and are labelled accordingly. A simulated pressure event never changes the measured surface reading or makes the physical transformer glow as if overheated.

A missing connection, invalid surface reading or unavailable model is reported explicitly. Cached readings cannot establish recovery. A model trip remains latched until its scenario is reset; acknowledging does not reset it.

For an isolated demonstration, select **Industrial simulation**. Open **Model & fault scenarios**, choose **Pressure surge** for a sealed tank, then acknowledge the alarm. Use **Reset scenario** to clear the injected scenario; remaining abnormal conditions can keep the alarm active. Gas accumulation requires the conservator setting.

**Oil leak** and **Gas accumulation** give an immediate amber scenario warning after the model confirms the injection. Selecting a fault automatically starts a paused industrial simulation, so oil inventory and accumulated gas progress without manual stepping. Low oil or accumulated gas crossing the critical threshold triggers the emergency siren. The initial warning identifies the injected scenario; it does not claim a measured leak or gas detection. At the default 60× clock, one source minute represents 60 model minutes. Physical mode advances only with fresh source samples; starting a scenario does not alter physical readings or switch relays.

This is browser annunciation while the control panel is open, not an unattended or certified protection system. These alerts do not operate relays. Existing load-control buttons still require a separate operator action. Voltage and current display calculations are unchanged.

The siren is generated locally with Web Audio (960/1440 Hz alternating square-wave tones, filtered harmonics and short gain ramps). It needs no MP3 download or network connection. System volume controls the final speaker level.
