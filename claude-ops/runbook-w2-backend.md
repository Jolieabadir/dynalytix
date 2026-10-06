# Runbook W2 — Backend: Single dataset + skeleton removal (with Amendment)

> Ingested from the Dynalytix Mailbox on 2026-10-06.
> Sources: "Runbook — Single dataset (remove Dataset A/B split) + remove skeleton overlay" and
> "Amendment — Single dataset: public-source clips, athletes table, age gate, dormant self-upload, observer-only rating view".
> The Amendment is applied below (Part B). Where they conflict, Part B wins.
> Branch: `feat/single-dataset`. Lane: Backend (covers backend AND frontend; merge as one unit, MAILBOX rule 6).
> Step 0 (per Note "Tag main as pre-scope-flip"): tag `main` as `pre-scope-flip` before anything merges.

## Part A — Original runbook

### Purpose
The study is now one paper with one dataset. Drop the Dataset A / Dataset B split: every video is admin-prepped and rated by validated raters. Most videos get **1 rater** (ML volume); a **random ~25% overlap subset gets 3 raters** (inter-rater reliability, Krippendorff's alpha). In the same branch, remove the skeleton overlay from the labeling UI.

### Defaults (do not ask)
- Branch `feat/single-dataset` from main, own worktree. Merge backend + frontend together, only after tests are green and the migration is pushed (session pooler 5432, `supabase migration list` clean).
- No real study data exists yet. If any `videos` rows have `dataset = 'B'`, list their ids + R2 keys in REPORT.md before the migration runs. Do NOT delete R2 objects.
- Overlap rate: env `IRR_OVERLAP_RATE`, default `0.25`.

### Backend
1. Migration (`<timestamp>_single_dataset.sql`):
   - `videos`: drop `dataset`. Add `irr_overlap` bool not null default false, `irr_overlap_set_by` text nullable ('random' | 'admin_override').
   - `video_assignments`: drop `cohort`.
   - `rater_profiles`: replace `tier` ('validated' | 'open') with `is_validated` bool not null default false. Keep `validation_note`, `bio`, `is_admin`.
   - Remaining access model: admin = everything; rater with an assignment = read video/holds/moves, read/write only own label rows. Raters never see another rater's labels (keep that test).
2. Overlap selection is random, not hand-picked: on `POST /api/admin/videos/{id}/ready`, set `irr_overlap` with probability `IRR_OVERLAP_RATE` using `secrets.SystemRandom`, `irr_overlap_set_by = 'random'`. `PUT /api/admin/videos/{id}/overlap` lets an admin flip it only while the video has zero assignments (`'admin_override'`); 409 otherwise.
3. Assignments: target raters per video = 3 if `irr_overlap` else 1. `POST /api/admin/assignments` drops `cohort`, rejects (409) beyond the target, rejects raters whose `is_validated` is false.
4. *(Superseded by Part B change 1.)*
5. Raters: `PUT /api/admin/raters/{user_id}` sets `is_validated` + `validation_note`. `/api/me/assignments` returns an empty queue with a "pending validation" flag when the profile is not validated.
6. Exports: long export drops `dataset`, `cohort`, `rater_tier`; adds `irr_overlap`. Full export drops `dataset`. `scripts/irr_alpha.py` computes alpha only on rows where `irr_overlap = true` and reports n videos / n moves used.
7. Tests on scratch Postgres (`scripts/setup_test_db.sh`, never the live DB).

### Frontend
1. *(Superseded by Part B change 1: keep self-upload UI behind the flag.)* Remove dataset labels/filters. Upload + prep live in the admin view. Non-admins land on My queue; unvalidated raters see a "waiting for validation" screen after the profile gate.
2. Admin view: per video show overlap flag (with set-by), assignments `n / target`, Overlap toggle disabled once any assignment exists. Rater list shows `is_validated` with a toggle + note. Remove cohort picker and tier select.
3. Remove the skeleton overlay: `SkeletonOverlay` and every render path, the `S` shortcut, the toggle, and the pose-CSV fetch that existed only to draw it. Remove related tests.
4. Remove hold auto-suggest from the rating view (raters pick hold slots manually from the locked holds; pre-fill would bias agreement). If `holdMatching.js` has no remaining caller, leave it and its tests in place, unused, and note it in REPORT.md.
5. Keep: pose status chip in the admin view only; export disabled until pose is done; worker flow untouched.

### Verify
Backend + frontend tests green; build green; lint clean. Scratch-DB walk: prep 4 videos → ready → random overlap → assign 1 / 3 (4th rejected) → independent labeling → long export has `irr_overlap`, no dataset/cohort → `irr_alpha.py` on overlap rows only. No skeleton anywhere; `S` does nothing.

## Part B — Amendment (scope flip, 2026-10-06)

The paper uses **public footage** (IFSC senior bouldering World Cup broadcasts, plus CC-licensed / open research footage). Labels are observer-only. Community uploads become a later open-source project, so self-upload is kept but switched off.

1. **Self-upload behind a flag.** Env `SELF_UPLOAD_ENABLED` (default false), exposed as `self_upload_enabled` in `/api/config`; frontend reads it at runtime. Flag off: upload / confirm / register / holds / moves create-edit are admin-only. Flag on: non-admins may upload their own videos as `source_type = 'community'` with owner-only access. Keep the self-upload UI code; render only when the flag is on. Exports exclude community rows by default (`?include_community=true` to include).
2. **Athletes table.** `athlete_id` uuid PK (pseudonymous), `ifsc_profile_url` (admin-only, never exported), `height_cm`, `height_source` ('ifsc_profile' | 'missing'), `birth_year`, `category` ('men' | 'women'), `created_at`. No name column. Admin-only. `GET/POST /api/admin/athletes`, `PUT /api/admin/athletes/{id}`. Admin UI list + form; athlete picker on the prep form.
3. **Video source fields.** `source_type` not null default 'public_broadcast' ('public_broadcast' | 'cc_license' | 'research_dataset' | 'community'), `source_url`, `clip_start_ms`, `clip_end_ms`, `license`, `event_name`, `event_date`, `athlete_id` FK. Drop `climber_height_cm`, `climber_ape_index_cm`, `climber_experience`, `gym`. Prep form gains these + "Import metadata JSON" (sidecar from `scripts/prepare_clip.py`).
4. **Age gate at mark-ready** (non-community): 422 unless `athlete_id`, `event_date`, `source_type`, `source_url` (or `license` for research_dataset) are set, the athlete has `birth_year`, and `event_date.year - birth_year >= 19` (conservative: guarantees 18+ without birth dates).
5. **Observer-only rating view.** Hide frame tagging (sensation) and `effort_level` from raters; keep tables/columns; `/complete` must not require them. (Pending Taylor sign-off; reversible UI hide.)
6. **Exports** add `athlete_id`, `height_cm`, `height_source`, `source_type`, `source_url`, `clip_start_ms`, `clip_end_ms`, `event_name`, `event_date`. Never `ifsc_profile_url`.

Tests: flag off → non-admin upload 403; flag on → community upload works and is excluded from default export; athlete endpoints admin-only; ready blocked for missing athlete / birth year / under-age; dropped columns gone; complete passes without sensation/effort; export columns present and no profile URL.

Manual steps for Jolie: add athletes from IFSC profiles; leave `SELF_UPLOAD_ENABLED` unset.
