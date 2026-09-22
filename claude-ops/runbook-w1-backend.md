# 📊 Runbook — Dataset A: prep/rating split, rater assignments, validated-rater profiles, admin + long-format IRR export

- **Wave:** W1 · **Lane:** Backend · **Feature:** `feat/dataset-a-assignments` · **Mailbox date:** 2026-09-17
- **Priority:** highest in W1 (per Priority-change entry of 2026-09-17). Runs in parallel with the Worker runbook (different tables, different files).

## Purpose

Paper A needs the same video labeled independently by 3 validated raters. The current model (one owner per video, nobody else sees it) cannot do that. Add a prep-pass / rating-pass split with assignments, keep the existing self-upload flow untouched for Dataset B later. **This is the highest-priority runbook. It can run in parallel with the worker runbook (different tables, different files).**

## Design

- **Prep pass** (admin): upload video, draw holds, define canonical moves, fill video metadata, mark **Ready to rate**. Holds and moves lock at that point.
- **Rating pass** (rater): opens an assigned video, sees canonical moves and holds, fills Environment / Strategy / Outcome and frame tags per move. Cannot create, edit, or delete moves or holds. Never sees another rater's labels.
- **Stats stay out of the app.** The app produces a long-format export; Krippendorff's alpha is computed in a notebook.

## Defaults (do not ask)

- Branch `feat/dataset-a-assignments` from main. Merge only as one unit with its frontend changes.
- Raters per video: 3. Admin assigns manually; no auto-assignment.
- Existing self-upload flow stays exactly as is, tagged `dataset = 'B'`. Nothing in this runbook changes it.
- Schema changes via `supabase db push` on the session pooler (5432); `supabase migration list` clean before merge.

## Backend (`data_collection/backend`)

1. **Migration:**
   - `videos`: add `dataset` text not null default 'B' ('A'|'B'), `prep_status` text default 'draft' ('draft'|'ready'|'closed'), `owner_user_id` (rename of current `user_id` semantics: the uploader/prepper). Add metadata: `route_grade` text, `wall_type` text, `climber_experience` text, `climber_height_cm` int, `climber_ape_index_cm` int, `camera_angle` text, `gym` text, `notes` text — all nullable.
   - `video_assignments`: id, video_id, rater_user_id, cohort text ('validated'|'overlap'), status text ('assigned'|'in_progress'|'done'), assigned_at, completed_at. Unique (video_id, rater_user_id).
   - `rater_profiles`: user_id PK, display_name, tier text ('validated'|'open'), years_climbing int, coaching_cert text nullable, highest_grade text, research_background bool, validation_note text (why this rater counts as validated), created_at.
   - `users_admin`: user_id PK (or an `is_admin` bool on rater_profiles — pick one, document it).
   - `environments`, `outcomes`, `frame_tags`: already carry `user_id` (the rater). Add `taxonomy_version` text not null on each, stamped from the config's version at write time. Add a config `version` string to `/api/config`.
   - `moves`: for Dataset A, moves belong to the video (created in prep), not to a rater. Keep `user_id` as creator. Rater label rows reference `move_id`.
   - `is_gold` bool default false on environments/outcomes/frame_tags for adjudicated rows later.
2. **RLS / scoping:**
   - Admin: everything.
   - Rater with an assignment: read the video, its holds, its canonical moves, its pose CSV; read/write only label rows where `user_id = auth.uid()`.
   - Owner of a Dataset B video: unchanged (full access to own video).
   - No rater can read another rater's environment/outcome/frame_tag rows on the same video. Test this explicitly.
3. **Endpoints:**
   - `POST /api/admin/videos/{id}/ready`, `.../close`
   - `POST /api/admin/assignments` (video_id, rater_user_id, cohort), `DELETE /api/admin/assignments/{id}`, `GET /api/admin/assignments?video_id=`
   - `GET /api/admin/raters` (profiles), `PUT /api/admin/raters/{user_id}` (set tier, validation_note)
   - `GET /api/me/assignments` — the rater's queue with status
   - `POST /api/assignments/{id}/complete` — rater marks done; validates every canonical move has all three lenses filled for that rater
   - `GET /api/admin/export/long` — long-format CSV: video_id, dataset, move_id, move_index, rater_user_id, rater_tier, cohort, lens, field, value (multi-select as pipe-delimited), taxonomy_version, is_gold. This is the IRR input.
   - `GET /api/admin/export/full` — everything across users, the same shape as the per-video export.
   - Rater profile is collected at first sign-in: `POST /api/me/profile`; the app blocks labeling until it exists.
4. **Nightly snapshot:** a scheduled job (Modal cron if the worker runbook has landed, else a Railway cron) that dumps every table to R2 at `snapshots/YYYY-MM-DD/*.csv`. Supabase free tier has no point-in-time recovery; this is the backup.

## Frontend (`data_collection/frontend`)

1. **Rater profile gate** on first sign-in: display name, years climbing, highest grade, coaching cert (optional), research background. One screen, saved once.
2. **My queue** view: assigned videos with status; opens the rating view. Dataset B "My videos" stays as is.
3. **Rating view** = the existing labeling UI with Define mode removed and holds/moves read-only. Moves list is the canonical list; each move opens the three-lens form (with hold slots limited to picking from the locked holds) and frame tagging. A "Complete" button calls `/complete` and shows what's missing if validation fails.
4. **Admin view** (only for admins): video list across all users with dataset, prep_status, assignment count; assign raters by picking from the rater list; mark ready/close; export buttons.
5. Prep pass uses the existing upload → holds → define flow plus the metadata form, with a "Mark ready to rate" button.

## Verify

- Backend tests on scratch Postgres: assignment scoping, cross-rater 404, rater cannot mutate moves/holds on a ready video, complete-validation, long export shape.
- Manual: admin preps a video with 3 moves → assigns 2 test raters → each rater labels independently → neither sees the other's labels → long export has 2 × 3 × (fields) rows → a notebook computes alpha on it (include `scripts/irr_alpha.py` using the `krippendorff` package as the reference implementation).

## Done when

Three raters can independently label the same prepped video without seeing each other, and one export produces the table Krippendorff's alpha is computed from.
