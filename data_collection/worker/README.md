# Dynalytix pose worker (Modal)

Server-side pose extraction. The browser no longer runs MediaPipe: it registers
a video, uploads it straight to R2, and confirms; the backend then POSTs a job
to this app's `enqueue` endpoint; a T4 container downloads the clip, runs
MediaPipe **PoseLandmarker FULL, VIDEO mode** on every frame at the source
frame rate, writes the pose CSV to R2 at `pose/{user_id}/{video_id}.csv`, and
sets `videos.pose_status = 'done'` with the measured fps / frame count /
duration / dimensions.

```
browser ──register──▶ backend ──▶ videos row (pose_status=pending, provisional fps=30)
browser ──PUT──▶ R2 videos/{user}/{id}/{file}
browser ──confirm-upload──▶ backend ──POST {video_id,user_id,r2_key} + X-Webhook-Secret──▶ enqueue (Modal)
                                                                                           │ spawn
                                                                                           ▼
                            videos row ◀── done/failed + fps,frames,w,h ◀── extract_pose (T4)
                            R2 pose/{user}/{id}.csv ◀───────────────────────────┘
browser ──GET /status every 5 s──▶ backend ; when done: GET /pose-csv-url → fetch CSV → skeleton, export
```

## Files

| File | What |
|---|---|
| `extract.py` | Pure pipeline: `extract_pose_csv(video_path, model_path) -> (csv_text, meta)`. ffprobe → ffmpeg raw-RGB pipe (auto-rotated, presentation order, `showinfo` pts) → PoseLandmarker → CSV. No Modal import. Also a CLI: `python extract.py clip.mov > clip.csv`. |
| `angles.py` | The CSV contract: landmark map, column order (15 legacy first, 18 appended), the 12 angle definitions, 4-dp / 3-dp rounding, JS `Number#toString` formatting. A line-for-line port of `frontend/src/services/poseMath.js`. |
| `fdlibm.py` | fdlibm `acos`, bit-identical to V8's `Math.acos`, so unrounded angle columns match the browser's bytes. |
| `db.py` | The two `videos` updates (`processing`, `done`/`failed` + measured columns) over psycopg with `prepare_threshold=None`. |
| `storage.py` | R2 download/upload via boto3; same `R2_*` env names and key layout as the backend. |
| `modal_app.py` | The Modal app: image, `enqueue` web endpoint, `extract_pose` T4 function, retry policy, result reporting. |
| `models/pose_landmarker_full.task` | The FULL model (9.4 MB, float16), vendored so tests and the image use identical bytes. |
| `tests/` | Golden-file test ported from the frontend, real-file extraction tests, DB and job tests. |

## Deploy

Prerequisites: `pip install modal && modal setup` (once, on your laptop).

1. **Create the Modal secret** (values from the backend's Railway variables;
   `DATABASE_URL` is the **transaction pooler, port 6543**):

   ```bash
   modal secret create dynalytix-worker \
     R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_BUCKET=... \
     DATABASE_URL='postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres' \
     MODAL_WEBHOOK_SECRET="$(openssl rand -hex 32)"
   ```

   Keep the `MODAL_WEBHOOK_SECRET` value: Railway needs the same one. To have
   the worker report through the backend instead of writing Postgres, add
   `POSE_RESULT_MODE=callback BACKEND_URL=https://<railway-backend>`.

2. **Deploy** from the repo root:

   ```bash
   modal deploy data_collection/worker/modal_app.py
   ```

   The output ends with the `enqueue` URL, e.g.
   `https://<workspace>--dynalytix-pose-enqueue.modal.run`.

3. **Point the backend at it** (never echo the secret):

   ```bash
   cd data_collection/backend
   printf 'MODAL_ENDPOINT_URL=%s\n' 'https://<workspace>--dynalytix-pose-enqueue.modal.run' \
     | railway variables --set-from-stdin --skip-deploys
   printf 'MODAL_WEBHOOK_SECRET=%s\n' '<the value from step 1>' \
     | railway variables --set-from-stdin --skip-deploys
   ```

