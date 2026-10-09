# Physical acquisition provenance and recovery

These changes support the low-voltage bench measurement workflow. They do not commission a transformer, approve mains wiring, or make the software an electrical protection device.

## Configuration contract

Saving `/api/halo/config` archives a content-addressed configuration version (`CFG-` followed by SHA-256 of the validated configuration). Both `/api/halo/config` and authenticated `/api/halo/device/config` expose its `config_id`. Existing configurations that were never archived return no ID until an operator explicitly saves them. Saving does not turn any commissioning checkbox on.

The USB bridge retains that ID when it converts an acquisition, alongside its immutable calibration ID and raw ADC/surface values. Its durable outbox preserves these references, values and acquisition time across retries. The ID identifies the server configuration used by the bridge; it is not proof of the firmware's physical wiring.

`hardware_config_status` is a separate bridge report:

| Value | Meaning |
| --- | --- |
| `reported_match` | Firmware handshake chip, protocol, device identity, ADC assignments, temperature pin, relay pins and polarity match the server configuration. This is a firmware report, not an independent wiring test. |
| `mismatch` | The reported configuration disagrees. Measurements cannot qualify decisions or enable a load. |
| `unverified` / absent | A complete comparison is unavailable. No implied approval. |

Physical ON permission still requires all existing commissioning checks, explicit enablement, compatible compiled firmware, valid fresh acknowledged acquisition, relay-state confirmation, reviewed calibration and allowed load/current/temperature. The latest frame and requested command must refer to the active immutable configuration. K4 remains locked. All-OFF requests remain available under their existing contract.

The normalized `/api/halo/device/twin-telemetry` endpoint accepts the same `config_id`, `hardware_config_status` and `raw` fields. Missing legacy references are never filled with today's configuration. Legacy measurements remain visible, but configuration-derived thresholds, load percentage and condition interpretation are withheld. Bound historical measurements retain their original limits when current settings change. Surface models retain both configuration and calibration identities; a mismatch requires a new qualified fit.

## Maintenance comparison

An apparent improvement cannot close a physical incident if its before/after windows have different or missing calibration IDs or configuration IDs. Both windows need one valid reviewed calibration, one intact commissioned configuration, matching firmware reports, acquisition evidence IDs and raw surface/current/secondary-voltage values consistent with the recorded conversion.

For example, raw surface temperature of 50 °C under CAL-A with a zero offset and the same raw value under CAL-B with a −4 °C offset is **insufficient evidence**, not a 4 °C repair improvement. Missing raw history is also insufficient. Existing minimum sample/span, comparable current/ambient and active-warning checks still apply. A successful comparison establishes only a comparable surface response; it does not prove recovered insulation life or a repaired distribution transformer.

## Accepted acquisition and pending analysis

In SQLite, the immutable frame and `analysis_job` record commit together. In Supabase, migration `202610080004_hardware_provenance.sql` adds an insert trigger that performs this atomic step. It also creates a recovery job for each device's newest historical frame without editing its data or inventing configuration references.

If decision processing fails after acquisition admission, the accepted frame and pending job survive. Derived state, events, commands and job completion commit together, so a partial local analysis rolls back. An exact acquisition retry can reprocess a due pending job; persisted retry delays and ownership leases are respected. Conflicting sequence reuse remains rejected. Completed jobs are idempotent.

The application lifespan now owns a continuous, bounded recovery worker. It attempts one job at startup and drains additional due jobs oldest-first in batches of 25, with durable ownership leases, atomic result fencing and bounded retry backoff. Recovery always disables physical commands and never opens a serial port. A newer live acquisition prevents an older pending job from rewinding current state; that job becomes explicitly `superseded`. This does not claim retrospective modelling of every historical frame. Authenticated diagnostics are available at `/api/halo/analysis-recovery`; lifecycle state is retained on `app.state.acquisition_recovery`. See [Analysis recovery worker](ANALYSIS_RECOVERY_WORKER.md) for delivery guarantees, tests and operational limits.

Supabase hardware ingestion checks the new capability RPC before admission. If the migration or trigger is absent, it returns 503 before accepting a new frame. `/api/halo/status` exposes this readiness separately. The existing application can still start and provide read-only views; no automatic SQLite fallback or remote schema changes occur.

## Regression evidence

`tests/test_hardware_provenance.py` exercises CAL-A/CAL-B false improvement, raw inconsistency/missing data, actual closure gating, valid comparable response, immutable historical limits, legacy unbound data, mismatched firmware reports, bridge outbox retention, analysis failure rollback, restart recovery without commands, superseded historical jobs and missing cloud migration admission. Tests use disposable local databases and software fixtures. Cloud SQL must additionally be applied and verified against the intended project; these tests do not claim a live hardware test.
