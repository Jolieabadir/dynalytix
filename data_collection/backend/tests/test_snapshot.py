"""
scripts/snapshot_to_r2.py: every public table lands as CSV under
snapshots/YYYY-MM-DD/<table>.csv. R2 is mocked; Postgres is real.
"""
import csv
import io
import uuid

import pytest

from scripts import snapshot_to_r2 as snap
from src.labeling.models import Video, RaterProfile
from tests.conftest import requires_db

pytestmark = requires_db

EXPECTED_TABLES = {
    'videos', 'holds', 'moves', 'environments', 'outcomes', 'frame_tags',
    'rater_profiles', 'video_assignments', 'schema_version',
}


def test_snapshot_writes_one_csv_per_public_table(clean_db, dsn):
    user = str(uuid.uuid4())
    clean_db.create_video(Video(user_id=user, filename='a.mp4', fps=30, total_frames=3,
                                duration_ms=100, notes='has,comma "and quotes"'))
    clean_db.create_rater_profile(RaterProfile(user_id=user, display_name='R'))

    uploaded = {}

    def record(key, body):
        uploaded[key] = body

    written = snap.snapshot(dsn, date_str='2026-09-22', upload=record, log=lambda *_: None)

    assert set(written) == set(uploaded)
    tables = {key.split('/')[-1][:-4] for key in uploaded}
    assert EXPECTED_TABLES <= tables, tables - EXPECTED_TABLES
    assert all(key.startswith('snapshots/2026-09-22/') and key.endswith('.csv') for key in uploaded)
    assert written == sorted(written)

    rows = list(csv.DictReader(io.StringIO(uploaded['snapshots/2026-09-22/videos.csv'].decode())))
    assert len(rows) == 1
    assert rows[0]['user_id'] == user
    assert rows[0]['notes'] == 'has,comma "and quotes"'
    assert rows[0]['dataset'] == 'B'
    profiles = list(csv.DictReader(io.StringIO(uploaded['snapshots/2026-09-22/rater_profiles.csv'].decode())))
    assert profiles[0]['display_name'] == 'R'
    # An empty table still produces a header-only file.
    assert uploaded['snapshots/2026-09-22/holds.csv'].decode().splitlines()[0].startswith('id,')


def test_snapshot_default_upload_uses_r2(clean_db, dsn, monkeypatch):
    calls = []
    monkeypatch.setattr(snap.r2, 'put_object',
                        lambda key, body, content_type=None: calls.append((key, content_type)))
    written = snap.snapshot(dsn, date_str='2026-01-01', tables=['videos'], log=lambda *_: None)
    assert written == ['snapshots/2026-01-01/videos.csv']
    assert calls == [('snapshots/2026-01-01/videos.csv', 'text/csv')]


def test_snapshot_reports_failures_after_trying_every_table(clean_db, dsn):
    uploaded = []

    def flaky(key, body):
        if key.endswith('/videos.csv'):
            raise OSError('bucket unavailable')
        uploaded.append(key)

    with pytest.raises(RuntimeError, match='videos: OSError'):
        snap.snapshot(dsn, date_str='2026-01-01', upload=flaky,
                      tables=['videos', 'holds'], log=lambda *_: None)
    assert uploaded == ['snapshots/2026-01-01/holds.csv']


def test_main_requires_database_url(monkeypatch, capsys):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    assert snap.main([]) == 2
