"""
Schema v3 database tests.

Covers the Postgres port: identity keys, jsonb round-trips, the four hold
slots, nullable foot slot, and user scoping at the data layer.
"""
import uuid
from pathlib import Path
from datetime import datetime, timezone

import psycopg
import pytest

from src.labeling.database import SCHEMA_VERSION
from src.labeling.models import (
    Video, Hold, Move, Environment, Outcome, FrameTag, HOLD_SLOTS,
)
from tests.conftest import requires_db

pytestmark = requires_db


# ==================== HELPERS ====================

def make_video(user_id: str, **kwargs) -> Video:
    defaults = dict(
        user_id=user_id,
        filename='climb.mp4',
        fps=30.0,
        total_frames=120,
        duration_ms=4000.0,
        r2_pose_csv_key=f'pose/{user_id}/1.csv',
    )
    defaults.update(kwargs)
    return Video(**defaults)


def make_move(user_id: str, video_id: int, **kwargs) -> Move:
    defaults = dict(
        video_id=video_id,
        user_id=user_id,
        frame_start=10,
        frame_end=20,
        timestamp_start_ms=333.0,
        timestamp_end_ms=666.0,
        approach='dynamic',
        move_tags=['dyno', 'tension'],
        size='large',
        form_quality=4,
        effort_level=8,
        confidence='high',
        description='big move to the jug',
    )
    defaults.update(kwargs)
    return Move(**defaults)


def make_hold(user_id: str, video_id: int, **kwargs) -> Hold:
    defaults = dict(
        video_id=video_id,
        user_id=user_id,
        bbox_x=0.1, bbox_y=0.2, bbox_w=0.05, bbox_h=0.04,
        source='manual',
    )
    defaults.update(kwargs)
    return Hold(**defaults)


# ==================== SCHEMA ====================

def test_schema_version_is_three(clean_db):
    assert clean_db.check_schema() == SCHEMA_VERSION == 3


def test_expected_tables_exist(clean_db):
    with clean_db.get_connection() as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    names = {r['tablename'] for r in rows}
    assert {
        'videos', 'holds', 'moves', 'environments',
        'outcomes', 'frame_tags', 'schema_version',
    } <= names


def test_rls_enabled_on_every_table(clean_db):
    with clean_db.get_connection() as conn:
        rows = conn.execute(
            "SELECT tablename, rowsecurity FROM pg_tables "
            "WHERE schemaname = 'public'"
        ).fetchall()
    for row in rows:
        assert row['rowsecurity'], f"RLS not enabled on {row['tablename']}"


def test_every_data_table_has_four_policies(clean_db):
    with clean_db.get_connection() as conn:
        rows = conn.execute(
            "SELECT tablename, count(*) AS n FROM pg_policies "
            "WHERE schemaname = 'public' GROUP BY tablename"
        ).fetchall()
    counts = {r['tablename']: r['n'] for r in rows}
    for table in ('videos', 'holds', 'moves', 'environments', 'outcomes', 'frame_tags'):
        assert counts.get(table) == 4, f'{table} has {counts.get(table)} policies'


# ==================== VIDEOS ====================

def test_create_and_get_video(clean_db, user_a):
    video = make_video(user_a)
    video_id = clean_db.create_video(video)
    assert isinstance(video_id, int)

    fetched = clean_db.get_video(video_id, user_a)
    assert fetched.filename == 'climb.mp4'
    assert fetched.fps == pytest.approx(30.0)
    assert fetched.total_frames == 120
    assert fetched.user_id == user_a
    assert fetched.r2_video_key is None
    assert fetched.r2_export_key is None
    assert isinstance(fetched.uploaded_at, datetime)


def test_identity_keys_increment(clean_db, user_a):
    first = clean_db.create_video(make_video(user_a))
    second = clean_db.create_video(make_video(user_a))
    assert second > first


def test_get_video_scoped_to_owner(clean_db, user_a, user_b):
    video_id = clean_db.create_video(make_video(user_a))
    assert clean_db.get_video(video_id, user_a) is not None
    assert clean_db.get_video(video_id, user_b) is None


