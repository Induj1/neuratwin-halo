# Backend operations

Supabase is the configured persistent backend. The numerical FastAPI application runs separately. No private environment is shipped in the submission.

### Start

```powershell
python -m pip install -r requirements.txt
.\start-halo.ps1
# Equivalent API-only launch, reading your private configuration:
python -m uvicorn neuratwin.app:app --host 127.0.0.1 --port 8765 --env-file .env
```

Open `/app#integrations` for the assistant and connected tools. Account and team controls live under **Account**; infrastructure diagnostics are available through the authenticated `/api/auth/backend` endpoint, not advertised in the operator interface. The local
setup explicitly enables `HALO_LOCAL_OPERATOR=1`: same-origin loopback clients on
this computer receive an owner session. This is a trusted development-computer
mode, not team authentication. **Use `HALO_LOCAL_OPERATOR=0` on any shared/hosted
server**, omit the optional administrator token, and sign in with team accounts.
There is no automatic switch to SQLite if the cloud fails. To run a separate
local rehearsal, explicitly choose `HALO_STORAGE_BACKEND=sqlite`; that local data
is not silently synchronized with the cloud.

### Create a real team account

Use the server-side administrator tool. It prompts for a password without echoing
it, creates a confirmed account, and sends no email. Give each teammate a separate
account; do not share the Supabase secret or database password.

```powershell
python scripts/supabase_admin.py create-user --email YOUR_EMAIL --role admin
python scripts/supabase_admin.py create-user --email TEAMMATE_EMAIL --role operator
python scripts/supabase_admin.py list
python scripts/supabase_admin.py set-role --user-id USER_UUID --role viewer
python scripts/supabase_admin.py set-role --user-id USER_UUID --role viewer --disable
```

The web **Account** dialog provides email/password sign-in. Administrators manage existing accounts by email and edit roles or pause access in **Account → Team access**. Auth tokens
live in HttpOnly, SameSite cookies, not JavaScript storage. The server verifies
ES256/RS256 signatures against the project's JWKS and checks issuer, audience,
expiry, UUID and current membership. Membership changes take effect on the next
request. A Supabase Auth user without an active NeuraTwin membership gets no app
access. There is no public self-enrollment or automatic first-user administrator.

| Role | Access |
| --- | --- |
| Viewer | Read application evidence and studies |
| Operator | Also import, investigate, upload inspection photos and create studies |
| Admin | Also commission/configure the bench, record calibration and manage team access |

Inspection photo download requires operator access. Device ingestion uses its own
`HALO_DEVICE_TOKEN`, provisioned in the private local configuration. The bridge
loads it from `.env`; it never receives a Supabase secret. Judge capabilities stay
case-scoped and cannot read other evidence or call equipment controls. Service-role
credentials are privileged and remain exclusively on the backend/administrator CLI.

### What is persisted

- `halo_records`: configuration versions, calibration, model fits, datasets,
  investigations, observations, assessments, commands, Arena cases and studies;
  older distribution assets/work orders use namespaced record kinds.
- `halo_frames`: immutable device frames, ordered by acquisition identity and time.
  A PostgreSQL transaction serializes each device, accepts identical retries and
  rejects changed retries, backwards timestamps, old sessions and future frames.
- `halo_events`: event ledger and committed-request audit. SQL transactions commit
  related record writes and audit entries together.
- `halo_kind_revisions`: prevents concurrent inserts from invalidating a read such
  as “no incident exists.” Per-record revisions also prevent lost updates.
- `halo_members`: active viewer/operator/admin access, separate from Auth users.
- Private `halo-evidence` bucket: validated JPEG/PNG inspection photos. Metadata
  retains a SHA-256 checksum. Downloads pass through the authenticated backend.

All five application tables have RLS enabled with client grants revoked. Browser
and signed-in client keys cannot directly query these private records or invoke
privileged database functions. This intentionally protects hidden Arena schedules
as well as field evidence; the FastAPI server mediates access. Storage has no
public-read policy. Database records and audit are atomic; object upload happens
first, so an interrupted metadata commit can leave an unreferenced private object.
Do not delete objects merely because a client did not receive an acknowledgement.

The original demo database contained 53 records and 9 audit events, with zero
physical frames. Migration copied 51 records and preserved the 9 events in an
`imported_audit` namespace; two integration/subscription states were skipped to
avoid restarting external actions. Existing synthetic evidence remains labelled
synthetic. No measurements, calibration or physical readiness were invented.

### Schema and migration

All three checked-in migrations are installed and recorded in the new project. For a
fresh project with an authorized CLI account:

```powershell
supabase link --project-ref YOUR_PROJECT_REF
supabase db push --linked
supabase migration list --linked
```

The CLI also supports applying a migration with `supabase db query --linked --file
PATH_TO_MIGRATION`; record an externally applied migration with `supabase migration
repair VERSION --status applied --linked`. Never reset a populated remote database
to install this application. The migration is additive and scopes objects to Halo.

To import another local database, make a backup, review the dry-run counts, then:

```powershell
python scripts/migrate_to_supabase.py --source runtime/neuratwin.sqlite3
python scripts/migrate_to_supabase.py --source runtime/neuratwin.sqlite3 --apply
```

The source is read-only. Existing cloud IDs are skipped, telemetry identity is
idempotent, and pending commands/integration state are not reactivated. Configure
matching project credentials for the web server and optional Telegram worker.
Run only one Telegram polling worker per bot; outbound delivery is not exactly-once.
No worker or serial bridge starts automatically with the web app.

### Hosting and verification

Supabase hosts the database, Auth and evidence files. The numerical FastAPI/Laya
application still runs on this computer; **this change does not publicly deploy
the full website**. A production host must run the Python requirements, inject the
private server environment, terminate HTTPS, pass only trusted proxy headers, use
`HALO_LOCAL_OPERATOR=0`, and set `HALO_PUBLIC_URL` to its HTTPS URL. Configure Laya
as a private service if required; numerical rules remain available without it.
`/api/health` is liveness; authenticated `/api/auth/backend` verifies schema and
bucket privacy. Browser telemetry refresh still polls; no realtime-stream claim
is made. Plan storage/retention and backups before long-running field acquisition.

```powershell
python -m pytest tests -q
# Explicit live verification; creates/removes only its own isolated QA records:
python scripts/verify_supabase.py --run
supabase db advisors --linked --type security --level warn
```

Verification reports are in `reports/halo-supabase-tests.xml` and
`reports/supabase-integration.json`. Live tests cover real password/JWKS sign-in,
HttpOnly sessions, refresh/sign-out, immediate role revocation, private evidence
round trips, denied direct table/RPC access, acquisition ordering/idempotency,
K4 lockout and concurrent write conflicts. QA accounts use `.invalid` addresses;
no email is sent. Hardware, external Telegram delivery and public hosting remain
separate from these software checks.

References: [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys),
[JWT verification](https://supabase.com/docs/guides/auth/jwts),
[row-level security](https://supabase.com/docs/guides/database/postgres/row-level-security),
[private Storage access](https://supabase.com/docs/guides/storage/security/access-control).
