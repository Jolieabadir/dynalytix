"""
R2 access for the worker: download the video, upload the CSV.

Same environment variable names and key layout as backend/src/storage/r2.py,
so one Modal secret can be filled from the backend's Railway variables:

    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
    R2_ENDPOINT_URL   optional override (local MinIO / S3 stub)
"""
from __future__ import annotations

import os
from typing import Optional


class R2NotConfigured(RuntimeError):
    """A required R2_* variable is missing."""


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def bucket_name() -> str:
    bucket = _env('R2_BUCKET')
    if not bucket:
        raise R2NotConfigured('R2_BUCKET is not set')
    return bucket


def endpoint_url() -> str:
    override = _env('R2_ENDPOINT_URL')
    if override:
        return override
    account = _env('R2_ACCOUNT_ID')
    if not account:
        raise R2NotConfigured('R2_ACCOUNT_ID is not set (or set R2_ENDPOINT_URL)')
    return f'https://{account}.r2.cloudflarestorage.com'


def get_client():
    import boto3
    from botocore.config import Config

    key_id, secret = _env('R2_ACCESS_KEY_ID'), _env('R2_SECRET_ACCESS_KEY')
    if not key_id or not secret:
        raise R2NotConfigured('R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY are not set')
    return boto3.client(
        's3',
        endpoint_url=endpoint_url(),
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name='auto',
        config=Config(signature_version='s3v4', retries={'max_attempts': 3, 'mode': 'standard'}),
    )


# ==================== KEY LAYOUT (mirrors backend r2.py) ====================

def video_key(user_id: str, video_id: int, filename: str) -> str:
    return f'videos/{user_id}/{video_id}/{filename}'


def pose_csv_key(user_id: str, video_id: int) -> str:
    return f'pose/{user_id}/{video_id}.csv'


def key_belongs_to(key: str, user_id: str) -> bool:
    """The backend enforces this on confirm-upload; the worker re-checks it."""
    return key.startswith(f'videos/{user_id}/')


# ==================== OPERATIONS ====================

def download_video(key: str, local_path: str, client=None) -> str:
    client = client or get_client()
    client.download_file(bucket_name(), key, local_path)
    return local_path


def upload_csv(key: str, csv_text: str, client=None) -> str:
    client = client or get_client()
    client.put_object(
        Bucket=bucket_name(),
        Key=key,
        Body=csv_text.encode('utf-8'),
        ContentType='text/csv',
    )
    return key
