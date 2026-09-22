"""
The worker's writes to `public.videos`.

Direct Postgres access over DATABASE_URL (the Supabase TRANSACTION pooler,
port 6543, which is why every connection sets prepare_threshold=None: pgbouncer
in transaction mode does not keep prepared statements across statements).

Only two operations exist, and both are idempotent so a Modal retry can replay
them:

    mark_processing(dsn, video_id)
    record_result(dsn, video_id, status='done', fps=..., ..., r2_pose_csv_key=...)

The backend exposes the same two writes as `POST /api/videos/{id}/pose-result`
(see modal_app.report_result), for deployments where the worker should not hold
a database credential. The column semantics are documented in
backend/supabase/migrations/20260922130000_pose_status.sql.
"""
from __future__ import annotations

from typing import Optional

POSE_STATUSES = ('pending', 'processing', 'done', 'failed')

#: Columns the worker may overwrite with what ffprobe measured. The browser's
#: values at register time were provisional (fps defaulted to 30).
MEASURED_COLUMNS = ('fps', 'total_frames', 'duration_ms', 'width', 'height')


def _connect(dsn: str):
    import psycopg

    return psycopg.connect(dsn, prepare_threshold=None, connect_timeout=15)


def build_result_update(
    video_id: int,
    status: str,
    error: Optional[str] = None,
    r2_pose_csv_key: Optional[str] = None,
    **measured,
) -> tuple[str, list]:
    """The UPDATE statement and its parameters, pure so it can be unit tested."""
    if status not in POSE_STATUSES:
        raise ValueError(f'Unknown pose_status: {status}')
    unknown = set(measured) - set(MEASURED_COLUMNS)
    if unknown:
        raise ValueError(f'Not a measured column: {sorted(unknown)}')

    sets = ['pose_status = %s', 'pose_error = %s']
    params: list = [status, (error or None) if status == 'failed' else None]
    if status == 'processing':
        sets.append('pose_started_at = now()')
        sets.append('pose_finished_at = NULL')
    elif status in ('done', 'failed'):
        sets.append('pose_finished_at = now()')

    for column in MEASURED_COLUMNS:
        value = measured.get(column)
        if value is not None:
            sets.append(f'{column} = %s')
            params.append(value)
    if r2_pose_csv_key is not None:
        sets.append('r2_pose_csv_key = %s')
        params.append(r2_pose_csv_key)
    params.append(video_id)
    return f'UPDATE videos SET {", ".join(sets)} WHERE id = %s', params


def record_result(
    dsn: str,
    video_id: int,
    status: str,
    error: Optional[str] = None,
    r2_pose_csv_key: Optional[str] = None,
    **measured,
) -> bool:
    """Apply the job outcome. Returns False when the video row no longer exists."""
    sql, params = build_result_update(
        video_id, status, error=error, r2_pose_csv_key=r2_pose_csv_key, **measured
    )
    with _connect(dsn) as conn:
        cursor = conn.execute(sql, params)
        return cursor.rowcount > 0


def mark_processing(dsn: str, video_id: int) -> bool:
    return record_result(dsn, video_id, 'processing')


def fetch_pose_state(dsn: str, video_id: int) -> Optional[dict]:
    """Read back the job columns, for the local entrypoint and tests."""
    with _connect(dsn) as conn:
        row = conn.execute(
            'SELECT id, pose_status, pose_error, pose_started_at, pose_finished_at, '
            'fps, total_frames, duration_ms, width, height, r2_pose_csv_key '
            'FROM videos WHERE id = %s',
            (video_id,),
        ).fetchone()
    if row is None:
        return None
    keys = ('id', 'pose_status', 'pose_error', 'pose_started_at', 'pose_finished_at',
            'fps', 'total_frames', 'duration_ms', 'width', 'height', 'r2_pose_csv_key')
    return dict(zip(keys, row))