def test_get_all_videos_only_returns_own(clean_db, user_a, user_b):
    clean_db.create_video(make_video(user_a))
    clean_db.create_video(make_video(user_a))
    clean_db.create_video(make_video(user_b))

    assert len(clean_db.get_all_videos(user_a)) == 2
    assert len(clean_db.get_all_videos(user_b)) == 1


def test_set_video_r2_keys(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))

    assert clean_db.set_video_r2_keys(video_id, user_a, r2_video_key='videos/a/1/x.mp4')
    assert clean_db.set_video_r2_keys(video_id, user_a, r2_export_key='exports/a/1_labeled.csv')

    video = clean_db.get_video(video_id, user_a)
    assert video.r2_video_key == 'videos/a/1/x.mp4'
    assert video.r2_export_key == 'exports/a/1_labeled.csv'
    # Untouched key survives a partial update.
    assert video.r2_pose_csv_key is not None


def test_set_video_r2_keys_rejects_other_user(clean_db, user_a, user_b):
    video_id = clean_db.create_video(make_video(user_a))
    assert clean_db.set_video_r2_keys(video_id, user_b, r2_video_key='x') is False


def test_videos_with_exports(clean_db, user_a):
    with_export = clean_db.create_video(make_video(user_a))
    clean_db.create_video(make_video(user_a))
    clean_db.set_video_r2_keys(with_export, user_a, r2_export_key='exports/a/1_labeled.csv')

    exports = clean_db.get_videos_with_exports(user_a)
    assert [v.id for v in exports] == [with_export]


# ==================== HOLDS ====================

def test_create_and_get_hold(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    hold_id = clean_db.create_hold(make_hold(user_a, video_id, source='detected'))

    hold = clean_db.get_hold(hold_id, user_a)
    assert hold.source == 'detected'
    assert hold.bbox_x == pytest.approx(0.1)
    assert hold.bbox_h == pytest.approx(0.04)
    assert hold.video_id == video_id


def test_hold_bbox_must_be_normalized(clean_db, user_a):
    import psycopg
    video_id = clean_db.create_video(make_video(user_a))
    with pytest.raises(psycopg.errors.CheckViolation):
        clean_db.create_hold(make_hold(user_a, video_id, bbox_x=1.5))


def test_hold_source_is_constrained(clean_db, user_a):
    import psycopg
    video_id = clean_db.create_video(make_video(user_a))
    with pytest.raises(psycopg.errors.CheckViolation):
        clean_db.create_hold(make_hold(user_a, video_id, source='guessed'))


def test_holds_scoped_to_owner(clean_db, user_a, user_b):
    video_id = clean_db.create_video(make_video(user_a))
    hold_id = clean_db.create_hold(make_hold(user_a, video_id))

    assert clean_db.get_hold(hold_id, user_b) is None
    assert clean_db.get_holds_for_video(video_id, user_b) == []
    assert clean_db.delete_hold(hold_id, user_b) is False
    assert clean_db.delete_hold(hold_id, user_a) is True


# ==================== MOVES ====================

def test_move_tags_round_trip_as_jsonb(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))

    move = clean_db.get_move(move_id, user_a)
    assert move.move_tags == ['dyno', 'tension']
    assert move.approach == 'dynamic'
    assert move.confidence == 'high'
    assert move.form_quality == 4


def test_move_tags_stored_as_real_jsonb(clean_db, user_a):
    """Not a JSON string in a text column - the column must be queryable."""
    video_id = clean_db.create_video(make_video(user_a))
    clean_db.create_move(make_move(user_a, video_id))

    with clean_db.get_connection() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM moves WHERE move_tags @> '[\"dyno\"]'::jsonb"
        ).fetchone()
    assert row['n'] == 1


def test_update_move(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))

    move = clean_db.get_move(move_id, user_a)
    move.approach = 'static'
    move.move_tags = ['balance', 'technical']
    move.effort_level = 2
    assert clean_db.update_move(move)

    updated = clean_db.get_move(move_id, user_a)
    assert updated.approach == 'static'
    assert updated.move_tags == ['balance', 'technical']
    assert updated.effort_level == 2


