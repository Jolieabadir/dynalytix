"""
Row Level Security for Dataset A, exercised the way PostgREST would hit it:
as the non-superuser `authenticated` role with `request.jwt.claims` set.

The API's own role bypasses RLS, so tests/test_dataset_a.py says nothing
about these policies. Here every statement runs through
    SET ROLE authenticated; SET request.jwt.claims = '{"sub": ...}';
on a fresh connection, so both the policies and the column privileges the
migration grants / revokes are what decide the outcome.
"""
import json
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from src.labeling.models import Video, Hold, Move, Environment, RaterProfile, VideoAssignment
from tests.conftest import requires_db

pytestmark = requires_db


# ==================== HELPERS ====================

class As:
    """Run statements as `authenticated` for one user id (None = anon)."""

    def __init__(self, dsn: str, user_id):
        self.dsn = dsn
        self.user_id = user_id

    def _connect(self):
        conn = psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row)
        role = 'authenticated' if self.user_id else 'anon'
        conn.execute(f'SET ROLE {role}')
        claims = json.dumps({'sub': self.user_id, 'role': role} if self.user_id else {'role': role})
        conn.execute("SELECT set_config('request.jwt.claims', %s, false)", (claims,))
        return conn

    def rows(self, sql, params=()):
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def count(self, sql, params=()):
        """Rows affected by a write (0 when RLS filters everything)."""
        with self._connect() as conn:
            return conn.execute(sql, params).rowcount

    def error(self, sql, params=()):
        """The psycopg error class a statement raises, or None."""
        try:
            with self._connect() as conn:
                conn.execute(sql, params)
        except psycopg.Error as exc:
            return type(exc)
        return None


@pytest.fixture
def world(clean_db, dsn):
    """Owner (non-admin) with a ready video, admin, two assigned raters, one outsider."""
    db = clean_db
    ids = {
        'owner': str(uuid.uuid4()), 'admin': str(uuid.uuid4()),
        'rater_a': str(uuid.uuid4()), 'rater_b': str(uuid.uuid4()),
        'outsider': str(uuid.uuid4()),
    }
    for key in ('owner', 'admin', 'rater_a', 'rater_b', 'outsider'):
        db.create_rater_profile(RaterProfile(user_id=ids[key], display_name=key))
    db.update_rater_profile(ids['admin'], is_admin=True)
    db.update_rater_profile(ids['rater_a'], tier='validated', validation_note='coach')

    video_id = db.create_video(Video(user_id=ids['owner'], filename='v.mp4', fps=30,
                                     total_frames=3, duration_ms=100,
                                     r2_pose_csv_key='pose/secret.csv'))
    db.update_video_fields(video_id, dataset='A', prep_status='ready')
    other_id = db.create_video(Video(user_id=ids['admin'], filename='other.mp4', fps=30,
                                     total_frames=3, duration_ms=100,
                                     r2_pose_csv_key='pose/other.csv'))
    hold_id = db.create_hold(Hold(video_id=video_id, user_id=ids['owner'],
                                  bbox_x=0.1, bbox_y=0.1, bbox_w=0.1, bbox_h=0.1))
    move_id = db.create_move(Move(video_id=video_id, user_id=ids['owner'], frame_start=0,
                                  frame_end=2, timestamp_start_ms=0, timestamp_end_ms=66,
                                  approach='dynamic', size='large', move_tags=['dyno'],
                                  form_quality=3, effort_level=5, confidence='high'))
    a_id = db.create_assignment(VideoAssignment(video_id=video_id, rater_user_id=ids['rater_a'],
                                                cohort='validated')).id
    b_id = db.create_assignment(VideoAssignment(video_id=video_id, rater_user_id=ids['rater_b'],
                                                cohort='overlap')).id
    env_a = db.create_environment(Environment(move_id=move_id, user_id=ids['rater_a'],
                                              wall_angle='steep'))
    env_b = db.create_environment(Environment(move_id=move_id, user_id=ids['rater_b'],
                                              wall_angle='slab'))
    return dict(ids, dsn=dsn, video_id=video_id, other_id=other_id, hold_id=hold_id,
                move_id=move_id, assignment_a=a_id, assignment_b=b_id,
                env_a=env_a, env_b=env_b, db=db)


def as_(world, who):
    return As(world['dsn'], world[who] if who else None)


# ==================== 1. video_assignments are admin-write-only ====================

