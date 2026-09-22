"""
Modal app `dynalytix-pose`: server-side pose extraction.

Two entry points:

- `enqueue` - a web endpoint the backend POSTs to from confirm-upload (and
  retry-pose) with `{video_id, user_id, r2_key}` and the shared secret in the
  `X-Webhook-Secret` header. It validates the secret and spawns `extract_pose`,
  returning 202-style JSON at once.
- `extract_pose(video_id, user_id, r2_key)` - the GPU function. Downloads the
  video from R2, runs extract.py (ffprobe -> ffmpeg -> PoseLandmarker FULL ->
  CSV in the frontend contract), uploads the CSV to `pose/{user_id}/{video_id}
  .csv`, and records the outcome on the `videos` row.

Reporting the outcome (`report_result`): by default the worker writes
`public.videos` directly over DATABASE_URL (transaction pooler,
prepare_threshold=None), as the runbook specifies. Setting `POSE_RESULT_MODE=
callback` in the Modal secret makes it POST `{BACKEND_URL}/api/videos/{id}/
pose-result` with the same `X-Webhook-Secret` instead, for a deployment where
the worker should not hold a database credential. Both paths apply the same
update.

Retries: transient failures (R2, MediaPipe, an ffmpeg crash) are retried twice
inside the call (3 attempts, backing off), then the row is marked 'failed' with
pose_error. A PipelineError (the file itself is unusable: no video stream, no
frames, unknown fps) is not retried. The labeler can hit retry-pose in the UI,
which enqueues a fresh call.

Deploy (see README.md):

    modal secret create dynalytix-worker \\
        R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_BUCKET=... \\
        DATABASE_URL=postgresql://...:6543/postgres MODAL_WEBHOOK_SECRET=...
    modal deploy data_collection/worker/modal_app.py

`modal deploy` prints the `enqueue` URL; that is the backend's MODAL_ENDPOINT_URL.
"""
from __future__ import annotations

import hmac
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import modal

APP_NAME = 'dynalytix-pose'
SECRET_NAME = 'dynalytix-worker'
SECRET_HEADER = 'X-Webhook-Secret'

HERE = Path(__file__).resolve().parent
LOCAL_MODEL = HERE / 'models' / 'pose_landmarker_full.task'
MODEL_PATH = '/models/pose_landmarker_full.task'

#: 1 attempt + 2 retries, as the runbook specifies.
ATTEMPTS = 3
RETRY_BACKOFF_S = (5, 20)

log = logging.getLogger(APP_NAME)
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

image = (
    modal.Image.debian_slim(python_version='3.11')
    # ffmpeg/ffprobe for decode; libGL/EGL for MediaPipe (CPU build still links
    # them, and the GPU delegate needs EGL + GLES).
    .apt_install('ffmpeg', 'libgl1', 'libglib2.0-0', 'libegl1', 'libgles2')
    .pip_install_from_requirements(str(HERE / 'requirements.txt'))
    # The vendored FULL model (9.4 MB) and the pipeline modules.
    .add_local_file(str(LOCAL_MODEL), MODEL_PATH)
    .add_local_python_source('extract', 'angles', 'fdlibm', 'db', 'storage')
)

app = modal.App(APP_NAME)
secret = modal.Secret.from_name(SECRET_NAME)


# ==================== helpers (run inside the container) ====================

def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def _secret_matches(provided: str | None) -> bool:
    expected = _env('MODAL_WEBHOOK_SECRET')
    if not expected or not provided:
        return False
    token = provided[7:] if provided.lower().startswith('bearer ') else provided
    return hmac.compare_digest(token.strip(), expected)


def report_result(video_id: int, status: str, error: str | None = None, **fields) -> None:
    """Record the job state. Direct DB write by default; callback when configured.

    Raises on failure so the caller can decide whether to retry; a failed
    status ping must never mask the real job outcome, so callers wrap the
    'processing' ping but let 'done'/'failed' propagate.
    """
    mode = (_env('POSE_RESULT_MODE') or 'db').lower()
    if mode == 'callback':
        _post_callback(video_id, status, error, **fields)
        return

    import db

    dsn = _env('DATABASE_URL')
    if not dsn:
        raise RuntimeError(f'DATABASE_URL is not set in the {SECRET_NAME} secret')
    if not db.record_result(dsn, video_id, status, error=error, **fields):
        log.warning('video %s: no such row when recording %s', video_id, status)


def _post_callback(video_id: int, status: str, error: str | None, **fields) -> None:
    import httpx

    base = _env('BACKEND_URL')
    if not base:
        raise RuntimeError('POSE_RESULT_MODE=callback needs BACKEND_URL in the secret')
    url = f"{base.rstrip('/')}/api/videos/{video_id}/pose-result"
    payload = {'status': status, 'error': error, **{k: v for k, v in fields.items() if v is not None}}
    headers = {SECRET_HEADER: _env('MODAL_WEBHOOK_SECRET') or ''}
    last_error = None
    for attempt in range(3):
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=20)
            if response.status_code < 300:
                return
            last_error = f'{response.status_code}: {response.text[:300]}'
            if response.status_code < 500 and response.status_code != 429:
                break  # a 4xx will not fix itself
        except httpx.HTTPError as exc:
            last_error = repr(exc)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'pose-result callback failed: {last_error}')