def test_update_move_rejects_other_user(clean_db, user_a, user_b):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))

    move = clean_db.get_move(move_id, user_a)
    move.user_id = user_b
    move.approach = 'static'
    assert clean_db.update_move(move) is False
    assert clean_db.get_move(move_id, user_a).approach == 'dynamic'


def test_moves_scoped_to_owner(clean_db, user_a, user_b):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))

    assert clean_db.get_move(move_id, user_b) is None
    assert clean_db.get_moves_for_video(video_id, user_b) == []


def test_delete_move_cascades_children(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))
    clean_db.create_outcome(Outcome(move_id=move_id, user_id=user_a, result='fall',
                                    reach_detail='didnt_reach', confidence='low'))
    clean_db.create_frame_tag(FrameTag(move_id=move_id, user_id=user_a, frame_number=12,
                                       timestamp_ms=400.0, tag_type='sharp_pain',
                                       level=7, locations=['left_shoulder']))

    assert clean_db.delete_move(move_id, user_a)
    assert clean_db.get_move(move_id, user_a) is None
    assert clean_db.get_outcome_for_move(move_id, user_a) is None
    assert clean_db.get_frame_tags_for_move(move_id, user_a) == []


def test_delete_move_rejects_other_user(clean_db, user_a, user_b):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))

    assert clean_db.delete_move(move_id, user_b) is False
    assert clean_db.get_move(move_id, user_a) is not None


# ==================== ENVIRONMENTS ====================

def test_environment_all_four_slots(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))
    holds = {
        slot: clean_db.create_hold(make_hold(user_a, video_id))
        for slot in HOLD_SLOTS
    }

    env = Environment(move_id=move_id, user_id=user_a, wall_angle='steep')
    for slot in HOLD_SLOTS:
        setattr(env, f'{slot}_hold_id', holds[slot])
        setattr(env, f'{slot}_hold_type', 'jug')
        setattr(env, f'{slot}_hold_quality', ['incut', 'small'])
    env_id = clean_db.create_environment(env)

    fetched = clean_db.get_environment(env_id, user_a)
    assert fetched.wall_angle == 'steep'
    for slot in HOLD_SLOTS:
        assert getattr(fetched, f'{slot}_hold_id') == holds[slot]
        assert getattr(fetched, f'{slot}_hold_type') == 'jug'
        assert getattr(fetched, f'{slot}_hold_quality') == ['incut', 'small']


def test_environment_foot_slot_is_optional(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))

    env = Environment(move_id=move_id, user_id=user_a, wall_angle='slab')
    env_id = clean_db.create_environment(env)

    fetched = clean_db.get_environment(env_id, user_a)
    assert fetched.foot_hold_id is None
    assert fetched.foot_hold_type is None
    assert fetched.foot_hold_quality == []


def test_environment_one_per_move(clean_db, user_a):
    import psycopg
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))

    clean_db.create_environment(Environment(move_id=move_id, user_id=user_a, wall_angle='slab'))
    with pytest.raises(psycopg.errors.UniqueViolation):
        clean_db.create_environment(
            Environment(move_id=move_id, user_id=user_a, wall_angle='steep')
        )


def test_update_environment_clears_a_slot(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))
    hold_id = clean_db.create_hold(make_hold(user_a, video_id))

    env = Environment(move_id=move_id, user_id=user_a, wall_angle='vertical',
                      foot_hold_id=hold_id, foot_hold_type='pinch',
                      foot_hold_quality=['small'])
    env.id = clean_db.create_environment(env)

    env.foot_hold_id = None
    env.foot_hold_type = None
    env.foot_hold_quality = []
    assert clean_db.update_environment(env)

    fetched = clean_db.get_environment_for_move(move_id, user_a)
    assert fetched.foot_hold_id is None
    assert fetched.foot_hold_quality == []


def test_environment_scoped_to_owner(clean_db, user_a, user_b):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))
    env_id = clean_db.create_environment(
        Environment(move_id=move_id, user_id=user_a, wall_angle='slab')
    )

    assert clean_db.get_environment(env_id, user_b) is None
    assert clean_db.get_environment_for_move(move_id, user_b) is None