def test_rater_cannot_repoint_or_complete_their_assignment(world):
    rater = as_(world, 'rater_a')
    # Before: the rater cannot see the other video at all.
    assert rater.rows('SELECT id FROM videos WHERE id = %s', (world['other_id'],)) == []

    # UPDATE video_id -> filtered out by RLS (0 rows), not permission denied.
    assert rater.count('UPDATE video_assignments SET video_id = %s WHERE id = %s',
                       (world['other_id'], world['assignment_a'])) == 0
    assert rater.count("UPDATE video_assignments SET status = 'done' WHERE id = %s",
                       (world['assignment_a'],)) == 0
    assert rater.count('DELETE FROM video_assignments WHERE id = %s', (world['assignment_b'],)) == 0
    assert rater.error(
        "INSERT INTO video_assignments (video_id, rater_user_id, cohort) VALUES (%s, %s, 'overlap')",
        (world['other_id'], world['rater_a']),
    ) is psycopg.errors.InsufficientPrivilege  # RLS WITH CHECK violation

    # Nothing moved, and the other video is still invisible.
    row = world['db'].get_assignment(world['assignment_a'])
    assert row.video_id == world['video_id'] and row.status == 'assigned'
    assert rater.rows('SELECT id FROM videos WHERE id = %s', (world['other_id'],)) == []
    # The rater still reads their own assignment row, and not the other rater's.
    assert [r['id'] for r in rater.rows('SELECT id FROM video_assignments ORDER BY id')] == [world['assignment_a']]

    # Admin can.
    admin = as_(world, 'admin')
    assert admin.count("UPDATE video_assignments SET status = 'done' WHERE id = %s",
                       (world['assignment_a'],)) == 1


# ==================== 2. videos: dataset / prep_status are API-only ====================

def test_owner_cannot_change_prep_status_or_dataset_but_can_edit_metadata(world):
    owner = as_(world, 'owner')
    assert owner.error("UPDATE videos SET prep_status = 'draft' WHERE id = %s",
                       (world['video_id'],)) is psycopg.errors.InsufficientPrivilege
    assert owner.error("UPDATE videos SET dataset = 'B' WHERE id = %s",
                       (world['video_id'],)) is psycopg.errors.InsufficientPrivilege
    assert owner.count("UPDATE videos SET notes = 'mine' WHERE id = %s", (world['video_id'],)) == 1
    video = world['db'].get_video_any(world['video_id'])
    assert video.prep_status == 'ready' and video.dataset == 'A' and video.notes == 'mine'

    # An admin through PostgREST is bound by the same column privilege: the
    # ready/close/reopen transitions are API routes.
    admin = as_(world, 'admin')
    assert admin.error("UPDATE videos SET prep_status = 'closed' WHERE id = %s",
                       (world['video_id'],)) is psycopg.errors.InsufficientPrivilege
    # The API's own (superuser / postgres) role is unaffected.
    assert world['db'].update_video_fields(world['video_id'], prep_status='closed').prep_status == 'closed'


# ==================== 3. rater_profiles: own row editable, privileged columns not ====================

def test_validated_rater_can_rename_but_not_promote_themself(world):
    rater = as_(world, 'rater_a')  # tier = validated, validation_note set
    assert rater.count("UPDATE rater_profiles SET display_name = 'A. Rater' WHERE user_id = %s",
                       (world['rater_a'],)) == 1
    assert rater.error("UPDATE rater_profiles SET tier = 'open' WHERE user_id = %s",
                       (world['rater_a'],)) is psycopg.errors.InsufficientPrivilege
    assert rater.error("UPDATE rater_profiles SET is_admin = true WHERE user_id = %s",
                       (world['rater_a'],)) is psycopg.errors.InsufficientPrivilege
    assert rater.error("UPDATE rater_profiles SET validation_note = 'x' WHERE user_id = %s",
                       (world['rater_a'],)) is psycopg.errors.InsufficientPrivilege
    # Someone else's row: filtered, not touched.
    assert rater.count("UPDATE rater_profiles SET display_name = 'pwned' WHERE user_id = %s",
                       (world['rater_b'],)) == 0
    profile = world['db'].get_rater_profile(world['rater_a'])
    assert profile.display_name == 'A. Rater' and profile.tier == 'validated' and not profile.is_admin
    # They only see themself (admin sees everyone).
    assert [r['user_id'] for r in rater.rows('SELECT user_id FROM rater_profiles')] == [uuid.UUID(world['rater_a'])]
    assert len(as_(world, 'admin').rows('SELECT user_id FROM rater_profiles')) == 5


