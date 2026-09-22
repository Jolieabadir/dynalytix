"""
Shared pytest fixtures.

The suite runs against a real Postgres. It applies every migration under
supabase/migrations in order; the v3 base DROPS AND RECREATES the labeling
tables - point TEST_DATABASE_URL at a throwaway database, never at production.

R2 is exercised against the real bucket when credentials are present and
working; otherwise an in-memory fake stands in.
"""
import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# Hermetic signing key - never the project's real secret.
TEST_JWT_SECRET = 'test-jwt-secret-not-a-real-key-padded-to-32-bytes-min'
os.environ.setdefault('SUPABASE_JWT_SECRET', TEST_JWT_SECRET)

import jwt  # noqa: E402

from src.labeling.database import Database  # noqa: E402
from src.storage import r2  # noqa: E402


def _dsn() -> str:
    return os.environ.get('TEST_DATABASE_URL') or os.environ.get('DATABASE_URL') or ''


requires_db = pytest.mark.skipif(
    not _dsn(),
    reason='Set TEST_DATABASE_URL (or DATABASE_URL) to a throwaway Postgres to run these tests',
)


@pytest.fixture(scope='session')
def dsn() -> str:
    if not _dsn():
        pytest.skip('No TEST_DATABASE_URL/DATABASE_URL configured')
    return _dsn()


@pytest.fixture(scope='session')
def db(dsn):
    """A Database on a freshly migrated schema."""
    database = Database(dsn)
    database.apply_schema_sql()
    yield database
    database.close()


@pytest.fixture
def clean_db(db):
    """Truncate every data table so each test starts empty."""
    with db.get_connection() as conn:
        conn.execute(
            'TRUNCATE frame_tags, outcomes, environments, moves, holds, videos, '
            'video_assignments, rater_profiles '
            'RESTART IDENTITY CASCADE'
        )
    return db


@pytest.fixture
def user_a() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def user_b() -> str:
    return str(uuid.uuid4())


def make_jwt(user_id: str, secret: str = None, expires_in: int = 3600) -> str:
    """Mint a Supabase-shaped access token for a user id."""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            'sub': user_id,
            'aud': 'authenticated',
            'role': 'authenticated',
            'iat': now,
            'exp': now + timedelta(seconds=expires_in),
        },
        secret or os.environ['SUPABASE_JWT_SECRET'],
        algorithm='HS256',
    )


# ==================== R2 ====================

class FakeR2:
    """In-memory stand-in for the R2 bucket."""

    def __init__(self):
        self.objects = {}

    def put_object(self, key, body, content_type=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        elif hasattr(body, 'read'):
            body = body.read()
        self.objects[key] = body
        return key

    def get_object_stream(self, key):
        if key not in self.objects:
            raise FileNotFoundError(f'R2 object not found: {key}')
        return io.BytesIO(self.objects[key])

    def object_exists(self, key):
        return key in self.objects

    def presigned_put_url(self, key, content_type=None, expires_in=3600):
        return f'https://fake-r2.local/{key}?sig=put&expires={expires_in}'

    def presigned_get_url(self, key, expires_in=3600, download_filename=None):
        return f'https://fake-r2.local/{key}?sig=get&expires={expires_in}'


def real_r2_usable() -> bool:
    """True when R2 credentials are present and the bucket answers."""
    if not r2.is_configured():
        return False
    try:
        r2.get_client().head_bucket(Bucket=r2.bucket_name())
        return True
    except Exception:
        return False


@pytest.fixture
def fake_r2(monkeypatch):
    """Patch the r2 module's operations with the in-memory fake.

    Skipped in favour of the real bucket when credentials work, so the same
    tests cover both paths.
    """
    if real_r2_usable():
        yield None
        return

    fake = FakeR2()
    for name in (
        'put_object',
        'get_object_stream',
        'object_exists',
        'presigned_put_url',
        'presigned_get_url',
    ):
        monkeypatch.setattr(r2, name, getattr(fake, name))
    monkeypatch.setattr(r2, 'is_configured', lambda: True)
    monkeypatch.setattr(r2, 'bucket_name', lambda: 'fake-bucket')
    yield fake
