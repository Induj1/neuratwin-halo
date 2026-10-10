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

   If `halo-esp32.local` does not resolve on your network, use the IP.
4. Start the backend. `GET /api/halo/esp32/status` shows whether the poller can
   reach the board.

## Backend routes

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /api/halo/esp32/status` | none | Poller state: reachable, last seen, forwarded count, last errors. |
| `GET /api/halo/esp32/healthz` | none | Live pass-through of the board's `/healthz`. |
| `GET /api/halo/esp32/readings` | none | Live board reading. When the board is unreachable, returns the poller's last reading with `stale: true`. |
| `GET /api/halo/esp32/loads` | none | Load 1/2/4 drive states as the board reports them. |
| `POST /api/halo/esp32/loads` | operator + `HALO_ALLOW_CONTROL=1` | `{"load":4,"state":true}` or `{"load1":false,"load2":true}`. Load 3 is not wired. Records an `esp32_load_set` event. |
| `GET /api/halo/esp32/calibration` | none | Board factors, sensitivity, method and status. |
| `POST /api/halo/esp32/calibration` | operator | `{"action":"mains_voltage","value":228}`; actions `mains_voltage`, `secondary_voltage`, `current_meter`, `sensor_model` (66/100/185), `auto`, `zero`, `reset`, `step_test`. Returns the board's log; a board-side failure is `422` with that log. Records an `esp32_calibration` event. |
| `POST /api/halo/esp32/poll` | operator | Force one poll now and return the poller state. |

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

`tests/test_esp32.py` runs the integration against an in-process fake board
(`httpx.MockTransport`); no network, port or hardware is touched.
