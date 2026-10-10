# Frontend structural plan: hardware-routed instruments for Halo

Status: written 10 October 2026 against branch `feat/frontend-fixes-esp32-integration` (HEAD `e05fa51`).
**Implemented the same day (prototype side only):** Workstreams A, B (prototype configuration), C and D, in `web/halo-esp32.js`, `web/halo-scope.js`, `web/halo-thermo.js`, `web/halo-loads.js` with tests `tests/test_esp32_ui.mjs`, `tests/test_loads.mjs`, `tests/test_scope.mjs`. The industrial side (Workstream E) is untouched. The M1–M4 remap is frontend-only; backend and firmware are unchanged by design, and §8 stays informational.

This document turns the stated objectives into an ordered implementation plan for the `/app#operate` workspace. It describes **what** must change, **where** it lives in the existing frontend, and **which backend facts constrain it**. It does not prescribe visual design beyond the consistency rules the current code already follows.

---

## 0. Objectives (as given) and how they map

| # | Objective | Where it lands |
|---|---|---|
| O1 | Route the frontend to the ESP32 backend endpoints that already exist | New frontend data layer `web/halo-esp32.js`, consumed by the Physical prototype mode of the operate view |
| O2 | Oscilloscope-style graphs for primary and secondary voltage and current from the hardware | New shared instrument `web/halo-scope.js` (+ css), prototype configuration |
| O3 | Load controls shown as four loads M1–M4 with M1→load1, M2→load2, M3→load4, M4→isolated | New load panel replacing `#op-relays` in prototype mode |
| O4 | Toggling M4 cuts the supply with an "exceeded load" message | Frontend overload-cutoff state machine that issues an all-off request |
| O5 | Temperature instrument in °C from the hardware API | New shared instrument `web/halo-thermo.js` (+ css), prototype configuration |
| O6 | Same instrument style on the industrial side, three-phase, readings and controls to match | Industrial configuration of the scope, thermometer and a per-phase control block |

---

## 1. What exists today (facts the plan depends on)

### 1.1 Backend endpoints already available

Wi-Fi board proxy, `neuratwin/halo_esp32.py`, prefix `/api/halo/esp32`:

| Route | Auth | Returns / accepts |
|---|---|---|
| `GET /status` | none | `configured`, `url`, `poll_seconds`, `control_enabled` (HALO_ALLOW_CONTROL=1), `token_configured`, `poller{status, reachable, last_seen_at, last_error, forwarded, ...}` |
| `GET /healthz` | none | Board liveness: `wifi{connected, ip, rssi_dbm}`, `sensors{mains_present, temperature_probe_ok, current_calibrated}`, `uptime_ms` |
| `GET /readings` | none | `{live, stale, reading, readings_at?, error?}`. `reading` is the raw board JSON (fields in 1.2). When the board is unreachable and the poller has a cached reply, `stale: true` |
| `GET /loads` | none | `{ok, loads{load1, load2, load4, loads_on, relay_states[4]}}` |
| `POST /loads` | operator + HALO_ALLOW_CONTROL=1 | `{"load":1\|2\|4,"state":bool}` or any subset of `{"load1","load2","load4"}`. 423 when control is locked. Records `esp32_load_set` event |
| `GET /calibration` | none | Board factors and status |
| `POST /calibration` | operator | `{action, value?}` — long-running, 422 with board log on failure |
| `POST /poll` | operator | Force one poll, returns poller state |

Also: `GET /api/halo/status` now includes `esp32_configured` (`halo_api.py:79`).

Existing prototype analysis view, `GET /api/halo/twin/prototype` (`twin_api.py:162`): derived from the frames the poller forwards. Supplies `analysis`, `holds`, `evidence`, `settings{temperature_warning, temperature_critical, ...}`, `relay_states`, `load_control_available`, `control_enabled`, `latched`, `history[240]`. The operate view renders prototype mode from this today (`halo-operate.js:145`, `render()`).

Existing relay path `POST /api/halo/relays` (`halo_api.py:472`) is the **older USB-bridge command queue**. It rejects K4 with 403 and has many commissioning gates. The new UI must not use it for the Wi-Fi board; it uses `/esp32/loads`.

### 1.2 Board reading shape (`firmware/esp32_integration/esp32_integration.ino`, `fillReadings`)

