# Supabase + R2 + Schema v3 Migration Report

Branch: `feat/supabase-r2-schema-v3` (from `main`, commit `7be1840`)
Scope: `data_collection/backend` only. Frontend untouched.

---

## ✅ Update — Supabase project created, schema live, verified against it

After the initial pass, a dedicated Supabase project was created and linked, which
cleared the largest blocker. What changed:

- **Project created:** `dynalytix-climbing`, ref `nbqtgknayvsjkevaoeef`, org
  **Dynalytix** (`huwgfrlivqxluwsjkxln`), region East US (North Virginia).
  Dashboard: https://supabase.com/dashboard/project/nbqtgknayvsjkevaoeef
- **CLI linked** to that project. The shared `login_system` project is no longer
  referenced anywhere.
- **Migration applied for real** with `supabase db push`. Verified over psql
  against the live database: 7 tables, RLS enabled on all 7, 4 policies on each
  data table, `schema_version = 3`.
- **`.env` rewritten** for the new project: `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
  `SUPABASE_SERVICE_ROLE_KEY`, and a working `DATABASE_URL`. R2 variables are
  present but still empty. A backup of the previous `.env` is in the session
  scratchpad. No secret value appears in this report or in any commit.
- **Test suite run against the live Supabase database: 61 passed.**
- **Smoke test run with real ES256 access tokens** for two throwaway users
  created through the auth admin API, against the live database: **35 passed, 0
  failed.** R2 was still stubbed locally, as no R2 credentials exist yet.
- **`.gitignore` fixed:** `.env` was not ignored and now is, along with
  `supabase/.temp/` (which holds the pooler URL with credentials).

### Three real bugs this surfaced

Running against actual infrastructure rather than a local stand-in caught three
defects that would each have broken the Railway deployment:

1. **ES256 vs HS256.** Supabase projects created from 2025 on sign user tokens
   with an asymmetric ES256 key published via JWKS, not the legacy HS256 shared
   secret. `auth.py` verified HS256 only, so it would have rejected every real
   token from this new project with a 401. It now reads the token's `alg` header
   and verifies ES256/RS256 against the project's cached JWKS, falling back to
   HS256 for legacy projects. `SUPABASE_JWT_SECRET` is now optional.
2. **Prepared statements vs the transaction pooler.** psycopg3 prepares
   statements automatically; Supabase's pooler (pgbouncer, port 6543) multiplexes
   connections per transaction, so this raised `DuplicatePreparedStatement`
   intermittently — 5 test failures. `Database._configure_connection` now sets
   `prepare_threshold = None` on every pooled connection.
3. **Missing crypto extra.** `PyJWT` cannot do ES256 without the `cryptography`
   package; every authenticated request 500'd with
   `MissingCryptographyError`. `requirements.txt` now pins `PyJWT[crypto]`.

Also worth knowing: the **direct** database host (`db.<ref>.supabase.co:5432`) is
IPv6-only and unreachable from this machine. `DATABASE_URL` uses the transaction
pooler at `aws-0-us-east-1.pooler.supabase.com:6543`. Use the pooler on Railway too.

### Still outstanding

Only R2 and Railway now:

- No R2 account/bucket/credentials — `src/storage/r2.py` is untested against the
  real service, and the CORS rule in §6 is unapplied.
- Railway still has no linked project, so no variables are set and nothing is
  deployed.

Two throwaway auth users (`smoke-test-a@dynalytix.test`,
`smoke-test-b@dynalytix.test`) now exist in the project so the smoke test can be
re-run; delete them from Authentication → Users if you would rather not keep them.
The labeling tables were truncated afterwards, so the database is empty.

---

## ✅ Third update — R2 is live and verified

R2 was set up through the Cloudflare dashboard (browser-driven, with the account
owner signing in). Everything in steps 1 and 2 now passes.

**Resources created**

- **Bucket** `dynalytix-climbing` — Automatic location, resolved to Eastern
  North America (same region as the Supabase project and Railway). Public
  access **disabled**: all reads and writes go through presigned URLs.
- **Account API token** `dynalytix-climbing-backend` — permission **Object Read
  & Write**, scoped to that one bucket, TTL forever, no IP filter (Railway
  egress IPs are not static). Account-level rather than user-level, which is
  what Cloudflare recommends for production since it survives user changes.
- `.env` filled in: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
  `R2_BUCKET`. File is `chmod 600` and gitignored. No value appears in this
  report or any commit.

**Step 1 — object operations against the real bucket**

```
Verifying R2 bucket "dynalytix-climbing" at https://<account>.r2.cloudflarestorage.com

direct object operations
  PASS  put_object uploads
  PASS  object_exists finds it
  PASS  object_exists is False for a missing key
  PASS  get_object_stream round-trips the bytes
  PASS  missing key raises FileNotFoundError

presigned URLs (plain HTTP, no credentials)
  PASS  presigned_put_url returns a URL
  PASS  PUT to the presigned URL succeeds
  PASS  object landed in the bucket
  PASS  GET from the presigned URL succeeds
  PASS  presigned GET returns the same bytes

10 passed, 0 failed
```

The presigned PUT and GET were also exercised with `curl` directly, outside the
Python client, to confirm a browser can use them unaided:

```
=== curl PUT to presigned URL ===
http=200 uploaded=35B
=== curl GET from presigned URL ===
frame_number,timestamp_ms
0,0
1,33
http=200
```

**Step 2 — CORS**

Applied through the dashboard (R2 → bucket → Settings → CORS Policy) and
confirmed by the read-back table there:

| Allowed Origins | Allowed Methods | Allowed Headers |
|---|---|---|
| `*` | `GET`, `PUT`, `HEAD` | `Content-Type`, `Content-Length` |

`AllowedOrigins` is `*` because that is literally what `api.py` sets
(`allow_origins=["*"]`), which already subsumes `http://localhost:5173`.
Now that the frontend origin is known, narrowing both `api.py` and this rule to
`["https://collect.dynalytix.net", "http://localhost:5173"]` is worth doing —
say the word.

`PutBucketCors`/`GetBucketCors` over the S3 API return **AccessDenied** with this
token, which is correct and intentional: bucket configuration is an admin-scoped
operation and the production token is deliberately object-scoped. `verify_r2.py`
now reports that as an expected skip rather than a failure, and points at the
dashboard. To manage CORS over the API instead, create a separate Admin Read &
Write token.

**One diagnostic worth keeping**

The first attempts failed with `SSL: SSLV3_ALERT_HANDSHAKE_FAILURE` against
`*.r2.cloudflarestorage.com`, from curl and Chrome alike, while
`dash.cloudflare.com`, AWS S3 and Google Cloud Storage all responded normally —
the endpoint for a freshly created account takes a few minutes to start serving
TLS. It resolved on its own. `verify_r2.py` now does a TLS preflight and
explains this instead of surfacing a bare `SSLError` from inside botocore.

**Still outstanding: Railway.** The CLI is linked to
`steadfast-vitality` / `adorable-integrity` / `production`, and every variable
value now exists. Steps 3-6 were not run — see the deploy warning in §9 step 5:
that service is live on the old build behind `collect.dynalytix.net`, and this
branch breaks the current frontend until Terminal C ships the §7 changes.

---

## ✅ Fourth update — Railway variables set, deploy deliberately held

All eight v3 environment variables are now set on the Railway service
`steadfast-vitality` / `adorable-integrity` / `production`:

| Variable | Set |
|---|---|
| `DATABASE_URL` | ✅ 133 chars |
| `SUPABASE_URL` | ✅ 40 chars |
| `SUPABASE_ANON_KEY` | ✅ 208 chars |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ 219 chars |
| `R2_ACCOUNT_ID` | ✅ 32 chars |
| `R2_ACCESS_KEY_ID` | ✅ 32 chars |
| `R2_SECRET_ACCESS_KEY` | ✅ 64 chars |
| `R2_BUCKET` | ✅ 18 chars |

Lengths were checked against `.env` to confirm each landed intact. No value was
printed at any point: each was piped through
`railway variables --set-from-stdin <KEY>`, which keeps it off the command line
entirely, and read back only as a name and a length.

`SUPABASE_JWT_SECRET` is intentionally **not** set — this Supabase project signs
with ES256 and the public key is discovered from `SUPABASE_URL`.

**Nothing was deployed.** `--skip-deploys` was used on every write, so Railway
did not roll the service. Confirmed afterwards: the running deployment is still
the one from 2026-07-25 (~49 days old), `/` still answers from the old build and
`/api/health` still returns 404. `collect.dynalytix.net` is unaffected.

**`GITHUB_TOKEN` and `DATA_REPO` were left in place**, contrary to step 3, and
deliberately so: the deployed build still runs `data_sync.py`, and removing them
now would silently stop export CSVs reaching the `dynalytix-data` repo while the
old backend is still the one in service. They should be unset as part of the
cutover, in the same window as `railway up`.

### Remaining: the deploy itself

Everything is staged. The cutover is:

```bash
cd data_collection/backend
railway variables delete GITHUB_TOKEN --service adorable-integrity --environment production
railway variables delete DATA_REPO   --service adorable-integrity --environment production
railway up --service adorable-integrity
# then
curl https://adorable-integrity-production.up.railway.app/api/health
python scripts/smoke_test.py --url https://adorable-integrity-production.up.railway.app
```

This is gated on the frontend, not on the backend: the moment v3 is live, every
endpoint requires a bearer token and the request/response shapes in §7 change,
so `collect.dynalytix.net` stops working until Terminal C ships. Deploy the two
together, or stand up a staging service first.

---

## ✅ Fifth update — final verification checks

### Check 1: R2 steps 1-2 confirmed against the real bucket

`scripts/verify_r2.py`, run with the real credentials from `.env`:

```
Verifying R2 bucket "dynalytix-climbing" at https://<account>.r2.cloudflarestorage.com

direct object operations
  PASS  put_object uploads
  PASS  object_exists finds it
  PASS  object_exists is False for a missing key
  PASS  get_object_stream round-trips the bytes
  PASS  missing key raises FileNotFoundError

presigned URLs (plain HTTP, no credentials)
  PASS  presigned_put_url returns a URL
  PASS  PUT to the presigned URL succeeds
  PASS  object landed in the bucket
  PASS  GET from the presigned URL succeeds
  PASS  presigned GET returns the same bytes

10 passed, 0 failed
```

Presigned PUT and GET exercised with `curl`, outside the Python client:

```
=== curl PUT via presigned URL ===
http=200 uploaded=35B
=== curl GET via presigned URL ===
frame_number,timestamp_ms
0,0
1,33
http=200
```

**CORS.** `GetBucketCors` over the S3 API returns **AccessDenied**, and will
continue to: the production token is Object Read & Write, and bucket
configuration is admin-scoped. That is deliberate, not a gap. The rule was
instead confirmed two ways that do not need admin rights:

1. The dashboard read-back table (R2 → bucket → Settings → CORS Policy):
   origins `*`, methods `GET, PUT, HEAD`, headers `Content-Type, Content-Length`.
2. A live CORS **preflight** against a presigned PUT URL — the exact request a
   browser makes before uploading:

```
$ curl -X OPTIONS -H "Origin: http://localhost:5173" \
       -H "Access-Control-Request-Method: PUT" \
       -H "Access-Control-Request-Headers: content-type" "<presigned PUT url>"

HTTP/1.1 204 No Content
Access-Control-Allow-Origin: *
Access-Control-Allow-Headers: content-type
Access-Control-Allow-Methods: GET, PUT, HEAD
Access-Control-Max-Age: 3600
```

R2's edge confirms the rule is live and that `http://localhost:5173` may PUT.
This is stronger evidence than `GetBucketCors`, which only reads stored config;
the preflight proves the enforced behaviour. To read the config over the API
anyway, create a separate Admin Read & Write token.

### Check 2: GitHub auto-deploy IS enabled on `main` — unchanged, as instructed

`adorable-integrity` → Settings → Source:

| Setting | State |
|---|---|
| Source Repo | `Jolieabadir/dynalytix` |
| Branch connected to production | **`main`** |
| Auto deploys when pushed to GitHub | **ENABLED** (the button offered is "Disable") |
| Wait for CI | **OFF** — no CI gate; a push deploys straight away |
| Root directory | none — builds the repo-root `Dockerfile` |

The repo-root `Dockerfile` copies `data_collection/backend/` and runs
`uvicorn src.web.api:app`, so it builds exactly this branch's backend. The
running deployment's commit is `7be1840`, which is `main` HEAD precisely —
consistent with auto-deploy having produced it.

**So merging this branch to `main` deploys it within seconds, with no CI gate.**
Confirming your concern. I changed nothing.

**The important wrinkle:** the frontend deploys from `main` too.

| Service | Repo | Branch | Root directory |
|---|---|---|---|
| `adorable-integrity` (climbing **backend**) | dynalytix | **`main`** | repo root |
| `Data_collection_climbing` (climbing **frontend**) | dynalytix | **`main`** | `/data_collection/frontend` |
| `Movement_analysis` (FMS frontend) | dynalytix | `fms-demo` | `/data_collection/frontend` |
| `dynalytix` (FMS backend) | dynalytix | `fms-demo` | repo root |

That turns out to be helpful rather than harmful: **one merge to `main` carrying
both the backend and the frontend changes redeploys both services together**, so
the coordinated cutover happens on its own. `railway up` is not needed.

The danger is merging **only** the backend: the frontend service still rebuilds
from the same push, from unchanged source, and comes back up talking v2 to a v3
API. `collect.dynalytix.net` breaks either way if the two halves are merged
separately.

---

## ✅ Sixth update — CUTOVER COMPLETE (2026-09-13)

v3 is **live**. `main` is deployed to both services and the smoke test passes
against the real deployment with real R2.

| | |
|---|---|
| Backend | https://adorable-integrity-production.up.railway.app |
| Frontend | https://collect.dynalytix.net |
| Deployed commit | `62d3330` (tree identical to the merge `3e3cb26`) |

### The first attempt failed — worth recording

The first cutover was rolled back. `POST /api/videos/register` returned 500:

```
psycopg.errors.UndefinedColumn: column "width" of relation "videos" does not exist
```

`20260913180000_add_video_dimensions.sql` had been merged into the repo but
never pushed to Supabase. Production applies migrations with `supabase db push`;
`apply_schema_sql()` is a **test-only** path and never runs against production.
Nothing else failed — health, config and the taxonomy were all correct.

Two things this exposed, both now fixed in §9:

1. **The runbook had no "apply migrations" step.** It predated the
   dimensions migration. It is now step 0, with a hard stop if anything is
   pending.
2. **`supabase db push` cannot use `DATABASE_URL` as it is set.** That DSN is
   the *transaction* pooler (port 6543), which does not support prepared
   statements, and the CLI fails with
   `prepared statement "lrupsc_1_0" already exists (SQLSTATE 42P05)`. The API
   itself is fine — `database.py` sets `prepare_threshold = None` — but the CLI
   has no such escape. Use the **session** pooler: same host and credentials,
   **port 5432**. §9 step 0 spells this out.

The failed push applied nothing; `width`/`height` were still absent and the
migration history was unchanged afterwards.

### Migration state after the fix

```
   Local          | Remote         | Time (UTC)
  ----------------|----------------|---------------------
   20260913023235 | 20260913023235 | 2026-09-13 02:32:35
   20260913180000 | 20260913180000 | 2026-09-13 18:00:00

Remote database is up to date.
```

`public.videos` now carries `width integer NULL` and `height integer NULL`.
`schema_version` is still **3** — the migration is additive and deliberately
does not bump it, so a v3 reader is unaffected.

### Health, against the deployment

```
$ curl https://adorable-integrity-production.up.railway.app/api/health
{"status":"ok","database":"ok","r2":"ok","schema_version":3}

$ curl -o /dev/null -w '%{http_code}' .../api/config
401          # correct: /api/config requires a bearer token in v3
```

`r2` reads `ok`, not `not configured` — object storage is real, not stubbed.

### Smoke test output — 35 passed, 0 failed

Run against the deployed URL with real R2 and real ES256 tokens for two
throwaway users:

```
Using real Supabase access tokens for two throwaway users

Smoke test against https://adorable-integrity-production.up.railway.app

health
  PASS  GET /api/health is 200
  PASS  database reachable
  PASS  schema version is 3
  PASS  R2 configured

config
  PASS  GET /api/config is 200
  PASS  move_tags contains 'technical'
  PASS  move_tags contains 'tension'
  PASS  'timings' key is gone
  PASS  GET /api/config without a token is 401

register
  PASS  POST /api/videos/register is 201
  PASS  pose CSV key recorded
  PASS  fps round-tripped
  PASS  total_frames round-tripped

labels
  PASS  POST /api/holds is 201
  PASS  POST /api/moves is 201
  PASS  POST /api/environments is 201
  PASS  foot slot left empty
  PASS  POST /api/outcomes is 201
  PASS  POST /api/frame-tags is 201

export
  PASS  POST export is 200
  PASS  export key returned
  PASS  GET /api/exports/mine is 200
  PASS  export appears in /api/exports/mine
  PASS  export download redirects (307)
  PASS  presigned URL returned
  PASS  export object fetched from R2
  PASS  export header carries raw pose columns
  PASS  export header carries label columns
  PASS  labels joined onto frames

isolation (second user)
  PASS  other user GET video is 404
  PASS  other user GET moves is 404
  PASS  other user GET move is 404
  PASS  other user export is 404
  PASS  other user download is 404
  PASS  other user's export list excludes it

35 passed, 0 failed
```

The export section is the one that matters most: it round-trips a real object
through R2 (presigned PUT, 307 redirect on download, presigned GET) and
confirms the labels are joined onto the raw pose frames. The isolation section
confirms a second user gets 404 on every one of the first user's resources.

### After the run

Tables were truncated so the smoke test's rows do not pollute the first real
session:

```sql
TRUNCATE frame_tags, outcomes, environments, moves, holds, videos RESTART IDENTITY CASCADE;
```

