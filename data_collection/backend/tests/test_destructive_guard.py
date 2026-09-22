"""
The guard between a stray `pytest` and the production database.

`apply_schema_sql` drops and recreates the labeling tables, and since
migration 20260922150000 it also drops `rater_profiles` and
`video_assignments` — rater identities and the Paper A assignment structure.
Before this guard the only thing standing in the way was a line in
MAILBOX.md and the hope that nobody had `DATABASE_URL` exported.

These tests need no database: the refusal happens before any connection is
used, which is the point.
"""
import os

import pytest

from src.labeling.database import (
    ALLOW_DESTRUCTIVE_ENV,
    DestructiveSchemaRefused,
    _refuse_destructive_dsn,
)
from tests.conftest import _dsn

HOSTED = 'postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres'
POOLER = 'postgresql://postgres.abcd:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres'
RAILWAY = 'postgresql://postgres:pw@containers-us-west-1.railway.app:6543/railway'
LOCAL = 'postgresql://jolie@localhost:5432/dynalytix_test_scratch'
LOCAL_IP = 'postgresql://postgres@127.0.0.1:5433/scratch'


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ALLOW_DESTRUCTIVE_ENV, raising=False)
    monkeypatch.delenv('TEST_DATABASE_URL', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)


# ==================== THE REFUSAL ====================

@pytest.mark.parametrize('dsn', [HOSTED, POOLER, RAILWAY])
def test_hosted_databases_are_refused(dsn):
    with pytest.raises(DestructiveSchemaRefused) as excinfo:
        _refuse_destructive_dsn(dsn, 'apply_schema_sql()')
    message = str(excinfo.value)
    # The message has to tell you what to do instead, not just say no.
    assert 'setup_test_db.sh' in message
    assert 'rater_profiles' in message


@pytest.mark.parametrize('dsn', [LOCAL, LOCAL_IP])
def test_local_databases_are_untouched(dsn):
    _refuse_destructive_dsn(dsn, 'apply_schema_sql()')  # does not raise


def test_an_explicit_opt_in_is_honoured(monkeypatch):
    """There is a way through, for rebuilding a staging database on purpose."""
    monkeypatch.setenv(ALLOW_DESTRUCTIVE_ENV, '1')
    _refuse_destructive_dsn(HOSTED, 'apply_schema_sql()')  # does not raise


def test_a_truthy_but_wrong_opt_in_does_not_count(monkeypatch):
    monkeypatch.setenv(ALLOW_DESTRUCTIVE_ENV, 'yes')
    with pytest.raises(DestructiveSchemaRefused):
        _refuse_destructive_dsn(HOSTED, 'apply_schema_sql()')


def test_an_empty_dsn_is_not_a_crash():
    _refuse_destructive_dsn('', 'apply_schema_sql()')
    _refuse_destructive_dsn(None, 'apply_schema_sql()')


# ==================== THE CONFTEST FALLBACK ====================

def test_a_hosted_database_url_is_not_used_as_a_test_database(monkeypatch):
    """The exact accident this exists to prevent: prod's DSN in the env."""
    monkeypatch.setenv('DATABASE_URL', HOSTED)
    assert _dsn() == '', 'a hosted DATABASE_URL must not become the test database'


def test_a_local_database_url_still_works(monkeypatch):
    """Local dev convenience is kept — this is not meant to be annoying."""
    monkeypatch.setenv('DATABASE_URL', LOCAL)
    assert _dsn() == LOCAL


def test_test_database_url_always_wins(monkeypatch):
    """Setting it is the explicit statement that this database is disposable."""
    monkeypatch.setenv('DATABASE_URL', HOSTED)
    monkeypatch.setenv('TEST_DATABASE_URL', LOCAL)
    assert _dsn() == LOCAL


def test_test_database_url_is_taken_at_its_word(monkeypatch):
    """Even a hosted one: the operator said it, and apply_schema_sql is the
    backstop that still refuses to rebuild it."""
    monkeypatch.setenv('TEST_DATABASE_URL', HOSTED)
    assert _dsn() == HOSTED
    with pytest.raises(DestructiveSchemaRefused):
        _refuse_destructive_dsn(_dsn(), 'apply_schema_sql()')


def test_nothing_set_is_nothing(monkeypatch):
    assert _dsn() == ''