| Field | Meaning | Unit |
|---|---|---|
| `primary_v` | Mains-side RMS voltage | V |
| `primary_current_a` | Mains-side current; `primary_current_method` is `"calculated"` unless the firmware is built with measured mains current | A |
| `secondary_v` | Load-side RMS voltage | V |
| `current_a` | Secondary RMS current | A |
| `expected_current_a` | `secondary_v × loads_on / 39 Ω` | A |
| `surface_c` | DS18B20 surface probe, `null` when `temperature_probe_ok` is false | °C |
| `mains_present`, `temperature_probe_ok`, `current_calibrated`, `calibration_status` | Validity flags | |
| `loads{load1, load2, load4, loads_on}` | Relay drive states | |
| `relay_states` | `[load1, load2, false, load4]` | |
| `quality_flags` | `mains_absent`, `surface_invalid`, `current_uncalibrated`, `sampling_short` | |
| `sequence`, `boot_id`, `uptime_ms`, `device_id` | Identity for change detection | |

The board publishes **RMS summaries at roughly 2 s**, never sampled waveforms. Every "oscilloscope" view is therefore a reconstruction or a trend and must say so, as `halo-waveform.js` already does.

### 1.3 Industrial run telemetry (`neuratwin/twin_core.py`)

Available per step: `primary_voltage`, `secondary_voltage` (line-to-line, nominal 433 V), `primary_current`, `secondary_current`, `phase_current_a/b/c`, `neutral_current`, `phase_imbalance_percent`, `max_phase_loading_percent`, `loading_percent`, `oil_temperature`, `hotspot_temperature`, `voltage_pu`, `breaker` (`CLOSED`/`OPEN`). Inputs: `load_percent`, `phase_imbalance_percent`, `cooling`, `protection_enabled`, `speed`.

**Not available:** `phase_voltage_a/b/c`. `halo-waveform.js:35` already looks for them and shows "Phase voltage RMS unavailable". See 8.1.

### 1.4 Frontend pieces to build on

| File | Role today | Reuse |
|---|---|---|
| `web/halo-operate.html` | Operate view markup, injected into `halo.html` via `<!-- HALO_OPERATE -->` (`app.py:259`) | Add new mount points here |
| `web/halo-operate.js` | Mode switching (industrial / prototype), polling (`schedule()`, 2.5 s prototype / 1.5 s industrial), `render()`, relay buttons, guarded actions | Extend; prototype branch of `render()` is the integration point |
| `web/halo-command.js` | `paint()` feeds the waveform packet, dial, contributions; `math.temperatureReading()` picks the thermal reading and level | Feed the new instruments from the same packet |
| `web/halo-waveform.js` | `HaloWaveform.create(host)` + pure `math` (`instant`, `neutralPhasor`, `buildChannels`, `axisScale`) tested in `tests/test_waveform.mjs` | The scope reuses `math` unchanged |
| `web/halo-session.js` | Single visible source selector (`industrial` / `prototype` / `reference`) | No change; new panels obey it |
| `web/halo.js` | `HaloWorkspace.api(path, body?)` (prefixes `/api/halo`, carries auth), `toast`, `view` | Use for every request |
| `web/halo-command.css`, `halo-operate.css`, `halo-waveform.css`, `halo-glass.css` | Light glass surfaces, `#view-operate .op-reading` level colours (`[data-level=WARNING]` amber, `CRITICAL` red, `UNKNOWN` grey), 44 px min targets, `focus-visible` outlines | New instruments must use the same tokens |

---

## 2. Target structure

```
web/
  halo-esp32.js        NEW  ESP32 data layer: status/readings/loads client, rolling buffer, freshness
  halo-scope.js        NEW  Oscilloscope instrument (shared): waveform mode + trend mode, N channels
  halo-scope.css       NEW
  halo-thermo.js       NEW  Thermometer instrument (shared): value, thresholds, validity
  halo-thermo.css      NEW
  halo-loads.js        NEW  Load panel M1–M4 + overload-cutoff state machine (prototype)
  halo-loads.css       NEW
  halo-operate.html    EDIT mount points: #op-scope, #op-thermo, #op-loads, #op-phase-controls
  halo-operate.js      EDIT prototype render uses halo-esp32 packet; industrial render feeds 3-phase config
  halo-command.js      EDIT paint() also updates scope + thermo; temperatureReading() unchanged
  halo.html            EDIT script/link tags for the new files (cache-bust `?v=`)
tests/
  test_scope.mjs       NEW  pure math: buffer, autoscale, phase construction
  test_loads.mjs       NEW  mapping M↔load, cutoff state machine, gating
  test_esp32_ui.mjs    NEW  packet normalisation from /esp32/readings (live, stale, flags)
```