# ==================== OUTCOMES ====================

def test_create_and_get_outcome(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))
    outcome_id = clean_db.create_outcome(
        Outcome(move_id=move_id, user_id=user_a, result='success',
                reach_detail='reached_controlled', confidence='med')
    )

    outcome = clean_db.get_outcome(outcome_id, user_a)
    assert outcome.result == 'success'
    assert outcome.reach_detail == 'reached_controlled'
    assert outcome.confidence == 'med'
    # foot_cut is gone in v3.
    assert not hasattr(outcome, 'foot_cut')


def test_outcome_scoped_to_owner(clean_db, user_a, user_b):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))
    outcome_id = clean_db.create_outcome(
        Outcome(move_id=move_id, user_id=user_a, result='fall',
                reach_detail='didnt_reach', confidence='low')
    )

    assert clean_db.get_outcome(outcome_id, user_b) is None
    assert clean_db.get_outcome_for_move(move_id, user_b) is None
    assert clean_db.delete_outcome(outcome_id, user_b) is False


# ==================== FRAME TAGS ====================

def test_frame_tag_locations_round_trip(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))
    tag_id = clean_db.create_frame_tag(
        FrameTag(move_id=move_id, user_id=user_a, frame_number=15, timestamp_ms=500.0,
                 tag_type='sharp_pain', side='left', level=8,
                 locations=['left_shoulder', 'left_elbow'], note='caught the edge')
    )

    tag = clean_db.get_frame_tag(tag_id, user_a)
    assert tag.locations == ['left_shoulder', 'left_elbow']
    assert tag.side == 'left'
    assert tag.level == 8
    assert tag.note == 'caught the edge'
    assert tag.is_sensation_tag()


def test_frame_tag_level_is_bounded(clean_db, user_a):
    import psycopg
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))
    with pytest.raises(psycopg.errors.CheckViolation):
        clean_db.create_frame_tag(
            FrameTag(move_id=move_id, user_id=user_a, frame_number=1,
                     timestamp_ms=1.0, tag_type='dull_pain', level=99)
        )


def test_frame_tags_ordered_by_frame(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))
    for frame in (18, 11, 14):
        clean_db.create_frame_tag(
            FrameTag(move_id=move_id, user_id=user_a, frame_number=frame,
                     timestamp_ms=float(frame) * 33, tag_type='pumped')
        )

    tags = clean_db.get_frame_tags_for_move(move_id, user_a)
    assert [t.frame_number for t in tags] == [11, 14, 18]


def test_frame_tag_scoped_to_owner(clean_db, user_a, user_b):
    video_id = clean_db.create_video(make_video(user_a))
    move_id = clean_db.create_move(make_move(user_a, video_id))
    tag_id = clean_db.create_frame_tag(
        FrameTag(move_id=move_id, user_id=user_a, frame_number=12,
                 timestamp_ms=400.0, tag_type='weak')
    )

    assert clean_db.get_frame_tag(tag_id, user_b) is None
    assert clean_db.get_frame_tags_for_move(move_id, user_b) == []
    assert clean_db.delete_frame_tag(tag_id, user_b) is False
    assert clean_db.delete_frame_tag(tag_id, user_a) is True


# ==================== POSE STATUS (20260922130000_pose_status.sql) ====================

def test_new_video_starts_pending(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    video = clean_db.get_video(video_id, user_a)
    assert video.pose_status == 'pending'
    assert video.pose_error is None
    assert video.pose_started_at is None
    assert video.pose_finished_at is None


def test_set_pose_status_stamps_timestamps(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))

    assert clean_db.set_pose_status(video_id, 'processing', user_id=user_a)
    video = clean_db.get_video(video_id, user_a)
    assert video.pose_status == 'processing'
    assert video.pose_started_at is not None
    assert video.pose_finished_at is None

    assert clean_db.set_pose_status(video_id, 'failed', 'gpu hiccup', user_id=user_a)
    video = clean_db.get_video(video_id, user_a)
    assert video.pose_status == 'failed'
    assert video.pose_error == 'gpu hiccup'
    assert video.pose_finished_at is not None

    # A retry clears the error and both stamps.
    assert clean_db.set_pose_status(video_id, 'pending', user_id=user_a)
    video = clean_db.get_video(video_id, user_a)
    assert video.pose_status == 'pending'
    assert video.pose_error is None
    assert video.pose_started_at is None and video.pose_finished_at is None


