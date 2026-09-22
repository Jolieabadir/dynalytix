# ⚙️ Runbook — Server-side async pose extraction on Modal (replace browser extractor)

- **Wave:** W1 · **Lane:** Worker · **Feature:** `feat/server-pose-worker` · **Mailbox date:** 2026-09-17
- Runs in parallel with the Backend (Dataset A) runbook; that runbook has priority if only one session runs.

## Purpose

Move pose extraction from the browser to an async server-side worker. Labeling must work the instant a video is picked; the pose CSV arrives later. This ends the client-side speed problem outright (labelers never wait on extraction), removes every browser edge case (HEVC, tab throttling, GPU fallback, singleton timestamp bug), and lets the worker run the FULL MediaPipe model at zero client cost. iPhone is the primary client, so browser extraction is not an option.

## Decisions (defaults — do not ask)

- Worker platform: **Modal** (serverless, per-second GPU billing, scales to zero). T4 GPU. ~$0.01–0.02 per 2-min clip.
- Model: **MediaPipe Tasks PoseLandmarker, FULL variant, VIDEO mode**, Python. Keeps the CSV contract and holdMatching.js untouched. RTMPose whole-body is a later worker-only swap.
- Frame rate: process every frame at the source fps. (30fps is the recommended capture setting for labelers; 60 still works.)
- Zero-wait start: Define mode plays the local `File` via object URL immediately (`playsInline`); upload runs in the background.
- Branch: `feat/server-pose-worker` from main. **Do not merge until the Modal app is deployed and reachable from Railway** — merging auto-deploys both services.

## Backend (`data_collection/backend`)

1. Migration: add to `videos`: `pose_status` text default 'pending' ('pending'|'processing'|'done'|'failed'), `pose_error` text nullable, `pose_started_at`, `pose_finished_at`. Apply with `supabase db push` via the **session pooler (5432)** — see runbook step 0 in REPORT.md. Verify with `supabase migration list`.
2. Register no longer accepts `csv_data`. Flow: `upload-url` → client PUTs video to R2 → `confirm-upload` → backend enqueues a pose job (POST to the Modal web endpoint with a shared secret). Add `GET /api/videos/{id}/status` returning pose fields. Export returns 409 with a clear message while `pose_status != done`.
3. Secrets on Railway: `MODAL_ENDPOINT_URL`, `MODAL_WEBHOOK_SECRET`. Set via `railway variables --set-from-stdin --skip-deploys`, never echoed.

## Worker (`data_collection/worker`, new Modal app)

1. `extract_pose(video_id, user_id, r2_key)`: download video from R2 → `ffprobe` for fps, width, height, duration, frame count (write these to the `videos` row) → `ffmpeg` decode to frames → PoseLandmarker FULL on T4 → compute the **12 angles with the same definitions as the frontend** → write the CSV in the **exact existing contract** (`frame_number`, `timestamp_ms`, 33 landmarks x/y/z/visibility with the original 15 first and 18 appended, 4-dp coords / 3-dp visibility rounding, 12 angles) to R2 at the pose key → set `pose_status`. Retries: 2, then 'failed' with `pose_error`.
2. Port the frontend golden-file test to Python: the worker's CSV for the golden frames must match byte-for-byte.
3. Modal secret holds R2 creds + `DATABASE_URL` (transaction pooler, `prepare_threshold=None`).

## Frontend (`data_collection/frontend`)

1. Delete the browser extractor, MediaPipe deps, fps detection, monotonic clock, keep-tab-open notice, DecodeUnsupported path. Upload: pick file → play locally at once → PUT to R2 with progress chip → confirm → job enqueued.
2. Pose status chip in the header, polling `/status` every 5s until done/failed. Skeleton overlay renders only when pose is done (fetch CSV then). Export disabled with tooltip until done. Hold auto-suggest shows "waiting for pose" until then.
3. Keep `holdMatching.js`, the CSV parser, angle definitions, and every test not tied to the browser extractor. Remove tests that are.

## Verify

- Worker golden test passes; Modal app deployed; endpoint reachable from Railway.
- One real iPhone clip end to end from the deployed site: pick → label immediately → upload completes → worker runs → skeleton appears → export downloads.
- Record GPU seconds and cost from the Modal dashboard in REPORT.md.

## Done when

A labeler can start labeling within one second of picking a video, and the export becomes available without any user action once the worker finishes.