Rules that apply to every new file:

- IIFE module exposing one global (`HaloScope`, `HaloThermo`, `HaloLoads`, `HaloEsp32`) plus a `math` object, exactly like `halo-waveform.js`, so `node --test` can `require()` the pure parts.
- Instruments are created once per host element with `create(host)` and updated with `update(packet)`. They never fetch. Fetching stays in `halo-esp32.js` and `halo-operate.js`.
- Every instrument prints its source label and quality (`live`, `stale`, `simulated`, `replay`) in the same place the waveform prints `.hw-origin`.

---

## 3. Workstream A — Route the frontend to the ESP32 endpoints (O1)

### 3.1 `halo-esp32.js`

Responsibilities:

1. `status()` → `GET /esp32/status`. Determines whether the Wi-Fi board integration is on (`configured`), reachable (`poller.reachable`), and whether control is allowed (`control_enabled`). Called on entering prototype mode and every 10 s thereafter.
2. `readings()` → `GET /esp32/readings`. Called on the existing prototype poll cadence (`schedule()` in `halo-operate.js`, 2.5 s). Normalises to a **hardware packet**:

   ```
   {
     live: bool, stale: bool, at: ISO, age_s: number,
     sequence, boot_id, device_id,
     primary:   { v, i, i_method: 'measured'|'calculated' },
     secondary: { v, i, i_expected },
     surface_c: number|null, probe_ok: bool,
     loads: { load1, load2, load4, loads_on },
     flags: string[], mains_present: bool, current_calibrated: bool
   }
   ```

   The packet keeps `primary.i_method` so the scope can label a calculated primary current as derived, matching `to_frame()` in `halo_esp32.py:136` which never presents it as a measurement.
3. `setLoads(body)` → `POST /esp32/loads`. Translates 423 into a user-facing "control locked" state rather than a generic error; translates 503 into "board unreachable".
4. Rolling buffer: keeps the last **N = 300** packets (≈10 min at 2 s) keyed by `(boot_id, sequence)` so duplicate polls don't add points. Exposed as `history()` for the scope's trend mode. Cleared on `boot_id` change.
5. Freshness: `age_s` from `readings_at` (stale) or receipt time (live). Anything over 3 × `poll_seconds` is shown as stale even if the last HTTP call succeeded.

### 3.2 Relationship to `/twin/prototype`

Keep both. `/twin/prototype` remains the source of **analysis** (status, alerts, holds, settings thresholds, `latched`, `load_control_available`, evidence, events). `/esp32/readings` becomes the source of **instrument values** at board cadence. `halo-operate.js` prototype render issues both requests in the same `guarded()` tick and passes both into `render()`. The instruments prefer the hardware packet for numbers; the readings strip `#op-readings` continues to use `/twin/prototype` telemetry so the existing evidence semantics (`qualified` / `unverified`) stay intact.

Degradation ladder shown in the prototype header (`#op-prototype-note`):

| Condition | Display |
|---|---|
| `status.configured` false | "Wi-Fi board integration is off (HALO_ESP32_URL unset)". Instruments show empty graticule, loads disabled |
| configured, poller unreachable, no cache | "Board unreachable since …". Instruments empty |
| configured, `stale: true` | Instruments render the cached values with a STALE badge and age; load toggles disabled |
| live | Normal |

---

## 4. Workstream B — Oscilloscope instrument (O2)

### 4.1 `HaloScope.create(host, config)`

Config (per mode):

```
{
  title, eyebrow,
  channels: [{ id, label, unit:'V'|'A', color, group:'voltage'|'current', phase:rad, dashed? }],
  modes: ['waveform','trend'],
  frequency: 50,
  windowMs: 40,              // waveform mode: two cycles
  trendSeconds: 300,         // trend mode: rolling window
  referenceRms?: number      // for nameplate scale (industrial current), as axisScale() does today
}
```

`update({ values: {channelId: rms|null}, history: [{at, values}], quality, sourceLabel, replay })`.

Two modes behind one toggle, same graticule:

| Mode | What is drawn | Honest label |
|---|---|---|
| Waveform | `√2·RMS·sin(2π·50·t + φ)` over 40 ms, reusing `HaloWaveform.math.instant` | "Illustrative RMS reconstruction · 50 Hz assumed · not sampled waveforms" (same sentence the waveform uses) |
| Trend | RMS value vs time over the last `trendSeconds`, one line per channel, gaps where `null` | "RMS summaries at board cadence" / "simulation clock" |

Instrument look, inside the existing glass panel: dark inset plot (like `#op-twin` canvas sits inside `.op-model`), 10 × 8 graticule, per-channel V/div or A/div readout, time/div readout, channel pills with checkboxes (reuse `.hw-channel` styling), pause/inspect cursor (reuse the waveform's slider and pointer logic). Voltage and current are shown as **two stacked plots** sharing the time axis so primary/secondary V and I are visible together, instead of the current single group toggle.

### 4.2 Prototype configuration (single phase)

| Channel | Source field | Note |
|---|---|---|
| Primary V | `primary.v` | |
| Secondary V | `secondary.v` | |
| Primary I | `primary.i` | Dashed, labelled "calculated from secondary power" when `i_method !== 'measured'` |
| Secondary I | `secondary.i` | Solid. Expected current `secondary.i_expected` drawn as a thin reference line in trend mode |

All phases 0 (the bench measures no phase relation; the waveform's existing note "arbitrary phase reference; do not infer phase shift" is kept).

Autoscale: use `HaloWaveform.math.axisLimit` per plot. Trend mode scales to the buffer's min/max with 15 % padding, the same rule as `trend()` in `halo-operate.js:244`.

### 4.3 Placement

Replace the single `#op-waveform` slot in the `.op-visual-stack` with `#op-scope` for both modes. `halo-command.js` `paint()` stops creating `HaloWaveform` directly and instead calls `HaloScope.update()`; the waveform file remains as the math library and its tests stay green.

---

## 5. Workstream C — Load controls M1–M4 (O3, O4)

### 5.1 Mapping (the single source of truth, in `HaloLoads.math.MAP`)

| UI load | Hardware | Request body | `relay_states` index reported by board | Shown as |
|---|---|---|---|---|
| M1 | `load1` | `{"load":1,"state":…}` | 0 | 39 Ω / 10 W branch |
| M2 | `load2` | `{"load":2,"state":…}` | 1 | 39 Ω / 10 W branch |
| M3 | `load4` | `{"load":4,"state":…}` | 3 | 39 Ω / 10 W branch |
| M4 | none (physically isolated) | never sent | 2 (always `false`) | "Isolated branch · overload demonstration" |

The UI never sends `load3`; the firmware rejects it anyway (`esp32_integration.ino:1259`).

### 5.2 Panel behaviour (`halo-loads.js`, mounted at `#op-loads`, replaces `#op-relays`)

- Four toggle cards, each with: label, branch description, reported drive state ("Board reports ON/OFF", from `loads` in the hardware packet — not contact feedback), and the switch.
- `loads_on` and `secondary.i_expected` shown in a footer: "3 branches on · expected 0.92 A".
- Gating, in order: not `status.configured` → disabled; `stale` → disabled; `!status.control_enabled` → switches disabled with the 423 message ("Physical load switching is locked. Set HALO_ALLOW_CONTROL=1"); `latched` from `/twin/prototype` → disabled with "Trip decision latched"; `busy` → disabled.
- Optimistic UI is **not** used. The switch moves only after the `POST /esp32/loads` reply, which carries the board's new `loads`.
- "All loads OFF" button stays (`#op-off` today), rerouted to `POST /esp32/loads {load1:false,load2:false,load4:false}`.

### 5.3 M4 overload cutoff state machine (O4)

States: `normal` → `cutoff` → `normal` (after explicit restore).

```
normal:
  user toggles M4 ON
    → immediately POST /esp32/loads {load1:false, load2:false, load4:false}
    → enter cutoff (regardless of whether the POST succeeds; see below)

cutoff:
  banner (role="alert", level CRITICAL): "Load exceeded. Supply cut off to protect the transformer."
  detail: "Switching the fourth branch would exceed the demonstrator's rated load.
           All relay drives were requested OFF. Board acknowledgement is a drive state, not contact feedback."
  M1–M3 switches disabled; M4 shown ON-but-isolated with a lock glyph.
  secondary metrics continue to update from the board (they should fall to ~0 A if the relays opened).
  "Restore supply" button → M4 OFF in UI state, back to normal; loads stay OFF until the operator switches them on individually.

  If the all-off POST failed (423/503): banner adds "Cutoff request not delivered: <reason>",
  keeps cutoff state, and disables Restore until a successful all-off or a live reading with loads_on == 0.
```

Persistence: cutoff state is kept in `sessionStorage` under `halo-esp32-cutoff` so a page reload does not silently drop the banner. It is cleared on `boot_id` change (board rebooted) or Restore.

Evidence: the all-off request already records an `esp32_load_set` event with `actor` and `request`; the UI adds no fabricated event. The banner wording must not claim measured isolation.

### 5.4 Interaction with the older `/relays` path and the K4 rule

`halo_engine.py:158` raises a **critical `k4` alert** whenever `relay_states[3]` is true, and `prototype_view` escalates that to `TRIP` when quality is `qualified`. With the firmware packing `load4` into index 3, switching **UI M3 on** will trip the prototype analysis. This is a cross-stack conflict, not a frontend bug. See 8.2 for the decision needed before Workstream C ships.

---

## 6. Workstream D — Temperature instrument (O5)

### 6.1 `HaloThermo.create(host)` / `update(packet)`

```
{ value_c, valid: bool, reason?, label, kind: 'surface'|'oil'|'hotspot',
  warning_c?, critical_c?, trend: [{at, value_c}], sourceLabel, quality }
```

Rendering: vertical thermometer (SVG) with the bulb, fill height proportional to value between a fixed floor and ceiling (prototype 0–100 °C; industrial 0–160 °C), warning and critical tick marks taken from the thresholds, big numeric readout in °C using the same `.op-reading strong` sizing, a 10-minute sparkline from `trend`, and the level colour mapped exactly as `#op-readings [data-level=…]`.

### 6.2 Prototype configuration

- `value_c` = hardware packet `surface_c`; `valid` = `probe_ok && !flags.includes('surface_invalid')`.
- Thresholds from `/twin/prototype` `settings.temperature_warning` / `temperature_critical` (surface limit − 5 and surface limit). When those are `null` (no commissioned limit), draw no ticks and state "Critical reference unavailable" as `#op-readings` does today.
- Label is always **"Surface temperature · DS18B20"**. Never "oil" or "winding"; `README.md` and `halo-command.js` are explicit about this.
- Invalid probe: empty tube, "Probe disconnected (−127 / 85 °C sentinel)".

### 6.3 Placement

`#op-thermo` sits beside the model in `.op-visual-stack`, replacing the thermal tile's role in the readings strip for the prototype; the strip keeps its four tiles for continuity.

---

## 7. Workstream E — Industrial three-phase instruments (O6)

### 7.1 Scope, three-phase configuration

| Plot | Channels | Source | Phase |
|---|---|---|---|
| Voltage | A, B, C | `phase_voltage_a/b/c` **(backend must add, see 8.1)**; until then the plot shows "Phase voltage RMS unavailable" exactly as the waveform does | 0, −120°, +120° |
| Current | A, B, C, Neutral | `phase_current_a/b/c`, `neutral_current` via `HaloWaveform.math.neutralPhasor` consistency check (`halo-waveform.js:30`) | 0, −120°, +120°, computed |

Scale: current uses the nameplate rule already in `axisScale()` (160 % of rated phase RMS from `rated_kva` and `secondary_v`), voltage autoscale. Trend mode uses the run's `history` (simulation clock), not a browser buffer, so replay works unchanged.

Labels: "Simulated · 120° separation and unity power factor assumed · no harmonics" (existing note).

### 7.2 Three-phase readings block

Extend `#op-phase-readout` into a small table rendered by the same panel: per phase V (when available), I, loading %, plus neutral I and imbalance %. Breaker state and `voltage_pu` deviation shown in the header. Values come from the run `telemetry`; nothing is derived in the frontend beyond what `neutralPhasor` already does.

### 7.3 Three-phase controls (`#op-phase-controls`, industrial only)

The simulator accepts `load_percent` and `phase_imbalance_percent` (`[1+u, 1, 1−u]` allocation, `twin_core.py:184`). The control block therefore exposes:

- Mean load slider (existing `#op-live-load`) and imbalance slider (existing `#op-live-imbalance`) presented as **per-phase bars** A/B/C that move together; the bars are a visualisation of the two inputs, not three independent inputs. State that explicitly in the helper text.
- Breaker: Trip / Reconnect (existing `#op-trip`, `#op-reconnect`), shown as a three-pole breaker glyph that follows `breaker`.
- Scenario and fault injection remain in the `.op-advanced` disclosure.

Independent per-phase load inputs are **not** promised by this plan; they need a simulator change (8.3).

### 7.4 Industrial thermometer

Two tubes from the same `HaloThermo` component: oil (`oil_temperature`) and winding hot-spot (`hotspot_temperature`), thresholds from the run `settings` (`temperature_warning/critical`), label "Simulated · oil + winding model". `math.temperatureReading()` in `halo-command.js` already selects the correct headline value and level; reuse it.

---

## 8. Backend and firmware prerequisites, and open decisions

These are outside the frontend scope but block specific workstreams. They are listed so the frontend plan is honest about what it cannot deliver alone.

### 8.1 Industrial phase voltages (blocks 7.1 voltage plot)

`twin_core.telemetry()` emits `primary_voltage`/`secondary_voltage` only. Add `phase_voltage_a/b/c` (line-to-neutral, `secondary_voltage/√3 × voltage_pu`, balanced unless a voltage-imbalance input is later introduced) to `PHASE_FIELDS` so history and replay carry them. The waveform code and tests already expect those names.

### 8.2 K4 slot conflict (blocks 5.x)

Decision needed, one of:

- **(Recommended)** Firmware packs `relay_states = [load1, load2, load4, false]` so the backend's locked slot (index 3) stays the physically isolated branch. This aligns firmware, `halo_engine.py` K4 rule, `/relays` 403 rule and the UI's M4-is-isolated story without touching the engine. `to_frame()` needs no change.
- Or: change the `k4` rule in `halo_engine.py:158` to index 2 and keep firmware as is.

Until decided, Workstream C must treat M3 as display-only.

### 8.3 Optional: independent per-phase load inputs

If per-phase sliders are wanted, `Inputs` needs `phase_allocation: [a,b,c]` replacing the single imbalance number. Not required for O6 as stated.

### 8.4 Nothing else is required

`/esp32/*` already provides every value the prototype instruments need. The operator session token already authorises `POST /esp32/loads`.

---

## 9. Sequencing

| Step | Deliverable | Depends on |
|---|---|---|
| 1 | `halo-esp32.js` + `test_esp32_ui.mjs`; prototype header shows status ladder (3.2) | nothing |
| 2 | `halo-scope.js/.css` with prototype config; `#op-waveform` replaced; `test_scope.mjs`; `test_waveform.mjs` still green | 1 |
| 3 | `halo-thermo.js/.css`, prototype config | 1 |
| 4 | `halo-loads.js/.css`: M1–M4 mapping, gating, all-off; M3 display-only | 1, decision 8.2 for M3 switching |
| 5 | M4 cutoff state machine + banner + persistence; `test_loads.mjs` | 4 |
| 6 | Industrial scope (current plot, neutral), readings table, per-phase bars, breaker glyph, dual thermometer | 2, 3 |
| 7 | Industrial voltage plot | 8.1 |
| 8 | Accessibility and responsive pass (44 px targets, `prefers-reduced-motion` pauses sweep, 600 px breakpoint as in `halo-waveform.css`) | all |

Each step is independently shippable; the operate view must remain usable with only earlier steps merged.

---

## 10. Acceptance checklist

- Prototype mode with `HALO_ESP32_URL` unset: no requests to `/esp32/readings` beyond one `/status`; instruments show "integration off"; no console errors.
- Board unreachable with cache: STALE badge with age; load switches disabled; values still visible.
- Live board: scope and thermometer update every poll; duplicate `(boot_id, sequence)` adds no trend point.
- Primary current labelled "calculated" unless `primary_current_method === 'measured'`.
- M1/M2/M3 switch exactly `load1/load2/load4`; M4 never produces a request body containing `load3` or `load:3`.
- Toggling M4 sends one all-off request, shows the cutoff banner, disables M1–M3, persists through reload, clears on Restore or board reboot.
- 423 from `/esp32/loads` renders the lock message, not a generic failure.
- Industrial mode: three current traces plus neutral; neutral hidden with reason when inconsistent; voltage plot states "unavailable" until 8.1 lands.
- Thermometer never labels prototype `surface_c` as oil or winding.
- `node --test tests/*.mjs` and `pytest tests -q` pass; no change to backend tests is required by the frontend work.
- Lighthouse/axe: no new contrast or focus regressions against the current `/app#operate`.