### Retired variables

`GITHUB_TOKEN` and `DATA_REPO` were deleted from `adorable-integrity` during the
first attempt and were **not restored** — the v3 build does not use them, and
`data_sync.py` no longer runs. Their values were not recorded anywhere and are
not recoverable from `.env`. If the old build ever needs to run again, both
must be recreated.

---

## ⛔ Second update — R2 and Railway are still not available

A follow-up pass was requested on the premise that R2 credentials were in
`.env` and Railway was linked. Neither holds:

| Check | Command | Result |
|---|---|---|
| R2 credentials | read `.env` | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` are all present as keys but set to **empty strings**. The file has not been modified since it was written. |
| Railway linked | `railway status` | **Was not linked.** *(Resolved — now linked to `steadfast-vitality` / `adorable-integrity` / `production`; see §9 step 5 for how the service was identified.)* |
| `wrangler` | `which wrangler` | **Still not installed.** |

No other file on disk holds R2 credentials (searched every `.env*` in the repo).
So testing R2 against a real bucket, applying the bucket CORS rule, setting
Railway variables, deploying, and smoke-testing a deployed URL all remain
impossible.

**What was done instead**, so that none of it needs figuring out later:

- `src/storage/r2.py` gained `delete_object()`, `put_bucket_cors()` and
  `get_bucket_cors()`. R2 implements the S3 CORS API, so wrangler is not needed
  at all.
- `scripts/verify_r2.py` implements both R2 steps as one command. It covers
  `put_object`, `object_exists` (hit and miss), `get_object_stream` (byte
  comparison, plus `FileNotFoundError` on a missing key), a real
  credential-free HTTP PUT to a presigned URL, a presigned GET, then
  `PutBucketCors` from `r2-cors.json` and `GetBucketCors` read-back asserting
  PUT, GET and `http://localhost:5173` are permitted. It cleans up after itself
  and never prints a credential.
- `r2-cors.json` allows `GET`, `PUT`, `HEAD`. `AllowedOrigins` is `["*"]`
  because that is literally what `api.py`'s CORS config is
  (`allow_origins=["*"]`) — which already subsumes `http://localhost:5173`.
  Narrow both together once the deployed frontend origin is known.

The 61-test suite still passes against the live Supabase database after these
changes.

---

## ⚠️ Blockers found at step 0 (read this first)

The brief stated the Supabase and Railway CLIs were already linked and that all
secrets were in `.env`. None of that held. Verified:

| Check | Command | Result |
|---|---|---|
| Supabase CLI linked | `supabase projects list` | **Not linked** — "Cannot find project ref." *(Resolved — see the update above.)* |
| Dedicated Supabase project | `supabase projects list` | **Did not exist.** *(Resolved — `dynalytix-climbing` created.)* Org has: login_system, login_system_STEAP, divvy, freelance-agent, Neuroplica, Aami, steap-staging, steap-sandbox. No dynalytix/climbing project. |
| Backend's `SUPABASE_URL` target | ref matched against project list | Points at the **`login_system`** project — a shared auth project (created 2026-03-16), not a project dedicated to this app. |
| Railway CLI linked | `railway status` | **Not linked** — "No linked project found. Run railway link to connect to a project." |
| `wrangler` installed | `which wrangler` | **Not installed.** |
| `DATABASE_URL` | `.env` | **Was absent.** *(Resolved — now set to the transaction pooler.)* |
| R2 credentials (`R2_ACCOUNT_ID`, access key, secret, bucket) | `.env` | **All absent.** |
| `GITHUB_TOKEN` / `DATA_REPO` | `.env` | Absent locally (they are read from the environment at runtime, so they exist only as Railway service variables). |

