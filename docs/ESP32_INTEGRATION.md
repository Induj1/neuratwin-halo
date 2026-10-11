# Wi-Fi ESP32 integration

`firmware/esp32_integration/esp32_integration.ino` turns the bench-tested
`hardware/esp32.ino` sketch into a JSON API. The backend polls that API, forwards
each new acquisition into the ordinary telemetry path, and proxies load and
calibration requests from operators. No serial port is involved; the USB bridge
(`scripts/usb_bridge.py`) is a separate, older transport.

## Flow

```
ESP32 (HTTP server, Wi-Fi) <── poll /healthz + /api/readings every 2 s ── backend poller
                           <── POST /api/loads, /api/calibration ────────── backend proxy ── operator UI
backend poller ── Frame ──> /api/halo/telemetry path ──> snapshot / twin / evidence
```

The board keeps its own calibration in flash. The backend therefore records
frames with the `calibration_unrecorded` flag: a reviewed backend calibration
record never applies to values the board has already scaled. The board's primary
current is derived from secondary power unless the firmware is built with
`USE_MEASURED_MAINS_CURRENT = true`; the derived value is kept in `raw` as
`primary_current_calculated_a` and is not presented as a measurement.

## Set up

1. In the sketch, set `WIFI_SSID`, `WIFI_PASSWORD` and `API_TOKEN`. Keep
   `DEVICE_ID` equal to the backend's configured device id (default `HALO-ESP32`).
2. Flash it as **ESP32 Dev Module** with ArduinoJson 7, OneWire and
   DallasTemperature installed. The serial monitor prints the IP address.
3. In `.env`:

   ```
   HALO_ESP32_URL=http://halo-esp32.local      # or http://<ip from serial monitor>
   HALO_ESP32_POLL_SECONDS=2
   HALO_DEVICE_TOKEN=<same value as API_TOKEN>
   HALO_ALLOW_CONTROL=1                        # required for load switching
   ```

   Keep the hostname even when DHCP changes the board's IP. Automatic discovery
   is enabled by default for `.local` names and private IPv4 board URLs.
4. Install the local-network discovery dependencies in the backend environment:
   `python -m pip install -r requirements-esp32.txt`.
5. Start the backend. `GET /api/halo/esp32/status` shows whether the poller can
   reach the board.

## Automatic reconnection

If polling fails, the backend rechecks the last verified address, directly queries
the board's `_http._tcp.local.` mDNS service, then tries local ARP neighbours and
a bounded local IPv4 scan. This bypasses Windows hostname-resolution failures.
Searches retry at most once every 15 seconds while the board is absent; ordinary
polling resumes once it is found. Wi-Fi adapters are re-enumerated on each search.
The discovery dependencies are separate from the numerical evaluation manifest;
simulation-only servers can use the core requirements alone. Missing discovery
dependencies appear explicitly in the status endpoint while ordinary URL-based
polling continues.

Discovery only reads `/healthz` and `/api/readings`. It checks the firmware,
configured device ID and boot ID, and verifies an authenticated acquisition before
adopting an address. Unrelated HTTP servers do not receive the device token.
Reconnect never replays load/calibration commands or changes measured values.
Cached readings remain stale while the board is missing.

The selected address is shared by readings and explicit operator commands.
`/api/halo/esp32/status` exposes `configured_url`, the current `url`, and discovery
progress inside `poller.discovery`. A local `esp32-discovery.json` alongside the
SQLite database retains the last address without credentials; it is revalidated
after a server restart, not blindly trusted.

Optional settings (the defaults require no additional setup):

```
HALO_ESP32_DISCOVERY=1
HALO_ESP32_DEVICE_ID=HALO-ESP32
HALO_ESP32_HOSTNAME=halo-esp32.local
```

Set discovery to `0` to use only the configured URL. Unsetting `HALO_ESP32_URL`
still disables the integration entirely. The laptop and ESP32 must be on a
mutually reachable network. Discovery cannot bypass Wi-Fi client isolation or
firewalls. The fallback is capped at 512 hosts and /24-sized local ranges; a
campus /16 is not swept. On wider LANs, mDNS or an ARP neighbour must expose an
address outside those ranges.

