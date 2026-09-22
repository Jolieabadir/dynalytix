"""
The worker's videos-row update, pure SQL building and against the test DB.
"""
import sys
from pathlib import Path

import pytest

from conftest import BACKEND_ROOT, dsn_for_tests
import db


def test_build_result_update_done_overwrites_measured_columns():
    sql, params = db.build_result_update(
        7, 'done', fps=60.0, total_frames=180, duration_ms=3000.0, width=1080, height=1920,
        r2_pose_csv_key='pose/u/7.csv',
    )
    assert sql == (
        'UPDATE videos SET pose_status = %s, pose_error = %s, pose_finished_at = now(), '
        'fps = %s, total_frames = %s, duration_ms = %s, width = %s, height = %s, '
        'r2_pose_csv_key = %s WHERE id = %s'
    )
    assert params == ['done', None, 60.0, 180, 3000.0, 1080, 1920, 'pose/u/7.csv', 7]


def test_build_result_update_processing_and_failed():
    sql, params = db.build_result_update(7, 'processing')
    assert 'pose_started_at = now()' in sql and 'pose_finished_at = NULL' in sql
    assert params == ['processing', None, 7]

    sql, params = db.build_result_update(7, 'failed', error='ffmpeg exited 1')
    assert 'pose_finished_at = now()' in sql
    assert params == ['failed', 'ffmpeg exited 1', 7]

    # An error is only stored with 'failed'.
    _, params = db.build_result_update(7, 'done', error='stale', r2_pose_csv_key='k')
    assert params[1] is None


def test_build_result_update_rejects_bad_input():
    with pytest.raises(ValueError):
        db.build_result_update(1, 'sideways')
    with pytest.raises(ValueError):
        db.build_result_update(1, 'done', filename='x.mp4')


@pytest.mark.skipif(not dsn_for_tests(), reason='TEST_DATABASE_URL not set')
def test_record_result_against_postgres():
    """Apply the backend migrations to the throwaway DB, then round-trip."""
    sys.path.insert(0, str(BACKEND_ROOT))
    from src.labeling.database import Database
    from src.labeling.models import Video

    database = Database(dsn_for_tests())
    try:
        database.apply_schema_sql()
        user = '11111111-2222-3333-4444-555555555555'
        video_id = database.create_video(Video(
            user_id=user, filename='clip.mov', fps=30.0, total_frames=90, duration_ms=3000.0,
        ))

        assert db.mark_processing(dsn_for_tests(), video_id)
        state = db.fetch_pose_state(dsn_for_tests(), video_id)
        assert state['pose_status'] == 'processing' and state['pose_started_at'] is not None

        assert db.record_result(
            dsn_for_tests(), video_id, 'done', fps=60.0, total_frames=180, duration_ms=3001.0,
            width=1080, height=1920, r2_pose_csv_key=f'pose/{user}/{video_id}.csv',
        )
        video = database.get_video(video_id, user)
        assert video.pose_status == 'done'
        assert video.fps == 60.0 and video.total_frames == 180
        assert (video.width, video.height) == (1080, 1920)
        assert video.r2_pose_csv_key == f'pose/{user}/{video_id}.csv'
        assert video.pose_finished_at is not None

        assert db.record_result(dsn_for_tests(), video_id, 'failed', error='x')
        assert database.get_video(video_id, user).pose_error == 'x'
        assert db.record_result(dsn_for_tests(), 999999, 'failed', error='x') is False
        assert db.fetch_pose_state(dsn_for_tests(), 999999) is None
    finally:
        database.close()
