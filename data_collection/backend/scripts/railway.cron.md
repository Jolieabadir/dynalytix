# Nightly snapshot as a Railway cron service

`scripts/snapshot_to_r2.py` dumps every `public` table to
`snapshots/YYYY-MM-DD/<table>.csv` in the R2 bucket. Supabase's free tier
has no point-in-time recovery, so this is the backup. Run it once a day.

## One-time setup (Railway dashboard)

1. In the `adorable-integrity` project, **+ New → GitHub Repo**, pick
   `Jolieabadir/dynalytix`, same branch as the API service (`main`). Name the
   service `snapshot-cron`.
2. **Settings → Source**: set *Root Directory* to `data_collection/backend`
   (same as the API service so the same `requirements.txt` / Dockerfile
   build applies).
3. **Settings → Deploy → Custom Start Command**:

       python scripts/snapshot_to_r2.py

4. **Settings → Deploy → Cron Schedule**:

       0 8 * * *

   (08:00 UTC daily. Railway runs the start command on that schedule and the
   container exits when the script does; the service is not kept running.)
5. **Variables**: reference the API service's variables rather than
   re-entering them. Needed: `DATABASE_URL` (the **session pooler, port
   5432** URL, not the transaction pooler: `COPY` is fine on either, but the
   session pooler matches what the API uses), `R2_ACCOUNT_ID`,
   `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`. Set them with
   `railway variables --set-from-stdin --skip-deploys` or the dashboard's
   *Reference variable* picker. Never paste a secret into a commit or chat.
6. Trigger one run by hand (**Deployments → ⋯ → Run now**) and confirm the
   objects appear in the bucket under `snapshots/<today>/`.

## Verifying

- Logs of a run list every key written and its byte size, then
  `N tables written under snapshots/YYYY-MM-DD/`.
- Exit status 1 with `Snapshot incomplete: <table>: <error>` means at least
  one table failed; the others were still uploaded. Exit 2 means
  `DATABASE_URL` or the `R2_*` variables are missing.
- Local dry run against a scratch database (no upload):

      DATABASE_URL=postgresql://... python scripts/snapshot_to_r2.py --dry-run

## Restoring

Each CSV has a header row and Postgres CSV quoting, so
`\copy public.<table> FROM '<table>.csv' WITH (FORMAT csv, HEADER true)`
in `psql` restores a table. Restore parents before children
(`videos` → `holds`, `moves` → `environments`, `outcomes`, `frame_tags`;
`rater_profiles`, `video_assignments`), and disable identity generation
conflicts with `OVERRIDING SYSTEM VALUE` if ids must be preserved.

## Retention

Nothing prunes old snapshots. Add an R2 lifecycle rule on the
`snapshots/` prefix (e.g. delete after 90 days) in the Cloudflare
dashboard when the bucket starts to grow.

## If the Modal worker lands first

The runbook allows a Modal cron instead. The script has no Railway-specific
code; a Modal function that sets the same environment variables and calls
`scripts.snapshot_to_r2.snapshot(dsn)` on `modal.Cron("0 8 * * *")` is
equivalent. Do not run both.
