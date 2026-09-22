"""
Hand a pose-extraction job to the Modal worker.

The worker (data_collection/worker/modal_app.py) exposes one web endpoint,
`enqueue`, that takes `{video_id, user_id, r2_key}` and spawns the GPU job. It
is protected by a shared secret sent as `X-Webhook-Secret`. The backend calls
it from confirm-upload and retry-pose.

Configuration (Railway variables, set with `railway variables
--set-from-stdin --skip-deploys`, never echoed):

    MODAL_ENDPOINT_URL   the URL `modal deploy` printed for `enqueue`
    MODAL_WEBHOOK_SECRET the same value stored in the Modal secret

A missing configuration or a failed request never fails the user's request:
the caller marks the video 'failed' with a readable pose_error and the labeler
can hit retry once the worker is up.
"""
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

SECRET_HEADER = 'X-Webhook-Secret'
ENQUEUE_TIMEOUT_S = 15.0


class PoseQueueError(RuntimeError):
    """The job could not be handed to the worker."""


class PoseQueueNotConfigured(PoseQueueError):
    """MODAL_ENDPOINT_URL / MODAL_WEBHOOK_SECRET are not set."""


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def is_configured() -> bool:
    return bool(_env('MODAL_ENDPOINT_URL') and _env('MODAL_WEBHOOK_SECRET'))


def enqueue_pose_job(video_id: int, user_id: str, r2_key: str) -> dict:
    """POST the job to the worker's `enqueue` endpoint.

    Returns the worker's JSON acknowledgement. Raises PoseQueueNotConfigured
    when the env vars are missing and PoseQueueError on any transport or
    non-2xx response; the message is short and safe to store in pose_error.
    """
    url = _env('MODAL_ENDPOINT_URL')
    secret = _env('MODAL_WEBHOOK_SECRET')
    if not url or not secret:
        raise PoseQueueNotConfigured(
            'worker not configured: set MODAL_ENDPOINT_URL and MODAL_WEBHOOK_SECRET'
        )

    payload = {'video_id': video_id, 'user_id': user_id, 'r2_key': r2_key}
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={SECRET_HEADER: secret},
            timeout=ENQUEUE_TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        log.warning('pose enqueue failed for video %s: %r', video_id, exc)
        raise PoseQueueError(f'worker unreachable: {type(exc).__name__}') from exc

    if response.status_code >= 300:
        body = response.text[:200].replace('\n', ' ')
        log.warning('pose enqueue rejected for video %s: %s %s', video_id, response.status_code, body)
        raise PoseQueueError(f'worker rejected the job ({response.status_code}): {body}')

    try:
        return response.json()
    except ValueError:
        return {'accepted': True}