def test_set_pose_status_is_scoped_when_a_user_is_given(clean_db, user_a, user_b):
    video_id = clean_db.create_video(make_video(user_a))
    assert clean_db.set_pose_status(video_id, 'failed', 'x', user_id=user_b) is False
    assert clean_db.get_video(video_id, user_a).pose_status == 'pending'


def test_set_pose_status_rejects_unknown_status(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    with pytest.raises(ValueError):
        clean_db.set_pose_status(video_id, 'sideways')


def test_record_pose_result_overwrites_provisional_metadata(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a, fps=30.0, total_frames=90, duration_ms=3000.0))

    assert clean_db.record_pose_result(
        video_id, 'done', fps=60.0, total_frames=180, duration_ms=3001.5,
        width=1080, height=1920, r2_pose_csv_key=f'pose/{user_a}/{video_id}.csv',
    )
    video = clean_db.get_video(video_id, user_a)
    assert video.pose_status == 'done'
    assert video.fps == 60.0
    assert video.total_frames == 180
    assert video.duration_ms == pytest.approx(3001.5)
    assert video.width == 1080 and video.height == 1920
    assert video.r2_pose_csv_key == f'pose/{user_a}/{video_id}.csv'
    assert video.pose_finished_at is not None


def test_record_pose_result_unknown_video_is_false(clean_db):
    assert clean_db.record_pose_result(999999, 'processing') is False


def test_pose_status_check_constraint(clean_db, user_a):
    video_id = clean_db.create_video(make_video(user_a))
    with pytest.raises(psycopg.errors.CheckViolation):
        with clean_db.get_connection() as conn:
            conn.execute("UPDATE videos SET pose_status = 'bogus' WHERE id = %s", (video_id,))


def test_pose_status_migration_backfills_existing_csvs(db, user_a):
    """A row that already had a browser-extracted CSV must read as done."""
    migrations = sorted(
        Path(__file__).resolve().parents[1].glob('supabase/migrations/*.sql')
    )
    pose_migration = [m for m in migrations if m.name.endswith('_pose_status.sql')]
    assert len(pose_migration) == 1
    before = [m for m in migrations if m < pose_migration[0]]

    # Rebuild the schema as it was before the pose migration. Like
    # apply_schema_sql, drop the Dataset A tables first: they are CREATE TABLE
    # IF NOT EXISTS and the rater bio migration (after the pose one) reshapes
    # rater_profiles, so a partial replay on the live schema would not apply.
    with db.get_connection() as conn:
        conn.execute('DROP TABLE IF EXISTS public.video_assignments CASCADE')
        conn.execute('DROP TABLE IF EXISTS public.rater_profiles CASCADE')
        for path in before:
            conn.execute(path.read_text())
        row = conn.execute(
            '''INSERT INTO videos (user_id, filename, fps, total_frames, duration_ms, r2_pose_csv_key)
               VALUES (%s, 'old.mp4', 30, 3, 100, %s) RETURNING id''',
            (user_a, f'pose/{user_a}/1.csv'),
        ).fetchone()
        old_id = row['id']
        conn.execute(
            '''INSERT INTO videos (user_id, filename, fps, total_frames, duration_ms)
               VALUES (%s, 'never-extracted.mp4', 30, 3, 100)''',
            (user_a,),
        )
    try:
        # ...then apply it and check the backfill.
        with db.get_connection() as conn:
            conn.execute(pose_migration[0].read_text())
        done = db.get_video(old_id, user_a)
        assert done.pose_status == 'done'
        assert done.pose_finished_at is not None
        pending = [v for v in db.get_all_videos(user_a) if v.filename == 'never-extracted.mp4'][0]
        assert pending.pose_status == 'pending'
    finally:
        # Leave the session-scoped schema exactly as the other tests expect.
        db.apply_schema_sql()