def test_self_insert_uses_defaults_and_cannot_name_privileged_columns(world):
    newcomer = str(uuid.uuid4())
    me = As(world['dsn'], newcomer)
    assert me.count("INSERT INTO rater_profiles (user_id, display_name) VALUES (%s, 'New')",
                    (newcomer,)) == 1
    profile = world['db'].get_rater_profile(newcomer)
    assert profile.tier == 'open' and profile.is_admin is False and profile.validation_note is None

    another = str(uuid.uuid4())
    other = As(world['dsn'], another)
    assert other.error(
        "INSERT INTO rater_profiles (user_id, display_name, is_admin) VALUES (%s, 'X', true)",
        (another,)) is psycopg.errors.InsufficientPrivilege
    assert other.error(
        "INSERT INTO rater_profiles (user_id, display_name, tier) VALUES (%s, 'X', 'validated')",
        (another,)) is psycopg.errors.InsufficientPrivilege
    # A row for somebody else fails the policy.
    assert other.error(
        "INSERT INTO rater_profiles (user_id, display_name) VALUES (%s, 'X')",
        (str(uuid.uuid4()),)) is psycopg.errors.InsufficientPrivilege
    assert world['db'].get_rater_profile(another) is None


# ==================== Scoping the policies were written for ====================

def test_rater_reads_assigned_video_only_and_never_another_raters_labels(world):
    a, b, outsider = as_(world, 'rater_a'), as_(world, 'rater_b'), as_(world, 'outsider')
    vid = world['video_id']

    assert [r['id'] for r in a.rows('SELECT id FROM videos')] == [vid]
    assert a.rows('SELECT r2_pose_csv_key FROM videos WHERE id = %s', (vid,))[0]['r2_pose_csv_key'] == 'pose/secret.csv'
    assert [r['id'] for r in a.rows('SELECT id FROM holds')] == [world['hold_id']]
    assert [r['id'] for r in a.rows('SELECT id FROM moves')] == [world['move_id']]
    assert outsider.rows('SELECT id FROM videos') == []
    assert outsider.rows('SELECT id FROM holds') == []
    assert outsider.rows('SELECT id FROM moves') == []

    # Each rater sees exactly their own environment on the shared move.
    assert [r['id'] for r in a.rows('SELECT id FROM environments WHERE move_id = %s', (world['move_id'],))] == [world['env_a']]
    assert [r['id'] for r in b.rows('SELECT id FROM environments WHERE move_id = %s', (world['move_id'],))] == [world['env_b']]
    assert b.count("UPDATE environments SET wall_angle = 'vertical' WHERE id = %s", (world['env_a'],)) == 0
    assert b.count('DELETE FROM environments WHERE id = %s', (world['env_a'],)) == 0
    assert world['db'].get_environment(world['env_a'], world['rater_a']).wall_angle == 'steep'
    # Admin reads both.
    assert len(as_(world, 'admin').rows('SELECT id FROM environments WHERE move_id = %s', (world['move_id'],))) == 2

    # Unassigning rater_a hides the video again.
    world['db'].delete_assignment(world['assignment_a'])
    assert a.rows('SELECT id FROM videos') == []
    assert a.rows('SELECT id FROM moves') == []


def test_structure_locks_at_ready_for_owner_and_always_for_raters(world):
    owner, rater = as_(world, 'owner'), as_(world, 'rater_a')
    vid, hold_id, move_id = world['video_id'], world['hold_id'], world['move_id']

    for who in (owner, rater):
        assert who.count("UPDATE holds SET bbox_x = 0.9 WHERE id = %s", (hold_id,)) == 0
        assert who.count("UPDATE moves SET description = 'x' WHERE id = %s", (move_id,)) == 0
        assert who.count('DELETE FROM holds WHERE id = %s', (hold_id,)) == 0
        assert who.error(
            "INSERT INTO holds (video_id, user_id, bbox_x, bbox_y, bbox_w, bbox_h) VALUES (%s, %s, 0.2, 0.2, 0.1, 0.1)",
            (vid, who.user_id)) is psycopg.errors.InsufficientPrivilege

    # Admin edits through the lock; back in draft the owner can again, the rater never.
    assert as_(world, 'admin').count("UPDATE moves SET description = 'admin' WHERE id = %s", (move_id,)) == 1
    world['db'].update_video_fields(vid, prep_status='draft')
    assert owner.count("UPDATE moves SET description = 'owner' WHERE id = %s", (move_id,)) == 1
    assert rater.count("UPDATE moves SET description = 'rater' WHERE id = %s", (move_id,)) == 0
    assert world['db'].get_move_any(move_id).description == 'owner'


def test_anon_sees_nothing(world):
    anon = as_(world, None)
    for table in ('videos', 'holds', 'moves', 'environments', 'rater_profiles', 'video_assignments'):
        assert anon.rows(f'SELECT 1 FROM {table}') == [], table