No firmware reflash is needed for this backend change when using the existing
`esp32_integration` sketch, which already advertises the HTTP service. The mDNS
client uses [python-zeroconf](https://python-zeroconf.readthedocs.io/en/stable/api.html)
with the [ESP32 mDNS service](https://docs.espressif.com/projects/esp-protocols/mdns/docs/latest/en/index.html).

## Backend routes

The control centre runs an independent oil demo when prototype inputs are
offline or missing usable model inputs. It starts at 65% simulated loading and 35 °C,
with the existing 60× model clock. Analysis contains its load slider, advance
button and fault scenarios. Usable live inputs automatically replace this demo.
Demo results and report exports identify their simulated inputs; they never
populate measured channels, save telemetry or send relay commands. Surface
annunciation uses 50 °C warning / 55 °C critical demo thresholds when reviewed
limits are absent. These display defaults do not commission hardware or enable
automatic cutoff.

Above the response graphs, Surface temperature displays the fresh probe value.
Set its alarm threshold beside that readout; the choice persists in this browser.
The warning is 5 °C lower, and the repeating critical siren clears after 2 °C of
recovery or acknowledgement. Offline and replay readings cannot raise a measured
temperature alarm. Source-instrument current and loading gauges prefer a valid
estimate and label it Estimated; the underlying measured channels remain intact.

With live inputs, the oil model uses that same displayed current estimate and
the measured surface temperature. A current-sensor disagreement remains visible
but does not replace these inputs with the independent demo. Oil temperature,
pressure and oil level remain conditional estimates, not measured channels.
Expected load current uses the displayed secondary voltage and active resistor
branches; the board's original expected-current value is retained separately.

Reading age advances from the first receipt of each boot/sequence pair. Repeated
responses cannot make a frozen acquisition fresh. Instrument polling runs
independently of slower history requests, and the prototype snapshot can include
the newest cached acquisition while storage catches up, without inventing a
stored evidence ID or enabling controls.

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /api/halo/esp32/status` | none | Poller state: reachable, last seen, forwarded count, last errors. |
| `GET /api/halo/esp32/healthz` | none | Live pass-through of the board's `/healthz`. |
| `GET /api/halo/esp32/readings` | none | Live board reading. When the board is unreachable, returns the poller's last reading with `stale: true`. |
| `GET /api/halo/esp32/loads` | none | Load 1/2/4 drive states as the board reports them. |
| `POST /api/halo/esp32/loads` | operator + `HALO_ALLOW_CONTROL=1`; ON also requires commissioning and a clear trip latch | `{"load":4,"state":true}` or `{"load1":false,"load2":true}`. Load 3 is not wired. Records an `esp32_load_set` event. |
| `GET /api/halo/esp32/calibration` | none | Board factors, sensitivity, method and status. |
| `POST /api/halo/esp32/calibration` | operator + `HALO_ALLOW_CONTROL=1`, commissioning, and a clear trip latch | `{"action":"mains_voltage","value":228}`; actions `mains_voltage`, `secondary_voltage`, `current_meter`, `sensor_model` (66/100/185), `auto`, `zero`, `reset`, `step_test`. Returns the board's log; a board-side failure is `422` with that log. Records an `esp32_calibration` event. |
| `POST /api/halo/esp32/poll` | operator | Force one poll now and return the poller state. |

Calibration writes require explicit hardware enablement, completed commissioning, and a clear trip latch because several firmware calibration routines switch relays. Read-only calibration inspection remains available while control is disabled. Load-ON requests are rejected while commissioning holds or the prototype trip latch remain active; with hardware control enabled, all-OFF remains available.

Operator auth is the usual local session token or Supabase operator identity.
The device token is only ever sent from the backend to the board.

## Operator UI (Physical prototype mode)

`/app#operate` → Working source **Physical prototype**. When `HALO_ESP32_URL` is
set, the view polls `GET /api/halo/esp32/readings` on the same 2.5 s tick as
`/twin/prototype` and renders three hardware instruments
(`web/halo-esp32.js` feeds `web/halo-scope.js`, `web/halo-thermo.js`,
`web/halo-loads.js`):

| Instrument | Source | Notes |
| --- | --- | --- |
| Hardware scope | `primary_v`, `secondary_v`, `primary_current_a`, `current_a`, `expected_current_a` | Waveform mode is a √2·RMS 50 Hz reconstruction; trend mode is RMS over the last 5 min (browser buffer, cleared on `boot_id` change). Primary current is labelled *calculated* unless the firmware reports `measured`. |
| Surface thermometer | `surface_c`, `temperature_probe_ok`, `surface_invalid` flag | Always labelled surface / DS18B20. Warning and critical ticks come from the prototype settings (commissioned surface limit − 5 / limit); without a limit the ticks are absent. |
| Load controls M1–M4 | `loads`, `POST /api/halo/esp32/loads` | The UI shows four identical loads. The remap is frontend-only: M1→`load1`, M2→`load2`, M3→`load4`, M4→no hardware. Switching M4 sends `{load1:false,load2:false,load4:false}` and shows the "Load exceeded, supply cut off" banner until **Restore supply**. The cutoff state survives a reload (`sessionStorage`) and clears on board reboot. Switches are disabled when the board is unreachable or stale, when `HALO_ALLOW_CONTROL` is off (423), or while a trip is latched. The backend and firmware are unchanged. |

Without `HALO_ESP32_URL` the view falls back to the older `/relays` command
queue (USB bridge).

## What the integration does not claim

An acknowledged load request is a relay drive state, not contact feedback.
Calibration actions store scaling on the board; they are not a reviewed
calibration record and do not satisfy commissioning holds. `/healthz` reachable
means the controller answered HTTP, nothing more. Electrical review and physical
verification remain outstanding as described in the hardware guide.

## Tests

### Protection studies and oil inventory

In Control centre > Analysis, Electrical protection study provides separate
overload, short-circuit and restored-supply exercises. The event recorder shows
current, voltage and sampled current-squared exposure. Exercises are independent
of source instruments and send no ESP32 commands. Live RMS screening requires
independent calibrated current; the resistor-bank estimate cannot detect a fault.
Overload and voltage-dip/current thresholds, persistence and startup guard are
editable study assumptions. Recovery margins are 0.05 per unit for overload and
10% for the high-current indication. These are advisory settings, not a physical
protective relay. Sparse RMS data cannot establish inrush or internal-fault cause.

The virtual oil profile starts with 200 L at 25 C, a 30 L gas cushion and a 40 L
conservator. Inventory is distinct from conservator fill and thermally expanded
volume. Slow loss is 0.12 L/model minute; rapid leakage is 2 L/model minute. At
60x, 15 real seconds of the rapid scenario represent a 30 L loss. Stop leak and
Reset scenario retain missing oil; only Record simulated refill replenishes it,
capped at the original inventory. Changing working source starts a new scenario.
No evaporation rate is inferred from electrical or surface measurements.

The forecast retains missing oil and continues the declared leak rate. A positive
rate gives a conditional time to the low-inventory limit; an already exceeded
limit gives zero even after leakage stops. Defaults of 95% warning and 90%
critical are configurable demo assumptions, not universal industrial limits.
Effective thermal capacity combines declared solid capacity with oil density,
inventory and specific heat. The heat-transfer coefficient is held fixed, so oil
loss changes response speed without inventing a higher steady-state temperature.
Gas-cushion pressure assumes a rigid sealed tank and no gas exchange, including
during the idealised leak; it does not model rupture or air ingress.

Calculation drawers expose equations, substituted inputs, units and assumptions
for loading/I-squared-R, sampled I-squared-t, prospective terminal fault current,
oil mass balance, time to limit, expansion, thermal capacity, top-oil response,
gas pressure and FEM balance. Absolute copper loss and prospective fault current
remain unavailable until winding resistance and impedance are declared.
The FEM field remains a separate illustrative geometry; it is not claimed as a
calibrated internal temperature field for the bench or the 200 L oil model.

Create job card freezes an abnormal study under Maintenance > Protection job
cards. Save findings, record the corrective action, then compare a newer
follow-up using unchanged assumptions. Simulated restored supply permits a
model-recovery comparison after an electrical exercise. Findings and model
recovery do not establish physical repair. Job PDFs and the main report retain
source labels, calculations, event traces and the maintenance trail.

References: [Schneider terminal fault-current approximation](https://www.electrical-installation.org/enwiki/Short-circuit_current_at_the_secondary_terminals_of_a_MV/LV_distribution_transformer),
[Alliander thermal modelling documentation](https://alliander-opensource.github.io/transformer-thermal-model/),
and [Eaton liquid-immersed transformer maintenance guidance](https://www.eaton.com/content/dam/eaton/products/medium-voltage-power-distribution-control-systems/iec-assemblies-mv-switchgear/ulusoy-oil-immersed-type-transformer/eaton-liquid-immersed-distribution-transformers-manual-en-us.pdf).

### Verification

`tests/test_esp32.py` and `tests/test_esp32_discovery.py` cover integration,
DHCP changes, reboot recovery, stale readings, identity/authentication rejection,
last-address revalidation, retry throttling and bounded interface discovery.
They use mocked transports; no network, port or hardware is touched.