4. **Smoke test** without the frontend: pick an existing uploaded video id
   and run the job directly (bills a few GPU seconds):

   ```bash
   modal run data_collection/worker/modal_app.py --video-id 12 --user-id <uuid> --r2-key videos/<uuid>/12/clip.mov
   ```

   Then check `GET /api/videos/12/status` says `done` and the Modal dashboard
   for GPU seconds. Record them in REPORT.md.

Redeploying after a code change is step 2 again; secrets and the URL are
stable. `modal app stop dynalytix-pose` takes it down (the backend will then
mark new uploads `failed` with "worker rejected the job"/"worker unreachable"
and the retry button re-enqueues once it is back).

## Configuration reference

| Variable | Where | Meaning |
|---|---|---|
| `MODAL_WEBHOOK_SECRET` | Modal secret **and** Railway | Shared secret. Backend → `enqueue` sends it as `X-Webhook-Secret`; worker → `pose-result` callback sends the same header. |
| `MODAL_ENDPOINT_URL` | Railway | The `enqueue` URL from `modal deploy`. |
| `DATABASE_URL` | Modal secret | Transaction pooler DSN; the worker writes `videos` directly (default). |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | Modal secret | Same as the backend. `R2_ENDPOINT_URL` optional override. |
| `POSE_RESULT_MODE` | Modal secret | `db` (default) or `callback`. |
| `BACKEND_URL` | Modal secret | Required for `callback` mode. |
| `POSE_USE_GPU` | Modal secret | `1` (default) tries the TFLite GPU delegate and falls back to CPU if it cannot be created; `0` forces CPU. |

## Retry policy

`run_job` marks the row `processing`, then tries download → extract → upload
up to 3 times (5 s, then 20 s back-off) for transient errors (R2, GPU,
MediaPipe). A `PipelineError` (no video stream, no frames, unknown frame rate)
is not retried. After the last attempt the row is `failed` with `pose_error`;
the labeler's retry button calls `POST /api/videos/{id}/retry-pose`, which
enqueues a fresh call.

## Tests

```bash
cd data_collection/worker
pip install -r requirements.txt pytest   # mediapipe 0.10.32, CPU is fine
TEST_DATABASE_URL=postgresql://.../throwaway python -m pytest tests -q
```

`test_golden.py` is the frontend's golden-file test ported: the same seeded
synthetic landmarks through `angles.py` must reproduce
`frontend/scripts/fixtures/golden_pose.csv` **byte for byte**, and it also
checks the constants against `poseMath.js` by parsing it, JS number
formatting against `node`, and `fdlibm.acos` against `Math.acos` bit for bit.
`test_extract.py` runs the real pipeline on ffmpeg-generated clips (30 fps,
60 fps, rotated) and on the iPhone HEVC sample under `backend/videos/` when it
is checked out. `test_modal_app.py` exercises the retry policy with Modal
stubbed out; `test_db.py` round-trips the row update against
`TEST_DATABASE_URL` when set.

### On "byte-for-byte"

The CSV *format* and the *angle math* are byte-identical to the browser's
(the golden test proves it, down to fdlibm `acos`). The *landmark values*
for a real video are not expected to be: the browser ran MediaPipe's WASM/WebGL
runtime, this runs the TFLite CPU/GPU delegate, and float16 model inference
differs in the low bits between them, then propagates through the tracker.
On the iPhone sample the same model on the two runtimes places the nose a
median 4 px apart at 1080x1920. Row count, frame indexing, timestamps,
rotation and column layout are identical. What the downstream code relies on
(`SkeletonOverlay`, `holdMatching.js`, the backend exporter) is the contract,
not the low bits.

## Cost

T4 is billed per second while the container runs. A 2-minute 30 fps clip is
3600 frames; FULL on a T4 runs well above real time, so expect on the order
of a minute of GPU per clip, i.e. roughly $0.01–0.02. Not yet measured on a
deployed app: fill in from the Modal dashboard after the first real run.