def _run_once(video_id: int, user_id: str, r2_key: str, use_gpu: bool) -> dict:
    """One attempt: download -> extract -> upload. Returns the 'done' fields."""
    import storage
    from extract import extract_pose_csv

    client = storage.get_client()
    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, os.path.basename(r2_key) or 'video')
        storage.download_video(r2_key, local, client=client)
        csv_text, meta = extract_pose_csv(local, MODEL_PATH, use_gpu=use_gpu)

    key = storage.pose_csv_key(user_id, video_id)
    storage.upload_csv(key, csv_text, client=client)
    return {
        'fps': meta.fps,
        'total_frames': meta.total_frames,
        'duration_ms': meta.duration_ms,
        'width': meta.width,
        'height': meta.height,
        'r2_pose_csv_key': key,
        'frames_with_pose': meta.frames_with_pose,
    }


def run_job(video_id: int, user_id: str, r2_key: str, use_gpu: bool = True) -> dict:
    """The job body, Modal-free so it can be exercised locally.

    Marks processing, tries up to ATTEMPTS times, then records done or failed.
    """
    from extract import PipelineError

    started = time.time()
    log.info('video %s: start (user %s, key %s)', video_id, user_id, r2_key)

    try:
        report_result(video_id, 'processing')
    except Exception as exc:  # noqa: BLE001 - never fail the job over a status ping
        log.warning('video %s: could not mark processing: %s', video_id, exc)

    last_error = 'unknown error'
    for attempt in range(1, ATTEMPTS + 1):
        try:
            fields = _run_once(video_id, user_id, r2_key, use_gpu)
            frames_with_pose = fields.pop('frames_with_pose')
            report_result(video_id, 'done', **fields)
            elapsed = time.time() - started
            log.info(
                'video %s: done in %.1fs (%d frames, %d with a pose, attempt %d)',
                video_id, elapsed, fields['total_frames'], frames_with_pose, attempt,
            )
            return {
                'video_id': video_id, 'status': 'done', **fields,
                'frames_with_pose': frames_with_pose, 'seconds': elapsed, 'attempts': attempt,
                'finished_at': datetime.now(timezone.utc).isoformat(),
            }
        except PipelineError as exc:
            # The file itself is unusable; retrying the same bytes cannot help.
            last_error = str(exc)
            log.error('video %s: pipeline failed, not retrying: %s', video_id, exc)
            break
        except Exception as exc:  # noqa: BLE001
            last_error = f'{type(exc).__name__}: {exc}'
            log.warning('video %s: attempt %d/%d failed: %s', video_id, attempt, ATTEMPTS, last_error)
            if attempt < ATTEMPTS:
                time.sleep(RETRY_BACKOFF_S[min(attempt - 1, len(RETRY_BACKOFF_S) - 1)])

    report_result(video_id, 'failed', error=last_error[:1000])
    return {'video_id': video_id, 'status': 'failed', 'error': last_error, 'seconds': time.time() - started}


# ==================== the GPU job ====================

@app.function(
    image=image,
    gpu='T4',
    timeout=1800,
    secrets=[secret],
)
def extract_pose(video_id: int, user_id: str, r2_key: str) -> dict:
    """Download -> ffprobe/ffmpeg -> PoseLandmarker FULL -> CSV -> R2 -> videos row."""
    use_gpu = (_env('POSE_USE_GPU') or '1') not in ('0', 'false', 'no')
    return run_job(video_id, user_id, r2_key, use_gpu=use_gpu)


# ==================== the web endpoint ====================

@app.function(image=image, secrets=[secret], timeout=30)
@modal.fastapi_endpoint(method='POST')
def enqueue(body: dict, request: 'Request'):  # noqa: F821 - FastAPI resolves the annotation
    """Backend -> worker hand-off. Secret-protected; returns at once."""
    from fastapi import HTTPException

    provided = request.headers.get(SECRET_HEADER) or request.headers.get('authorization')
    if not _secret_matches(provided):
        raise HTTPException(status_code=401, detail='bad or missing worker secret')

    try:
        video_id = int(body['video_id'])
        user_id = str(body['user_id'])
        r2_key = str(body['r2_key'])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail='video_id, user_id and r2_key are required')

    import storage
    if not storage.key_belongs_to(r2_key, user_id):
        raise HTTPException(status_code=400, detail='r2_key does not belong to user_id')

    call = extract_pose.spawn(video_id, user_id, r2_key)
    return {'accepted': True, 'video_id': video_id, 'call_id': call.object_id}


@app.local_entrypoint()
def main(video_id: int, user_id: str, r2_key: str):
    """`modal run modal_app.py --video-id 12 --user-id <uuid> --r2-key videos/<uuid>/12/clip.mov`"""
    print(extract_pose.remote(video_id, user_id, r2_key))
