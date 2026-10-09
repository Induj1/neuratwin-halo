# Continuous physical-analysis recovery

The application owns one recovery task for each FastAPI lifespan. It runs independently of browser requests. It never opens a serial port, enables a relay, or authorizes commissioning. This is a recovery mechanism for accepted physical acquisitions, not electrical protection or a fleet-capacity claim.

## Delivery and ownership

An immutable accepted frame and its pending analysis job are committed together (SQLite transaction; existing Supabase migration `202610080004_hardware_provenance.sql` trigger). Recovery selects the oldest **due** jobs first, ordered by creation time and identity. Deferred failures and active leases are filtered before the bounded database result limit. The default batch is 25 jobs, capped at 100 per pass; later batches continue until due work is drained. Startup attempts only one job before the application becomes ready.

A job is durably claimed as `processing`, with a unique token, attempt counter and 120-second lease. A local `BEGIN IMMEDIATE` transaction or Supabase revision compare-and-swap protects competing claims. The subsequent result transaction atomically commits derived state, events and job completion. It verifies ownership and an unexpired lease before and after computation. A changed cloud revision rejects the entire stale outcome, including its events. Completed jobs are idempotent.

Claims and result commits use independent transactions rather than inheriting an HTTP request's cloud unit of work. An HTTP response failure therefore cannot discard an already accepted frame or successfully committed analysis. A process that dies after claiming leaves a lease which becomes reclaimable. After lease expiry, two processes can briefly perform the same calculation; fencing prevents both from committing competing effects. This is not a claim of exactly-once CPU execution.

Every recovery call invokes `process_prototype(..., allow_control=False)`. A newer admitted acquisition or a different active device causes an older recovery job to become `superseded`; comparison includes device, boot and sequence identity, so a replacement device cannot inherit an old job's provenance. Historical jobs do not rewind the current physical state. Draining a backlog therefore establishes a terminal outcome for every job, not retrospective full modelling of every stale acquisition. Live admission retains its existing explicit control gates. Recovery does not retry or replay physical commands.

## Failure and shutdown behavior

Failed processing returns the job to `pending`, with a durable sanitized error code and exponential delays of 2, 4, 8, 16, 32 and at most 60 seconds. A repeatedly failing oldest job does not block newer due work. Failed claim/result storage, rate limits and database errors stop the current batch. Whole-worker storage backoff starts at the normal two-second polling interval and caps at 60 seconds. No raw exception, frame, claim token or secret is exposed in worker diagnostics.

Healthy polling occurs every two seconds; a full batch permits a further bounded pass after 50 ms. The task stays alive after storage outages. Shutdown wakes an idle task immediately and waits for an in-flight job before stopping; it does not abandon a background thread midway through an atomic write. It checks the stop flag before the next job. A stuck database/network operation can delay shutdown until that operation returns or its I/O timeout expires. Supabase transport already has explicit request timeouts. This worker does not provide hard real-time shutdown or scheduling guarantees.

## Observable state and decision provenance

Authenticated operators can read `GET /api/halo/analysis-recovery`. It returns process-local cumulative attempts, successes, skips and failures; storage-failure counters; cycle/poll timestamps; current state; and up to eight oldest unfinished job metadata records. The sample is explicitly **not a total queue count**. `app.state.analysis_worker` owns the task; `app.state.acquisition_recovery` references the same state for compatibility. Restart resets in-memory counters; job attempts, deadlines and outcomes persist.

New physical decision provenance records include `analyzer_version = halo-prototype-analysis-2` and `rule_version = bench-limits-1`, alongside the acquired frame, archived configuration and calibration identities. These version names must change when the corresponding physical decision behavior changes. Existing historical outcomes are not silently stamped with the new version.

## Evidence and remaining limits

`tests/test_analysis_reliability.py` exercises 153 real SQLite jobs across repeated batches; oldest-first order; poison-job fairness; durable capped backoff; competing threads; expired ownership; atomic rollback; read and write outages; startup/shutdown; authenticated diagnostic disclosure; and physical version binding. `tests/test_cloud_analysis_reliability.py` exercises independent cloud transactions, competing revision claims, stale-outcome rejection and bounded query construction through mock transport. No external database, hardware, mains circuit or serial port is used.

The cloud mock tests do not replace an operational PostgREST/database check against the deployed schema. This change requires no new SQL migration. Queue selection uses the existing records table and JSON fields; large-fleet query/index performance has not been established. Polling is bounded, but a prolonged outage can still grow the durable backlog and storage. There is no automatic deletion, dead-letter discard, SLA, or automatic retry of physical control. Permanent invalid jobs remain visible and retried at the capped interval until an operator resolves the underlying cause.