`.env` contains exactly four keys: `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
`SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`. (No values are reproduced
anywhere in this report.)

**Consequence:** every step that writes code was completed. Every step that
requires live infrastructure could not be executed and is documented instead.
See "What could not be verified" at the end.

**Safety hold:** step 3 asks to drop the old labeling tables and apply the
migration with `supabase db push`. The only Supabase project this repo is
configured against is `login_system`, which by its name and age serves other
applications. Running a DROP-and-recreate migration there could destroy another
app's data, so the migration file was written but **deliberately not applied**.
This is the one instruction I did not carry out autonomously.

---

## 1. Current data flow (before this change)

### Storage layout on Railway's ephemeral disk

```
backend/
  data/labels.db            <- SQLite, ALL labels
  data/<video_stem>.csv     <- raw pose CSV, one per video
  data/exports/*_labeled.csv<- joined export output
  videos/<safe_filename>    <- original video file (server-upload path only)
```

Every one of these lives on the container filesystem and is lost on redeploy.
The GitHub sync in `data_sync.py` is the only thing that survives a restart, and
it only covers export CSVs.

### `src/labeling/models.py`
Pure dataclasses, no DB dependency: `Video`, `Move`, `Environment`, `Outcome`,
`FrameTag`, plus taxonomy constants (`APPROACHES`, `SIZES`, `MOVE_TAGS`,
`TIMINGS`, `DYNO_STYLES`, `WALL_ANGLES`, `HOLD_TYPES`, `HOLD_QUALITIES`,
`RESULTS`, `REACH_DETAILS`, `CONFIDENCE_LEVELS`, `TAG_TYPES`, `SIDES`,
`TRACTION_SOURCES`, `BODY_PARTS`). No `user_id` anywhere — the system is
single-tenant. No `Hold` model; holds do not exist yet.

### `src/labeling/database.py`
`Database` class over `sqlite3`, `SCHEMA_VERSION = 3`, file at `data/labels.db`.
- `get_connection()` — contextmanager, `sqlite3.Row` factory, commit/rollback/close.
- `init()` — creates `schema_version`, compares `MAX(version)`, calls `_apply_schema` when behind.
- `_apply_schema()` — `CREATE TABLE IF NOT EXISTS videos`, then **drops and recreates**
  `frame_tags`, `outcomes`, `environments`, `moves`, then four indexes.
- CRUD per entity. Lists/dicts are persisted as `json.dumps` into `TEXT`
  columns (`move_tags`, `contextual_data`, `tags`, `hold_quality`, `locations`)
  and revived with `json.loads` in the `_row_to_*` helpers.
- Datetimes stored as ISO `TEXT`, parsed back with `datetime.fromisoformat`.
- `foot_cut` stored as `INTEGER` 0/1.
- Placeholders are `?`; ids come from `cursor.lastrowid`.

### `src/labeling/exporter.py`
`Exporter.export_video(video_id, delete_video=False)`:
1. `db.get_video` → `db.get_moves_for_video`.
2. Per move, fetch environment, outcome, frame tags; expand into a
   `frame -> labels` dict covering `frame_start..frame_end` inclusive.
3. Read `video.csv_path` from local disk with `csv.DictReader`.
4. Append 23 label columns to the raw pose header, pipe-joining multi-valued
   frame-tag fields.
5. Write to `data/exports/<raw_stem>_labeled.csv`.
6. If `delete_video`, `unlink()` the original video file.

### `src/labeling/data_sync.py`
`push_csv_to_github(csv_path, repo=None, branch="main", folder="collected_data/climbing")`.
Reads `GITHUB_TOKEN` and `DATA_REPO` from the environment, base64-encodes the
file and PUTs it to the GitHub contents API at
`collected_data/climbing/<timestamp>_<name>.csv`. Silently no-ops when the env
vars are missing. Called only from the export endpoint, wrapped in a
try/except so failures are non-blocking.

### `src/web/api.py`
FastAPI app, version 2.0.0. **`allow_origins=["*"]`, `allow_credentials=False`**
— there is no specific frontend origin configured anywhere. Module-level
singletons: `db = Database('data/labels.db')`, `db.init()`, `exporter = Exporter(db)`.
Mounts `videos/` as static files. **No authentication of any kind** — every
endpoint is open and unscoped.

Endpoints:
- `GET /` — health-ish, returns `{"status":"ok", ...}`. There is no `/api/health`.
- `GET /api/config` — returns the whole taxonomy from the `models.py` constants.
- `POST /api/videos/upload` — multipart video; saves to `videos/`, shells out to
  `main.py` for pose extraction via `subprocess`, writes CSV to `data/`.
- `POST /api/videos/register` — form fields `filename, fps, total_frames,
  duration_ms, csv_data`; client-side pose path. Writes `csv_data` to local disk.
- `GET /api/videos`, `GET /api/videos/{id}`, `GET /api/videos/{id}/csv`.
- `POST /api/videos/{id}/export?delete_video=bool` — runs the exporter, then
  fires the GitHub sync. Returns `{path, video_deleted}`.
- `GET /api/videos/{id}/export/download` — `FileResponse` off local disk.
- Moves: `POST /api/moves`, `GET /api/videos/{id}/moves`, `GET /api/moves/{id}`,
  `PUT /api/moves/{id}`, `DELETE /api/moves/{id}`.
- Environments: `POST /api/environments`, `GET /api/moves/{id}/environment`,
  `PUT /api/environments/{id}`.
- Outcomes: `POST /api/outcomes`, `GET /api/moves/{id}/outcome`, `PUT /api/outcomes/{id}`.
- Frame tags: `POST /api/frame-tags`, `GET /api/moves/{id}/frame-tags`,
  `DELETE /api/frame-tags/{id}`.

Validation is hand-rolled: each handler checks values against the `models.py`
constants and raises `HTTPException` 400/404/409.

### Flow summary

```
browser --(pose CSV as form field)--> /api/videos/register --> data/*.csv  (ephemeral)
browser --(labels)-----------------> /api/moves|environments|outcomes|frame-tags --> labels.db (ephemeral)
browser --(export)-----------------> /api/videos/{id}/export --> data/exports/*.csv (ephemeral)
                                                              \-> GitHub contents API (only durable copy)
```

---

## 2. Per-file changes

| File | Change |
|---|---|
| `src/labeling/models.py` | Rewritten. `user_id` on every entity. New `Hold` dataclass (normalized bbox + `source`). `Environment` replaced by four optional slots (`start_left`, `start_right`, `end`, `foot`), each with `_hold_id`, `_hold_type`, `_hold_quality`. `Move` drops `timing`, `dyno_style`, `contextual_data`, `tags`; gains `confidence`. `Outcome` drops `foot_cut`. `FrameTag` drops `traction_source`, `traction_direction`. `MOVE_TAGS` gains `technical`, `tension`. `TIMINGS`, `DYNO_STYLES`, `TRACTION_SOURCES` removed. New `HOLD_SLOTS`, `HOLD_SOURCES`. |
| `src/labeling/database.py` | Rewritten for psycopg v3. `ConnectionPool(min_size=1, max_size=5)` over `DATABASE_URL`, `dict_row` factory. `?` → `%s`, `cursor.lastrowid` → `RETURNING id`, `json.dumps`/`json.loads` into TEXT → `Jsonb` into `jsonb`, ISO-string datetimes → native `timestamptz`. `init()`/`_apply_schema()` replaced by `check_schema()` (verifies version, raises `SchemaNotApplied`) and `apply_schema_sql()` (runs the migration file, for tests). Every read/update/delete takes `user_id` and filters on it. New: `set_video_r2_keys()`, `get_videos_with_exports()`, hold CRUD. |
| `src/labeling/exporter.py` | Rewritten. `export_video(video_id, user_id)` streams the pose CSV from R2, joins labels, writes the result back to R2 and records `r2_export_key`. `delete_video` removed. Emits per-slot hold columns including a denormalized `{slot}_hold_bbox` so the export stands alone as a dataset. |
| `src/labeling/data_sync.py` | **Deleted.** GitHub sync retired. |
| `src/labeling/__init__.py` | Exports updated for the new models and constants. |
| `src/storage/r2.py` | **New.** boto3 against `https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com` (region `auto`, SigV4). `put_object`, `get_object_stream`, `object_exists`, `presigned_put_url`, `presigned_get_url`, plus `video_key`/`pose_csv_key`/`export_key`. Client built lazily and cached so the module imports without credentials. `R2_ENDPOINT_URL` overrides the endpoint for local MinIO/stub work. |
| `src/storage/__init__.py` | **New.** Re-exports the R2 surface. |
| `src/web/auth.py` | **New.** `get_current_user_id` FastAPI dependency: verifies the bearer token against `SUPABASE_JWT_SECRET` (HS256, `aud=authenticated`, requires `exp` and `sub`) and returns `sub`. Distinct 401s for missing / expired / invalid; 500 when the secret is unset. |
| `src/web/api.py` | Rewritten, version 3.0.0. See §7 for the endpoint-by-endpoint contract. Removed `POST /api/videos/upload`, the `/videos` static mount, `process_video()` and the `subprocess` call into `main.py` — all of which used the ephemeral disk. Added health, exports listing and hold endpoints. Lazy `get_db()`/`get_exporter()`; lifespan handler closes the pool only when this module opened it. |
| `supabase/migrations/<ts>_schema_v3.sql` | **New.** Full v3 DDL + RLS. |
| `tests/conftest.py`, `tests/test_database_v3.py`, `tests/test_api_scoping.py` | **New.** 61 tests. |
| `scripts/smoke_test.py` | **New.** End-to-end check against a base URL. |
| `test_backend.py` | **Deleted.** Imported `TRACTION_SOURCES` and the SQLite `Database` signature; both gone. Superseded by `tests/`. |
| `requirements.txt` | Added `psycopg[binary]`, `psycopg-pool`, `boto3`, `PyJWT`. |
| `README.md` (backend) | Rewritten for v3. The previous version was stale well before this change — it still documented `move_type`, `contextual_data` and SQLite. |
| `../../README.md` (root) | Data-pipeline section now describes Supabase + R2; `GITHUB_TOKEN`/`DATA_REPO` and the SQLite tree removed. |
| `.env.example` | **New.** |

---

## 3. Every default taken

Decisions made without asking, per the brief's instruction to use defaults and continue:

1. **`Database` interface is not byte-for-byte identical.** Step 2 asked to keep it identical; step 6 required every query to filter by `user_id`. Those conflict. Method names, return types and call style are unchanged, but reads/updates/deletes take an extra `user_id` argument. This is the minimum change that satisfies step 6.
2. **`init()` → `check_schema()`.** The app no longer creates tables; the migration is the single source of truth. `apply_schema_sql()` exists so tests can build a fresh schema without the Supabase CLI.
3. **"Remove `timing`" read as the `timings` config key.** `MOVE_TAGS` never contained a `timing` entry — `timing` was a separate `Move` column with its own `TIMINGS` list. Since the v3 `moves` table specified in step 3 has no `timing` column, the `timing` field, the `TIMINGS` constant and the `timings` key in `/api/config` were all removed. `technical` and `tension` were added to `MOVE_TAGS` as asked.
4. **`dyno_style`, `contextual_data`, `tags` (on moves), `foot_cut`, `traction_source`, `traction_direction` dropped.** None appear in the step 3 column lists. They are gone from the models, the API and the export.
5. **`confidence` exists on both `moves` and `outcomes`.** The step 3 spec lists it on both. Implemented as specified; exported as `move_confidence` and `outcome_confidence` to keep the two distinguishable. Flagging in case only one was intended.
6. **`r2_video_key` is nullable.** Only `r2_export_key` was marked nullable in the brief, but the direct-upload flow means no video key exists at register time. `r2_pose_csv_key` is likewise nullable for the window between the row insert and the R2 put.
7. **Hold endpoints added.** `environments` references `holds`, but no endpoint existed to create one, which would have made the slots unusable. Added `POST /api/holds`, `GET /api/videos/{id}/holds`, `DELETE /api/holds/{id}`.
8. **`POST /api/videos/upload` removed.** It saved the video to local disk and shelled out to `main.py` for pose extraction — exactly the ephemeral-disk dependency this work removes. The client-side path (`register` + presigned upload) replaces it. **This is a breaking removal; see §7.**
9. **`/api/health` and `/` are unauthenticated.** Step 6 says every endpoint requires a JWT, but a health check Railway cannot call is useless. Only these two are open, and neither touches user data. `/api/config` does require a token, as instructed.
10. **404, not 403, for another user's resource.** Prevents id enumeration.
11. **60MB limit enforced twice** — in middleware on `Content-Length` (before the body is buffered) and again on the decoded CSV, since `Content-Length` is client-supplied.
12. **`register` takes JSON, not multipart form.** The old endpoint used `Form(...)` fields. The body is now a single JSON document. **Breaking; see §7.**
13. **Foreign keys use `ON DELETE CASCADE`** (from `videos`/`moves`) and `ON DELETE SET NULL` (hold references from `environments`), so deleting a hold blanks the slot rather than failing.
14. **R2 CORS origin is `*`.** Step 4 said to use the frontend origins "found in the existing CORS config in api.py" — that config is `allow_origins=["*"]`. No specific origin exists anywhere in the repo. See §6 for the JSON and a recommendation to narrow it.
15. **Tests ran against a local Postgres 16.** No `DATABASE_URL` exists, so "the real DATABASE_URL" was unavailable. The same migration file was applied to a local scratch database with `auth.uid()`/`auth.role()` stubbed.
16. **The smoke test ran against a local instance of the real app**, not the deployment, for the same reason. See §5.
17. **Root `README.md` was edited** despite "work only in `data_collection/backend`", because step 5 explicitly said to remove `GITHUB_TOKEN`/`DATA_REPO` from docs and those references lived there. The frontend was not touched.

---

## 4. Test output

`pytest tests/ -q`, against Postgres 16 with `TEST_DATABASE_URL` pointed at a local scratch database:

```
.............................................................            [100%]
61 passed in 1.76s
```

- `tests/test_database_v3.py` — 33 tests: schema version, table presence, RLS enabled everywhere, four policies per data table, identity keys, jsonb round-trips (verified with a `@>` containment query, so a JSON-string-in-text column would fail), bbox and `source` CHECK constraints, all four hold slots, the optional foot slot, one-environment-per-move uniqueness, cascade on move delete, and user scoping on every read/update/delete.
- `tests/test_api_scoping.py` — 28 tests: unauthenticated health, 401 on missing/garbage/wrong-secret/expired tokens, register writing the pose CSV to R2, 413 on oversized bodies, presigned upload-url and confirm-upload (including refusal of a foreign key prefix), export contents, the 307 redirect, `/api/exports/mine`, and a second user getting 404 on every resource.

**One real bug was found by the suite and fixed:** the app's shutdown hook closed whatever `Database` was on the module global, including one injected by a caller. It now tracks whether it opened the pool itself (`_db_owned`).

---

## 5. Smoke test output

Could not be run against the deployment — Railway has no linked project (§1). Run instead against the real application started locally (`uvicorn src.web.api:app`) on Postgres 16 with a local S3 stub standing in for R2 via `R2_ENDPOINT_URL`. Tokens minted from a local `SUPABASE_JWT_SECRET` for two fixed throwaway uuids.

```
Smoke test against http://127.0.0.1:8099

health
  PASS  GET /api/health is 200
  PASS  database reachable
  PASS  schema version is 3
  PASS  R2 configured

config
  PASS  GET /api/config is 200
  PASS  move_tags contains 'technical'
  PASS  move_tags contains 'tension'
  PASS  'timings' key is gone
  PASS  GET /api/config without a token is 401

register
  PASS  POST /api/videos/register is 201
  PASS  pose CSV key recorded
  PASS  fps round-tripped
  PASS  total_frames round-tripped

labels
  PASS  POST /api/holds is 201
  PASS  POST /api/moves is 201
  PASS  POST /api/environments is 201
  PASS  foot slot left empty
  PASS  POST /api/outcomes is 201
  PASS  POST /api/frame-tags is 201

export
  PASS  POST export is 200
  PASS  export key returned
  PASS  GET /api/exports/mine is 200
  PASS  export appears in /api/exports/mine
  PASS  export download redirects (307)
  PASS  presigned URL returned
  PASS  export object fetched from R2
  PASS  export header carries raw pose columns
  PASS  export header carries label columns
  PASS  labels joined onto frames

isolation (second user)
  PASS  other user GET video is 404
  PASS  other user GET moves is 404
  PASS  other user GET move is 404
  PASS  other user export is 404
  PASS  other user download is 404
  PASS  other user's export list excludes it

35 passed, 0 failed
```

The export object produced, fetched back out of storage:

```
frame_number,timestamp_ms,left_elbow_angle,right_elbow_angle,move_id,approach,size,move_tags,
form_quality,effort_level,move_confidence,wall_angle,start_left_hold_id,start_left_hold_type,
start_left_hold_quality,start_left_hold_bbox,...,foot_hold_bbox,result,reach_detail,
outcome_confidence,tag_types,tag_levels,tag_locations,tag_sides,tag_notes

2,66,140.1,139.9,2,dynamic,large,dyno|tension,4,8,high,steep,1,jug,incut,"0.42,0.33,0.06,0.05",
,,,,1,jug,incut,"0.42,0.33,0.06,0.05",,,,,success,reached_controlled,high,sharp_pain,6,
left_shoulder,left,smoke test tag
```

---

## 6. R2 bucket and CORS — applied

Done; kept for reference and for rebuilding the bucket elsewhere. The bucket
`dynalytix-climbing` and its CORS rule are live (see the fifth update).
`wrangler` was never needed: R2 implements the S3 API, and the dashboard handles
CORS.

**To recreate with wrangler:**
```bash
npm install -g wrangler
wrangler login
wrangler r2 bucket create <bucket-name>
wrangler r2 bucket cors put <bucket-name> --file r2-cors.json
```

**Or paste this in the Cloudflare dashboard** (R2 → your bucket → Settings → CORS Policy). This is `r2-cors.json`, and it is what is currently applied:

```json
[
  {
    "AllowedOrigins": ["*"],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedHeaders": ["Content-Type", "Content-Length"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

`AllowedOrigins` is `*` because that is what `api.py`'s CORS config says and no
specific frontend origin appears anywhere in the repo. **Narrow it** to the
deployed frontend origin once you know it, e.g.:

```json
"AllowedOrigins": ["https://your-frontend.vercel.app", "http://localhost:5173"]
```

The browser PUTs with a `Content-Type` header that must match the one passed to
`/api/videos/{id}/upload-url`, or the presigned signature will not validate.

---

## 7. Frontend API contract changes (for Terminal C)

**Every** `/api` request except `/api/health` now needs:

```
Authorization: Bearer <supabase access token>
```

Get it from the existing Supabase client: `(await supabase.auth.getSession()).data.session.access_token`. Without it: `401`.

### `POST /api/videos/register` — changed shape

*Old* — multipart form:
```
FormData: filename, fps, total_frames, duration_ms, csv_data
→ 201 { id, filename, path, csv_path, fps, total_frames, duration_ms, uploaded_at }
```

*New* — JSON body:
```jsonc
POST /api/videos/register
{ "filename": "climb.mp4", "fps": 30.0, "total_frames": 900,
  "duration_ms": 30000.0, "csv_data": "<pose csv text>" }

→ 201 { "id": 1, "filename": "climb.mp4", "fps": 30.0, "total_frames": 900,
        "duration_ms": 30000.0, "r2_video_key": null,
        "r2_pose_csv_key": "pose/<user_id>/1.csv", "r2_export_key": null,
        "uploaded_at": "..." }
→ 413 if the body exceeds 60MB
```
`path` and `csv_path` are **gone**; `r2_*` keys replace them.

### `POST /api/videos/upload` — **removed**

The server no longer accepts video files or runs pose extraction. Use the
three-step flow below.

### Direct video upload — new

```jsonc
POST /api/videos/{id}/upload-url
{ "content_type": "video/mp4" }
→ 200 { "url": "<presigned PUT>", "key": "videos/<user_id>/<id>/climb.mp4",
        "expires_in": 3600 }

// then, from the browser, straight to R2:
PUT <url>   with header Content-Type: video/mp4   body = the file

POST /api/videos/{id}/confirm-upload
{ "key": "videos/<user_id>/<id>/climb.mp4" }   // or {} to use the default
→ 200 <video object>
→ 400 if the key is outside your own videos/{user_id}/ prefix
```

### `POST /api/videos/{id}/export` — changed

*Old:* `?delete_video=true` supported → `{ "path": "data/exports/...csv", "video_deleted": false }`
*New:* no query params → `{ "video_id": 1, "r2_export_key": "exports/<user_id>/1_labeled.csv" }`

### `GET /api/videos/{id}/export/download` — changed

*Old:* streamed the file body.
*New:* `307` redirect to a presigned R2 URL. Let the browser follow it (`fetch` follows by default; for a save-as, use `window.location = url` or an `<a>`).

### `GET /api/videos/{id}/csv` — changed

Same change: now a `307` to a presigned URL rather than a streamed body.

### `GET /api/exports/mine` — new

```jsonc
→ 200 [ { "video_id": 1, "filename": "climb.mp4",
          "r2_export_key": "exports/<user_id>/1_labeled.csv",
          "uploaded_at": "..." } ]
```

### Holds — new

```jsonc
POST /api/holds
{ "video_id": 1, "bbox_x": 0.42, "bbox_y": 0.33, "bbox_w": 0.06, "bbox_h": 0.05,
  "source": "manual" }          // "manual" | "detected"; bbox normalized 0-1
→ 201 { "id": 1, "video_id": 1, "bbox_x": 0.42, ..., "created_at": "..." }

GET    /api/videos/{id}/holds → 200 [ ... ]
DELETE /api/holds/{id}        → 204
```

### `POST /api/moves` / `PUT /api/moves/{id}` — changed fields

Removed from both request and response: `timing`, `dyno_style`, `contextual_data`, `tags`.
Added: `confidence` (`"low" | "med" | "high" | null`).
`move_tags` now accepts `technical` and `tension`.

```jsonc
{ "video_id": 1, "frame_start": 150, "frame_end": 200,
  "timestamp_start_ms": 5000.0, "timestamp_end_ms": 6666.7,
  "approach": "dynamic", "size": "large",
  "move_tags": ["dyno", "tension"],
  "form_quality": 4, "effort_level": 7,
  "confidence": "high", "description": "..." }
```

### `POST /api/environments` / `PUT /api/environments/{id}` — restructured

*Old:*
```jsonc
{ "move_id": 1, "wall_angle": "steep",
  "hold_type_reaching": "jug", "hold_type_non_reaching": "pinch",
  "hold_quality": ["incut"] }
```

*New* — four named slots, each fully optional:
```jsonc
{ "move_id": 1, "wall_angle": "steep",
  "start_left":  { "hold_id": 1, "hold_type": "jug",   "hold_quality": ["incut"] },
  "start_right": { "hold_id": 2, "hold_type": "pinch", "hold_quality": ["small"] },
  "end":         { "hold_id": 3, "hold_type": "jug",   "hold_quality": [] },
  "foot":        { "hold_id": 4, "hold_type": "jug",   "hold_quality": [] }
}
```
Omit a slot entirely, or send `{}`, to leave it empty — that is how no-hands,
one-hand and no-feet moves are expressed. `hold_id` must reference a hold you
own or the request 404s. The response echoes the same four-slot shape.

### `POST /api/outcomes` / `PUT /api/outcomes/{id}` — changed

`foot_cut` is **removed** from request and response. `confidence` is now nullable.

### `POST /api/frame-tags` — changed

`traction_source` and `traction_direction` are **removed** from request and response.

### `GET /api/config` — changed

Removed keys: `timings`, `dyno_styles`, `traction_sources`.
Added keys: `hold_slots` (`["start_left","start_right","end","foot"]`), `hold_sources` (`["detected","manual"]`).
`move_tags` gains `technical` and `tension`.
**Now requires a token.**

### New status codes to handle

`401` (no/expired token — refresh the session), `413` (pose CSV over 60MB),
`503` (object storage unavailable), `307` (follow the redirect).

---

## 8. What could not be verified, and why

| Step | Status | Why |
|---|---|---|
| 3 — `supabase db push` | **DONE** | Applied to the new dedicated project `dynalytix-climbing`. |
| 3 — verify tables via psql against `DATABASE_URL` | **DONE** | Against the live database: 7 tables, RLS on all, 4 policies each, `schema_version = 3`. |
| 4 — R2 bucket + CORS | **DONE** | Bucket and object-scoped token created; 10/10 object checks pass; presigned PUT/GET confirmed with curl; CORS applied, confirmed in the dashboard and by a live preflight. |
| 5 — `railway variables --unset GITHUB_TOKEN DATA_REPO` | **Deferred on purpose** | Left set so the deployed old build's GitHub sync keeps working until cutover. Removing them is the first step after the merge (section 9). |
| 7 — tests against the real `DATABASE_URL` | **DONE** | 61 passed against the live Supabase database. |
| 7 — R2 tests against the real bucket | **DONE** | `verify_r2.py` runs against the real bucket: 10 passed, 0 failed. The pytest fixture still uses the in-memory fake unless the bucket answers. |
| 8 — `railway variables --set` | **DONE** | All 8 v3 variables set on `adorable-integrity`, verified by length, no values printed. |
| 8 — `railway up` + health check on the deployment | **Held by choice** | Not blocked — staged and ready. Held because deploying breaks `collect.dynalytix.net` until the frontend ships the §7 changes. |
| 9 — smoke test against the deployed URL | **Pending the deploy** | Already passes 35/35 against the real app locally with real ES256 tokens and the live Supabase database. Re-run against the deployed URL at cutover, when R2 will be real rather than stubbed. |

Nothing about the application code is unverified — every module is exercised by
the 61-test suite, the 35-check smoke run and the 10-check R2 run. Supabase and
R2 are verified against the real services. The only untested path is the
deployed container itself, which is held deliberately, not blocked.

---

## 9. Cutover checklist

R2, Supabase and the Railway variables are all done and verified. What is left
is one coordinated release.

### Step 0 — apply migrations FIRST (added after the first attempt failed)

**Skipping this broke the first cutover.** The code deployed while
`20260913180000_add_video_dimensions.sql` had never reached Supabase, so every
`POST /api/videos/register` returned 500 with
`column "width" of relation "videos" does not exist`. See the Sixth update above.

`apply_schema_sql()` is **test-only** and never runs against production.

```bash
cd data_collection/backend
# DATABASE_URL is the TRANSACTION pooler (6543) and has no prepared-statement
# support; the CLI dies on it with SQLSTATE 42P05. Use the SESSION pooler, 5432.
SESSION_DSN=$(python3 -c "
import os, urllib.parse as u
p = u.urlparse(os.environ['DATABASE_URL'])
print(u.urlunparse(p._replace(netloc=f'{p.username}:{u.quote(p.password, safe=\"\")}@{p.hostname}:5432')))
")
supabase db push --db-url "$SESSION_DSN" --dry-run
supabase db push --db-url "$SESSION_DSN"
supabase migration list --db-url "$SESSION_DSN"
```

**STOP if `migration list` shows any local migration without a matching Remote
entry, or if a second `--dry-run` does not say "Remote database is up to date."**
Run it from a worktree that actually has `supabase/migrations/`.

### The one thing that governs everything

`adorable-integrity` (backend) **and** `Data_collection_climbing` (frontend) both
auto-deploy from **`main`**, with **Wait for CI off**. A push to `main` deploys
both within seconds. There is no staging gate.

Therefore: **do not merge this branch on its own.** Merge it together with
Terminal C's frontend work, in a single merge to `main`.

### Before the merge

- [ ] Terminal C's frontend changes are complete against the §7 contract:
      bearer token on every `/api` call, JSON body for `/api/videos/register`,
      the three-step presigned upload flow, the four-slot environment shape,
      `foot_cut` / `timing` / `dyno_style` / `traction_*` removed, and 307
      redirects followed for CSV and export downloads.
- [ ] Frontend `.env` points `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` at
      the **new** project `nbqtgknayvsjkevaoeef`, not the old shared
      `login_system` project. The `VITE_API_URL` service variable on
      `Data_collection_climbing` still points at the backend and needs no change.
- [ ] Someone can sign in on the new Supabase project — it has no users yet
      beyond the two `smoke-test-*@dynalytix.test` accounts.
- [ ] Decide about the old data. Labels in the old SQLite on the Railway disk
      are already gone on every redeploy; exports live in the `dynalytix-data`
      GitHub repo. Nothing is migrated — schema v3 starts empty by design.

### The merge

- [ ] Merge the backend branch and the frontend branch to `main` **in one merge**.
      Both services rebuild automatically. Watch both in the Railway dashboard.

### Immediately after

- [ ] Unset the retired variables (left in place until now so the old build's
      GitHub sync kept working):
      ```bash
      cd data_collection/backend
      railway variables delete GITHUB_TOKEN --service adorable-integrity --environment production
      railway variables delete DATA_REPO   --service adorable-integrity --environment production
      ```
      Each deletion triggers a redeploy; add `--skip-deploys` to batch them and
      redeploy once.
- [ ] Health check:
      ```bash
      curl https://adorable-integrity-production.up.railway.app/api/health
      # expect {"status":"ok","database":"ok","r2":"ok","schema_version":3}
      ```
      `r2` must read `ok`, not `not configured`. `/api/config` now requires a
      bearer token and returns 401 without one — that is correct behaviour.
- [ ] Smoke test against the deployment, with R2 real rather than stubbed:
      ```bash
      set -a && . ./.env && set +a
      python scripts/smoke_test.py --url https://adorable-integrity-production.up.railway.app
      ```
      It creates two throwaway users through the auth admin API, so it exercises
      the project's real ES256 signing keys. Expect 35 passed, 0 failed.
- [ ] Truncate the tables afterwards so the smoke test's rows do not pollute the
      first real session:
      ```bash
      psql -d "$DATABASE_URL" -c "TRUNCATE frame_tags, outcomes, environments, moves, holds, videos RESTART IDENTITY CASCADE;"
      ```
- [ ] Click through one real labelling session on `collect.dynalytix.net`:
      upload a video, mark a hold, label a move with all three lenses, export,
      download.

### Worth doing soon after

- [ ] **Narrow CORS.** Both `api.py` (`allow_origins=["*"]`) and the bucket rule
      are wide open. Now that the frontend origin is known, tighten both to
      `["https://collect.dynalytix.net", "http://localhost:5173"]`.
- [ ] **Consider turning off auto-deploy from `main`**, or pointing production at
      a release branch. With Wait for CI off, any push to `main` currently ships
      straight to a live service.
- [ ] Delete the two `smoke-test-*@dynalytix.test` users if you would rather not
      keep them (Supabase → Authentication → Users).
- [ ] Retire the old storage: `data/labels.db`, `data/*.csv`, `data/exports/`,
      `videos/`, and the `dynalytix-data` GitHub repo.
- [ ] Rotate the R2 token if you would rather it had never passed through an
      agent session; `.env` is the only place it lives locally.

### If it goes wrong

Railway keeps previous deployments: open the service → Deployments → pick the
`7be1840` build → Redeploy. That restores the old backend. The Supabase project
and R2 bucket are separate from it and are unaffected by a rollback.


---

## §10 Dataset A (runbook-w1-backend) — 2026-09-22

Branch `feat/dataset-a-assignments`. Backend section of
`claude-ops/runbook-w1-backend.md` only; the Frontend section is a separate
lane and builds against `API_DATASET_A.md` (every new/changed endpoint with
request/response JSON and error codes). Per MAILBOX rule 6 this branch merges
to `main` **only together with** its frontend changes.

### 10.1 Per-file changes

| File | Change |
|---|---|
| `supabase/migrations/20260922120000_dataset_a.sql` | **New, additive only.** (Revised after review, see §10.7.) `videos` + `dataset` ('A'\|'B', default 'B'), `prep_status` ('draft'\|'ready'\|'closed', default 'draft'), `route_grade`, `wall_type`, `climber_experience`, `climber_height_cm`, `climber_ape_index_cm`, `camera_angle`, `gym`, `notes`. New `rater_profiles` (user_id PK, display_name, tier, years_climbing, coaching_cert, highest_grade, research_background, validation_note, **is_admin**, created_at). New `video_assignments` (id, video_id FK cascade, rater_user_id, cohort, status, assigned_at, completed_at, UNIQUE(video_id, rater_user_id)). `environments`/`outcomes`/`frame_tags` + `taxonomy_version text NOT NULL DEFAULT 'pre-3.1'` and `is_gold boolean NOT NULL DEFAULT false`. `environments`/`outcomes` UNIQUE(move_id) → UNIQUE(move_id, user_id). SQL helpers `public.is_admin()`, `public.has_assignment(video_id)`, `public.video_is_draft(video_id)` (SECURITY DEFINER) and RLS policies on every table mirroring the API rules. `schema_version` is **not** bumped (see §10.2). Does not touch the `pose_*` columns the Worker lane adds. |
| `src/labeling/models.py` | `TAXONOMY_VERSION = "3.1.0"`; constants for datasets, prep statuses, cohorts, assignment statuses, tiers; `Video` gains the new columns + `is_locked()`; `Environment`/`Outcome`/`FrameTag` gain `taxonomy_version`, `is_gold`; new `RaterProfile`, `VideoAssignment`. |
| `src/labeling/database.py` | Insert/update stamp the new columns. New unscoped `*_any` accessors (`get_video_any`, `get_holds_for_video_any`, `get_moves_for_video_any`, `update_hold_any`, `delete_hold_any`, `update_move_any`, `delete_move_any`, `get_hold_any`, `get_move_any`) for use only after the API's access check; `list_videos_admin`, `update_video_fields`, `get_videos_for_export`; cross-rater readers `get_environments_for_move_all` etc. for exports; profile CRUD (`create_rater_profile`, `get_rater_profile`, `is_admin`, `list_rater_profiles`, `update_rater_profile` (admin fields), `update_rater_profile_self` (rater fields)); assignment CRUD. Every existing per-user label query already filtered by `user_id`; confirmed none assumed one-env-per-move without it. `apply_schema_sql()` already applied every `supabase/migrations/*.sql` in filename order, so the new file is picked up by tests unchanged. |
| `src/web/api.py` | Access model: `_require_video_access` → `VideoAccess(role = owner\|rater\|admin)`; `_require_structure_write` (holds/moves: owner while draft, admin always, rater never → 403); `_require_label_write` (rater: assignment open and video not closed; first write flips `assigned → in_progress`). All hold/move/environment/outcome/frame-tag routes go through these. Hold slots must reference holds on the move's own video (400). New: `DELETE /api/environments/{id}`, `DELETE /api/outcomes/{id}`, `GET/POST/PUT /api/me/profile`, `GET /api/me/assignments`, `POST /api/assignments/{id}/start`, `POST /api/assignments/{id}/complete` (422 + `missing[]`), `GET /api/admin/videos`, `PUT /api/admin/videos/{id}/metadata`, `POST /api/admin/videos/{id}/ready|close|reopen`, `GET/POST/DELETE /api/admin/assignments`, `GET /api/admin/raters`, `PUT /api/admin/raters/{user_id}`, `GET /api/admin/export/long`, `GET /api/admin/export/full`. `GET /api/config` gains `version`. `VideoResponse` gains `owner_user_id`, `dataset`, `prep_status`, metadata, `access_role`. App version 3.1.0. |
| `src/labeling/exporter.py` | `Exporter._build_frame_labels` takes an explicit move list and hold lookup (default behaviour unchanged). New `AdminExporter`: `long_rows/long_csv` (one row per video × move × rater × lens × field, sorted) and `full_rows/full_csv` (per-video export shape across every video × rater). |
| `src/labeling/__init__.py` | Re-exports the new models/constants. |
| `scripts/snapshot_to_r2.py` | **New.** `COPY` every `public` base table to CSV → `snapshots/YYYY-MM-DD/<table>.csv` via `src/storage/r2`. `--dry-run`, `--date`. Exit 1 if any table failed (after trying all), 2 if env is missing. |
| `scripts/railway.cron.md` | **New.** Scheduling as a Railway cron service (`python scripts/snapshot_to_r2.py`, `0 8 * * *` UTC), verification, restore, retention, Modal alternative. |
| `scripts/irr_alpha.py` | **New.** Reads the long CSV, pivots (video, move) × rater per field, Krippendorff's alpha (ordinal for `form_quality`/`effort_level`, nominal otherwise; frame tags as presence per tag_type), NaN for missing, prints a table, optional `--json`. `pip install krippendorff`. |
| `tests/conftest.py` | `clean_db` truncates `video_assignments`, `rater_profiles` too. The session `db` fixture re-applies `scripts/auth_shim.sql` (idempotent) before the migrations so an older scratch database gains the PostgREST roles. |
| `scripts/auth_shim.sql` | Test fixture only. Now also creates `anon` / `authenticated` (NOLOGIN) and gives them Supabase-like default privileges on `public`, so the migration's GRANT/REVOKE statements resolve and RLS can be exercised as a real non-superuser role. |
| `tests/test_dataset_a.py` | **New, 30 tests** (see §10.4). |
| `tests/test_rls_dataset_a.py` | **New, 7 tests.** Runs statements as `SET ROLE authenticated` / `anon` with `request.jwt.claims` set (what PostgREST does), so the policies and column privileges themselves are under test. |
| `tests/test_snapshot.py`, `tests/test_irr_alpha.py` | **New**, 4 + 3 tests. |
| `API_DATASET_A.md` | **New.** Frontend contract. |

No existing test was changed. `tests/test_api_scoping.py` and
`tests/test_database_v3.py` pass unmodified, which is the evidence that the
Dataset B self-upload flow is untouched.

### 10.2 Defaults taken (runbook said "pick one, document it")

- **Admin flag** = `rater_profiles.is_admin boolean NOT NULL DEFAULT false`, not
  a `users_admin` table. One row per user already exists; the same query that
  gates labeling answers "is this an admin". The API checks it (its DB role
  bypasses RLS, as before); the RLS helper `public.is_admin()` reads the same
  column for direct PostgREST access.
- **`owner_user_id`** is `videos.user_id`, **not renamed**. The whole codebase
  and the v3 RLS policies read `user_id`; the column is commented in SQL and
  surfaced as `owner_user_id` in every `VideoResponse`. No duplicate column.
- **`schema_version` not bumped.** `Database.check_schema()` requires an exact
  match, so a bump would refuse to start the API on a database that has not
  had this migration; the dimensions migration made the same call. Every new
  NOT NULL column carries a DEFAULT so existing rows backfill in place.
- **`taxonomy_version`** = `"3.1.0"` (`TAXONOMY_VERSION` in models.py, `version`
  in `/api/config`), stamped on every insert and re-stamped on every PUT.
  Pre-existing rows backfill to `'pre-3.1'`.
- **Lock semantics.** `ready` and `closed` lock holds and moves for everyone
  but admins, **including the owner**. `closed` additionally blocks rater
  label writes. Owners keep writing their own labels on their own video at any
  status (Dataset B is never closed by anyone but an admin). `POST
  /api/admin/videos/{id}/reopen` (optional in the spec, implemented) returns to
  `draft`.
- **`ready` also sets `dataset = 'A'`**, so the prep flow needs no separate
  call to tag the video.
- **Rater `complete`** requires an environment **and** an outcome by that
  rater on every canonical move; Strategy is the canonical move itself and
  always counts. Frame tags are not required (a move may have none). Failure
  is **422** with `missing: [{move_id, move_index, missing: [...]}]`. `done`
  is final for the rater (further label writes 403); an admin deletes and
  re-creates the assignment to reopen it.
- **Assignment status**: `assigned → in_progress` on the rater's first label
  write or on `POST /api/assignments/{id}/start`; `→ done` on `complete`.
  Deleting an assignment keeps the rater's label rows.
- **No cap on raters per video**: "3" is the study design, enforced by the
  admin, not the API.
- **Long export**: strategy rows are emitted once per rater (identical values
  from the canonical move) so the per-field pivot is rectangular; the set of
  raters on a move is assigned raters ∪ anyone with a label row, falling back
  to the move creator (Dataset B). `frame_tags` lens: one row per tag, `field`
  = tag_type, `value` = `frame:level:side:locations`. `environment` includes
  `{slot}_hold_id` on top of the runbook's "type + quality" so agreement on
  *which* hold was chosen is measurable. Defaults to `dataset=A`.
- **Full export** = the per-video export's frame-level shape (pose columns +
  label columns) for every video × rater, with identity columns in front and
  the pose header unioned across videos. It re-streams every pose CSV from R2
  and repeats frames per rater, so it is large; `?dataset=` / `?video_id=`
  narrow it.
- **Snapshot** is a Railway cron (the Worker runbook's Modal cron had not
  landed when this ran); the script is platform-agnostic and the note explains
  the Modal equivalent. Table list is discovered from `information_schema`, so
  the Worker lane's or any future table is included automatically.
- **Hold slot ids** on an environment must belong to the move's own video
  (400 otherwise). Previously the check was "a hold the caller owns".

### 10.3 What could not be verified, and why

- **RLS against the real Supabase stack.** The policies and column
  privileges ARE now exercised locally as the `authenticated` / `anon` roles
  with `request.jwt.claims` set (`tests/test_rls_dataset_a.py`), which is
  what PostgREST does. What is not exercised is Supabase's own `auth.uid()`
  (the shim reads the same GUC) and its actual default grants; if the
  project's `authenticated` role has grants beyond the defaults, the
  REVOKE/GRANT in the migration still applies on top. One spot-check with
  the anon key after `db push` (§10.5 step 4) closes that gap.
- **`supabase db push`** was not run: no network to the project from this
  machine. The migration applies cleanly on Postgres 16 in the test fixture
  (the file runs after the v3 base and dimensions migration, in order).
- **The nightly cron is not scheduled** — that is a Railway dashboard action
  (§10.5). The script was run only with a mocked `r2.put_object`.
- **`GET /api/admin/export/full` at production scale** (hundreds of MB for
  many videos × 3 raters) was not load-tested.
- **The `krippendorff` package** is not in `requirements.txt` on purpose: it
  is a notebook/CLI dependency, not an API one. `tests/test_irr_alpha.py`
  skips if it is not installed.

### 10.4 Test output

```
$ cd data_collection/backend && TEST_DATABASE_URL=postgresql://root@localhost:5432/dyn_test_a python -m pytest tests/ -q
116 passed
```
(72 before this runbook, all still passing unmodified; +30 `test_dataset_a.py`
(18 functions, one parametrised over the 12 admin routes), +7
`test_rls_dataset_a.py`, +4 `test_snapshot.py`, +3 `test_irr_alpha.py`.)
Also verified: a brand-new database built with `scripts/setup_test_db.sh`
applies all three migrations, applies `20260922120000_dataset_a.sql` a
second time without error, and passes the same 116.

`test_dataset_a.py` covers: profile 404 → 201 → 409 and self-edit cannot
touch tier/is_admin/validation_note; `/api/config` `version`; 403 on all 12
`/api/admin/*` routes for a non-admin and for a user with no profile; admin
tier/validation update; assignment CRUD incl. 409/400/404, queue, admin video
counts; rater reads assigned video/holds/moves/csv and gets 404 on unassigned
ones and in `GET /api/videos`; **rater A cannot see or touch rater B's
environment/outcome/frame_tags on the same move, both can hold their own**;
rater 403 on every hold/move write; owner locked out of holds/moves at
`ready`, admin edits through, reopen restores; `closed` blocks rater label
writes; `complete` 422 with the exact `missing` list twice, then 200, done is
final, idempotent; `start`; long export columns/row count (2 raters × 3 moves
= 3 × (2 × 22 + 1 + 2) = 141 rows), tiers/cohorts, pipe-delimited values, tag
value format, sort order, determinism, `?video_id=`, `?dataset=all`, and the
CSV fed through `irr_alpha.compute`; full export columns and rows across an
admin-prepped A video and a rater-owned B video; taxonomy_version stamped and
re-stamped on PUT with `pre-3.1` readable; Dataset B defaults; admin metadata
update.

### 10.5 Manual steps for Jolie

1. **Apply the migration** (MAILBOX rule 8) on the **session pooler, port
   5432**, before this branch's code deploys:
   ```bash
   cd data_collection/backend
   supabase db push --db-url "$SESSION_POOLER_URL"     # applies 20260922120000_dataset_a.sql
   supabase migration list --db-url "$SESSION_POOLER_URL"   # must show no pending rows
   ```
   If the Worker lane's `20260922130000_pose_status.sql` is also on the branch
   it applies in the same push, after this one. Both are additive.
2. **Create the first admin** (yourself). Sign in once on the app and create
   a profile (the profile gate), then in the Supabase SQL editor:
   ```sql
   update public.rater_profiles set is_admin = true
   where user_id = '<your auth.users uuid>';
   ```
   (`select id, email from auth.users;` to find it.) Further admins can be
   flagged from the app via `PUT /api/admin/raters/{user_id}` `{"is_admin": true}`.
3. **Schedule the nightly snapshot**: follow `scripts/railway.cron.md`
   (new Railway service from the same repo, root `data_collection/backend`,
   start command `python scripts/snapshot_to_r2.py`, cron `0 8 * * *`,
   reference the API service's `DATABASE_URL` + `R2_*` variables). Run it once
   by hand and check `snapshots/<today>/` in the bucket.
4. **Spot-check RLS** with the anon key once: as rater A, `GET
   /rest/v1/environments?move_id=eq.<id>` must not return rater B's row, and
   `PATCH /rest/v1/video_assignments?id=eq.<mine>` with `{"status":"done"}`
   must affect 0 rows. (`supabase db push` will also confirm the `anon` /
   `authenticated` roles resolve, which they do on every Supabase project.)
5. **Merge** only together with the frontend lane's branch (rule 6), after
   `supabase migration list` is clean.
6. **IRR**: `GET /api/admin/export/long` (admin token) → `pip install
   krippendorff numpy` → `python scripts/irr_alpha.py dynalytix_long.csv`.

### 10.6 Open questions (for chat, not the Mailbox)

- Should `complete` require at least one frame tag per move, or is "no
  sensation" a valid rating? Currently not required.
- Should a `done` assignment be re-openable by the rater, or only by an admin
  deleting and re-creating it? Currently admin only.
- Retention for `snapshots/`: no lifecycle rule exists yet.

### 10.7 Review fixes (same day, before merge)

Four findings on the migration, fixed in place (the file had never been
pushed), each with a test in `tests/test_rls_dataset_a.py`:

1. **HIGH — `video_assignments_update` was rater-writable.** Via PostgREST a
   rater could `UPDATE video_assignments SET video_id = <any>` and then read
   that video, its holds, moves and pose key, or `SET status = 'done'`
   bypassing `/complete`. Now `USING (public.is_admin()) WITH CHECK
   (public.is_admin())`; INSERT/DELETE were already admin-only. Status
   transitions belong to the API's role. Test:
   `test_rater_cannot_repoint_or_complete_their_assignment`.
2. **MEDIUM — owner could set `prep_status` / `dataset` directly.** Fixed
   with column privileges — but **not** as a bare column `REVOKE`: Postgres
   ignores a column-level REVOKE while the role still holds the table-level
   privilege, and Supabase grants `authenticated` table-level ALL on every
   public table by default (verified on Postgres 16 with
   `has_column_privilege`). The migration therefore does `REVOKE UPDATE ON
   videos FROM authenticated, anon` and `GRANT UPDATE (<every column except
   id, user_id, uploaded_at, dataset, prep_status>) TO authenticated`. The
   API's role (postgres / service, RLS-bypassing) is unaffected — the test
   asserts that the API path still flips `prep_status`. Neither the frontend
   nor the API updates `videos` through PostgREST, so nothing in use is
   narrowed. A column the Worker lane adds later (`pose_*`) will not be
   updatable by `authenticated`, which is the intended state (the worker
   writes with the service role). Test:
   `test_owner_cannot_change_prep_status_or_dataset_but_can_edit_metadata`.
3. **LOW — a validated rater could not rename themself.** The self-update
   policy required `tier = 'open' AND validation_note IS NULL`. Policies are
   now simply "own row" for INSERT and UPDATE; `tier`, `validation_note`,
   `is_admin` are protected by column privileges (table-level INSERT/UPDATE
   revoked, then `GRANT INSERT (user_id, display_name, years_climbing,
   coaching_cert, highest_grade, research_background, created_at)` and
   `GRANT UPDATE (display_name, years_climbing, coaching_cert,
   highest_grade, research_background)`). A self-insert relies on the column
   defaults. Admin edits to the privileged columns go through
   `PUT /api/admin/raters/{id}`; an admin through PostgREST is bound by the
   same privileges (documented, intentional). Tests:
   `test_validated_rater_can_rename_but_not_promote_themself`,
   `test_self_insert_uses_defaults_and_cannot_name_privileged_columns`.
4. **LOW — `ADD CONSTRAINT` re-run.** Both composite UNIQUE constraints are
   added inside a `DO` block guarded on `pg_constraint`, so a manual re-run of
   the file is a no-op (verified by applying it twice to a fresh database).

Also from the same review, on the frontend half of this branch:

5. `data_collection/frontend/src/App.jsx`: the `onAuthChange` null-session
   branch now calls `resetForSignOut()` and drops `config`, as the sign-out
   button does, so a dead session followed by another user signing in on the
   same tab never keeps user A's moves/holds/labels/profile/queue. Test in
   `App.test.jsx` (fails on the previous code). vitest 104/104, `npm run
   build` and eslint green.

To make the RLS tests possible, `scripts/auth_shim.sql` now creates the
`anon` / `authenticated` roles with Supabase-like default privileges, and the
`db` fixture re-applies the shim (idempotent) so an existing scratch database
does not need rebuilding. **Never apply the shim to the Supabase project.**
