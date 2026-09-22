"""
Database layer for labeling system.

Handles all Postgres operations against Supabase via psycopg v3. Models know
nothing about the database. Raw SQL throughout - no ORM.

Schema version 3: per-user scoping, holds with normalized bounding boxes,
slot-based environments, R2 object keys instead of local paths.

DDL lives in supabase/migrations/*.sql (the v3 base plus additive migrations,
applied in filename order), which is the single source of truth. This module
never creates tables outside of apply_schema_sql(), which exists so tests can
build a fresh schema without the Supabase CLI.
"""
import os
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .models import (
    Video, Hold, Move, Environment, Outcome, FrameTag,
    RaterProfile, VideoAssignment, HOLD_SLOTS,
)

SCHEMA_VERSION = 3


class SchemaNotApplied(RuntimeError):
    """Raised when the database has not had the v3 migration applied."""


class Database:
    """
    Database handler with clean separation of concerns.

    Every read, update and delete is scoped by user_id so one climber can never
    reach another's rows even if they guess an id. Create takes the user_id off
    the model instance.

    Dataset A (runbook W1) adds a second family of accessors suffixed ``_any``
    that are NOT scoped by user. They exist for two callers only: the admin
    role, and the API's access check (``_require_video_access``) once it has
    already established that the caller is the owner, an assigned rater or an
    admin of the video in question. Never reach for an ``_any`` method before
    that check has run.

    Usage:
        db = Database()            # reads DATABASE_URL from the environment
        db.check_schema()

        video_id = db.create_video(video)
        video = db.get_video(video_id, user_id)
        moves = db.get_moves_for_video(video_id, user_id)
    """

    def __init__(self, dsn: Optional[str] = None, min_size: int = 1, max_size: int = 5):
        """Initialize the connection pool.

        Args:
            dsn: Postgres connection string. Defaults to $DATABASE_URL.
            min_size/max_size: pool bounds. Small by default because Railway
                runs a single container and Supabase's pooler charges per
                connection.
        """
        self.dsn = dsn or os.environ.get('DATABASE_URL')
        if not self.dsn:
            raise RuntimeError(
                'DATABASE_URL is not set. Point it at the Supabase Postgres '
                'connection string (session or transaction pooler).'
            )
        self.pool = ConnectionPool(
            self.dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={'row_factory': dict_row},
            configure=self._configure_connection,
            open=True,
        )

    @staticmethod
    def _configure_connection(conn):
        """Prepare each pooled connection.

        Supabase's transaction pooler (pgbouncer, port 6543) multiplexes
        connections per transaction, so a prepared statement created on one
        backend is not there on the next - psycopg3's automatic prepared
        statements raise DuplicatePreparedStatement against it. Disabling the
        threshold keeps every statement unprepared, which is what the pooler
        requires. Harmless on a direct connection.
        """
        conn.prepare_threshold = None

    def close(self):
        """Close the pool. Call on application shutdown."""
        self.pool.close()

    @contextmanager
    def get_connection(self):
        """Context manager for pooled connections, committing on clean exit."""
        with self.pool.connection() as conn:
            # psycopg commits on clean block exit and rolls back on exception.
            yield conn

    # ==================== SCHEMA ====================

    def check_schema(self) -> int:
        """Return the applied schema version, raising if the migration is missing."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT MAX(version) AS version FROM schema_version')
                row = cursor.fetchone()
        except psycopg.errors.UndefinedTable as exc:
            raise SchemaNotApplied(
                'schema_version table is missing - apply '
                'supabase/migrations/*_schema_v3.sql before starting the API.'
            ) from exc

        version = row['version'] if row and row['version'] is not None else 0
        if version != SCHEMA_VERSION:
            raise SchemaNotApplied(
                f'Database is at schema version {version}, expected {SCHEMA_VERSION}.'
            )
        return version

    def get_schema_version(self) -> int:
        """Get the current schema version, or 0 when nothing is applied."""
        try:
            return self.check_schema()
        except SchemaNotApplied:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT to_regclass('public.schema_version') AS t"
                )
                if not cursor.fetchone()['t']:
                    return 0
                cursor.execute('SELECT MAX(version) AS version FROM schema_version')
                row = cursor.fetchone()
                return row['version'] if row and row['version'] is not None else 0

    def apply_schema_sql(self, sql_path: Optional[str] = None):
        """Execute the migrations, in filename order.

        Used by the test suite to build a fresh schema. Production applies the
        same files through `supabase db push`.

        Applies every migration rather than only the base schema: additive
        migrations land in their own files, and a test database built from the
        base alone would be missing their columns.
        """
        if sql_path is not None:
            paths = [Path(sql_path)]
        else:
            paths = sorted(
                Path(__file__).resolve().parents[2].glob('supabase/migrations/*.sql')
            )
            if not paths:
                raise FileNotFoundError('No migrations found under supabase/migrations/')

        with self.get_connection() as conn:
            for path in paths:
                conn.execute(path.read_text())

    # ==================== VIDEO OPERATIONS ====================

    def create_video(self, video: Video) -> int:
        """Create a new video record. Returns video_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO videos (
                    user_id, filename, fps, total_frames, duration_ms,
                    width, height,
                    r2_video_key, r2_pose_csv_key, r2_export_key, uploaded_at,
                    dataset, prep_status,
                    route_grade, wall_type, climber_experience,
                    climber_height_cm, climber_ape_index_cm, camera_angle, gym, notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (
                video.user_id,
                video.filename,
                video.fps,
                video.total_frames,
                video.duration_ms,
                video.width,
                video.height,
                video.r2_video_key,
                video.r2_pose_csv_key,
                video.r2_export_key,
                video.uploaded_at or datetime.now(timezone.utc),
                video.dataset or 'B',
                video.prep_status or 'draft',
                video.route_grade,
                video.wall_type,
                video.climber_experience,
                video.climber_height_cm,
                video.climber_ape_index_cm,
                video.camera_angle,
                video.gym,
                video.notes,
            ))
            return cursor.fetchone()['id']

    # Prep-pass fields an admin may set through update_video_fields().
    VIDEO_PREP_FIELDS = (
        'dataset', 'prep_status',
        'route_grade', 'wall_type', 'climber_experience',
        'climber_height_cm', 'climber_ape_index_cm', 'camera_angle', 'gym', 'notes',
    )

    def get_video_any(self, video_id: int) -> Optional[Video]:
        """Get a video by ID regardless of owner. Admin / post-access-check only."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM videos WHERE id = %s', (video_id,))
            row = cursor.fetchone()
            return self._row_to_video(row) if row else None

    def list_videos_admin(self) -> List[dict]:
        """Every video with its assignment count, newest first. Admin only.

        Returns dicts: {'video': Video, 'assignment_count': int,
        'done_count': int} so the admin view can show progress without a
        request per video.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT v.*,
                       COUNT(a.id)                                   AS assignment_count,
                       COUNT(a.id) FILTER (WHERE a.status = 'done') AS done_count
                FROM videos v
                LEFT JOIN video_assignments a ON a.video_id = v.id
                GROUP BY v.id
                ORDER BY v.uploaded_at DESC
            ''')
            return [
                {
                    'video': self._row_to_video(row),
                    'assignment_count': int(row['assignment_count']),
                    'done_count': int(row['done_count']),
                }
                for row in cursor.fetchall()
            ]

    def update_video_fields(self, video_id: int, **fields) -> Optional[Video]:
        """Set prep-pass fields on any video. Admin only. Returns the row, or None.

        Only VIDEO_PREP_FIELDS may change; a None value is a no-op for that
        field (nullable metadata is cleared by passing an empty string, which
        is stored as NULL).
        """
        updates = {}
        for key, value in fields.items():
            if key not in self.VIDEO_PREP_FIELDS or value is None:
                continue
            if isinstance(value, str) and value == '' and key not in ('dataset', 'prep_status'):
                value = None
            updates[key] = value
        if not updates:
            return self.get_video_any(video_id)

        assignments = ', '.join(f'{k} = %s' for k in updates)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE videos SET {assignments} WHERE id = %s RETURNING *',
                (*updates.values(), video_id)
            )
            row = cursor.fetchone()
            return self._row_to_video(row) if row else None

    def get_videos_for_export(
        self,
        video_id: Optional[int] = None,
        dataset: Optional[str] = None,
    ) -> List[Video]:
        """Videos across every owner, for the admin exports."""
        clauses, params = [], []
        if video_id is not None:
            clauses.append('id = %s')
            params.append(video_id)
        if dataset:
            clauses.append('dataset = %s')
            params.append(dataset)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'SELECT * FROM videos {where} ORDER BY id', tuple(params))
            return [self._row_to_video(row) for row in cursor.fetchall()]

    def get_video(self, video_id: int, user_id: str) -> Optional[Video]:
        """Get one of this user's videos by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM videos WHERE id = %s AND user_id = %s',
                (video_id, user_id)
            )
            row = cursor.fetchone()
            return self._row_to_video(row) if row else None

    def get_all_videos(self, user_id: str) -> List[Video]:
        """Get all of this user's videos, newest first."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM videos WHERE user_id = %s ORDER BY uploaded_at DESC',
                (user_id,)
            )
            return [self._row_to_video(row) for row in cursor.fetchall()]

    def set_video_r2_keys(
        self,
        video_id: int,
        user_id: str,
        r2_video_key: Optional[str] = None,
        r2_pose_csv_key: Optional[str] = None,
        r2_export_key: Optional[str] = None,
    ) -> bool:
        """Record one or more R2 keys on a video. Only the keys passed are written."""
        sets, params = [], []
        for column, value in (
            ('r2_video_key', r2_video_key),
            ('r2_pose_csv_key', r2_pose_csv_key),
            ('r2_export_key', r2_export_key),
        ):
            if value is not None:
                sets.append(f'{column} = %s')
                params.append(value)
        if not sets:
            return False

        params.extend([video_id, user_id])
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE videos SET {", ".join(sets)} WHERE id = %s AND user_id = %s',
                tuple(params)
            )
            return cursor.rowcount > 0

    def get_videos_with_exports(self, user_id: str) -> List[Video]:
        """Get this user's videos that have an export stored in R2."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM videos WHERE user_id = %s AND r2_export_key IS NOT NULL '
                'ORDER BY uploaded_at DESC',
                (user_id,)
            )
            return [self._row_to_video(row) for row in cursor.fetchall()]

    # ==================== HOLD OPERATIONS ====================

    def create_hold(self, hold: Hold) -> int:
        """Create a new hold. Returns hold_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO holds (
                    video_id, user_id, bbox_x, bbox_y, bbox_w, bbox_h, source, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (
                hold.video_id,
                hold.user_id,
                hold.bbox_x,
                hold.bbox_y,
                hold.bbox_w,
                hold.bbox_h,
                hold.source,
                hold.created_at or datetime.now(timezone.utc),
            ))
            return cursor.fetchone()['id']

    def create_holds_bulk(self, holds: List[Hold]) -> List[int]:
        """Create many holds in one transaction. Returns the new ids, in order.

        The detector posts a whole frame's worth of boxes at once. Doing that
        in a single transaction means a partial failure leaves no holds behind
        rather than half a wall.
        """
        if not holds:
            return []

        now = datetime.now(timezone.utc)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            ids = []
            for hold in holds:
                cursor.execute(
                    'INSERT INTO holds ('
                    ' video_id, user_id, bbox_x, bbox_y, bbox_w, bbox_h, source, created_at'
                    ') VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id',
                    (
                        hold.video_id, hold.user_id, hold.bbox_x, hold.bbox_y,
                        hold.bbox_w, hold.bbox_h, hold.source, hold.created_at or now,
                    )
                )
                ids.append(cursor.fetchone()['id'])
            return ids

    def update_hold(self, hold_id: int, user_id: str, **fields) -> Optional[Hold]:
        """Update one of this user's holds. Returns the updated hold, or None.

        Only the box and the source can move. video_id and user_id are fixed at
        creation, so a hold can never be re-pointed at another user's video.
        """
        allowed = ('bbox_x', 'bbox_y', 'bbox_w', 'bbox_h', 'source')
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return self.get_hold(hold_id, user_id)

        assignments = ', '.join(f'{k} = %s' for k in updates)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE holds SET {assignments} WHERE id = %s AND user_id = %s RETURNING *',
                (*updates.values(), hold_id, user_id)
            )
            row = cursor.fetchone()
            return self._row_to_hold(row) if row else None

    def get_hold_any(self, hold_id: int) -> Optional[Hold]:
        """Get a hold by ID regardless of creator. Post-access-check only."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM holds WHERE id = %s', (hold_id,))
            row = cursor.fetchone()
            return self._row_to_hold(row) if row else None

    def get_holds_for_video_any(self, video_id: int) -> List[Hold]:
        """Every hold on a video, whoever drew it. Post-access-check only."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM holds WHERE video_id = %s ORDER BY id', (video_id,)
            )
            return [self._row_to_hold(row) for row in cursor.fetchall()]

    def update_hold_any(self, hold_id: int, **fields) -> Optional[Hold]:
        """update_hold without the user filter. Admin only."""
        allowed = ('bbox_x', 'bbox_y', 'bbox_w', 'bbox_h', 'source')
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return self.get_hold_any(hold_id)
        assignments = ', '.join(f'{k} = %s' for k in updates)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE holds SET {assignments} WHERE id = %s RETURNING *',
                (*updates.values(), hold_id)
            )
            row = cursor.fetchone()
            return self._row_to_hold(row) if row else None

    def delete_hold_any(self, hold_id: int) -> bool:
        """delete_hold without the user filter. Admin only."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM holds WHERE id = %s', (hold_id,))
            return cursor.rowcount > 0

    def get_hold(self, hold_id: int, user_id: str) -> Optional[Hold]:
        """Get one of this user's holds by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM holds WHERE id = %s AND user_id = %s',
                (hold_id, user_id)
            )
            row = cursor.fetchone()
            return self._row_to_hold(row) if row else None

    def get_holds_for_video(self, video_id: int, user_id: str) -> List[Hold]:
        """Get all holds marked on a video."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM holds WHERE video_id = %s AND user_id = %s ORDER BY id',
                (video_id, user_id)
            )
            return [self._row_to_hold(row) for row in cursor.fetchall()]

    def delete_hold(self, hold_id: int, user_id: str) -> bool:
        """Delete a hold. Returns success."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM holds WHERE id = %s AND user_id = %s',
                (hold_id, user_id)
            )
            return cursor.rowcount > 0

    # ==================== MOVE OPERATIONS ====================

    def create_move(self, move: Move) -> int:
        """Create a new move. Returns move_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO moves (
                    video_id, user_id, frame_start, frame_end,
                    timestamp_start_ms, timestamp_end_ms,
                    approach, move_tags, size, form_quality, effort_level,
                    confidence, description, labeled_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (
                move.video_id,
                move.user_id,
                move.frame_start,
                move.frame_end,
                move.timestamp_start_ms,
                move.timestamp_end_ms,
                move.approach,
                Jsonb(move.move_tags),
                move.size,
                move.form_quality,
                move.effort_level,
                move.confidence,
                move.description,
                move.labeled_at or datetime.now(timezone.utc),
            ))
            return cursor.fetchone()['id']

    def get_move_any(self, move_id: int) -> Optional[Move]:
        """Get a move by ID regardless of creator. Post-access-check only."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM moves WHERE id = %s', (move_id,))
            row = cursor.fetchone()
            return self._row_to_move(row) if row else None

    def get_moves_for_video_any(self, video_id: int) -> List[Move]:
        """The canonical move list of a video, whoever created it.

        Ordered by frame_start, then id, which is also the order that defines
        move_index in the long export.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM moves WHERE video_id = %s ORDER BY frame_start, id',
                (video_id,)
            )
            return [self._row_to_move(row) for row in cursor.fetchall()]

    def update_move_any(self, move: Move) -> bool:
        """update_move without the user filter. Admin only."""
        if not move.id:
            return False
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE moves SET
                    frame_start = %s, frame_end = %s,
                    timestamp_start_ms = %s, timestamp_end_ms = %s,
                    approach = %s, move_tags = %s, size = %s,
                    form_quality = %s, effort_level = %s,
                    confidence = %s, description = %s
                WHERE id = %s
            ''', (
                move.frame_start, move.frame_end,
                move.timestamp_start_ms, move.timestamp_end_ms,
                move.approach, Jsonb(move.move_tags), move.size,
                move.form_quality, move.effort_level,
                move.confidence, move.description,
                move.id,
            ))
            return cursor.rowcount > 0

    def delete_move_any(self, move_id: int) -> bool:
        """delete_move without the user filter. Admin only.

        Every rater's environment / outcome / frame_tag rows on the move go
        with it (FKs are ON DELETE CASCADE from moves).
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM moves WHERE id = %s', (move_id,))
            return cursor.rowcount > 0

    def get_move(self, move_id: int, user_id: str) -> Optional[Move]:
        """Get one of this user's moves by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM moves WHERE id = %s AND user_id = %s',
                (move_id, user_id)
            )
            row = cursor.fetchone()
            return self._row_to_move(row) if row else None

    def get_moves_for_video(self, video_id: int, user_id: str) -> List[Move]:
        """Get all moves for a video."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM moves WHERE video_id = %s AND user_id = %s ORDER BY frame_start',
                (video_id, user_id)
            )
            return [self._row_to_move(row) for row in cursor.fetchall()]

    def update_move(self, move: Move) -> bool:
        """Update an existing move. Returns success."""
        if not move.id:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE moves SET
                    frame_start = %s,
                    frame_end = %s,
                    timestamp_start_ms = %s,
                    timestamp_end_ms = %s,
                    approach = %s,
                    move_tags = %s,
                    size = %s,
                    form_quality = %s,
                    effort_level = %s,
                    confidence = %s,
                    description = %s
                WHERE id = %s AND user_id = %s
            ''', (
                move.frame_start,
                move.frame_end,
                move.timestamp_start_ms,
                move.timestamp_end_ms,
                move.approach,
                Jsonb(move.move_tags),
                move.size,
                move.form_quality,
                move.effort_level,
                move.confidence,
                move.description,
                move.id,
                move.user_id,
            ))
            return cursor.rowcount > 0

    def delete_move(self, move_id: int, user_id: str) -> bool:
        """Delete a move and its related records. Returns success."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Children first - the FKs are not ON DELETE CASCADE so that a
            # partial delete can never orphan a row behind a user's back.
            cursor.execute(
                'DELETE FROM frame_tags WHERE move_id = %s AND user_id = %s',
                (move_id, user_id)
            )
            cursor.execute(
                'DELETE FROM environments WHERE move_id = %s AND user_id = %s',
                (move_id, user_id)
            )
            cursor.execute(
                'DELETE FROM outcomes WHERE move_id = %s AND user_id = %s',
                (move_id, user_id)
            )
            cursor.execute(
                'DELETE FROM moves WHERE id = %s AND user_id = %s',
                (move_id, user_id)
            )
            return cursor.rowcount > 0

    # ==================== ENVIRONMENT OPERATIONS ====================

    def create_environment(self, env: Environment) -> int:
        """Create a new environment record. Returns environment_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO environments (
                    move_id, user_id, wall_angle,
                    start_left_hold_id, start_left_hold_type, start_left_hold_quality,
                    start_right_hold_id, start_right_hold_type, start_right_hold_quality,
                    end_hold_id, end_hold_type, end_hold_quality,
                    foot_hold_id, foot_hold_type, foot_hold_quality,
                    taxonomy_version, is_gold
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (
                env.move_id,
                env.user_id,
                env.wall_angle,
                env.start_left_hold_id,
                env.start_left_hold_type,
                Jsonb(env.start_left_hold_quality),
                env.start_right_hold_id,
                env.start_right_hold_type,
                Jsonb(env.start_right_hold_quality),
                env.end_hold_id,
                env.end_hold_type,
                Jsonb(env.end_hold_quality),
                env.foot_hold_id,
                env.foot_hold_type,
                Jsonb(env.foot_hold_quality),
                env.taxonomy_version,
                env.is_gold,
            ))
            return cursor.fetchone()['id']

    def get_environments_for_move_all(self, move_id: int) -> List[Environment]:
        """Every rater's environment on a move. Admin export only."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM environments WHERE move_id = %s ORDER BY user_id', (move_id,)
            )
            return [self._row_to_environment(row) for row in cursor.fetchall()]

    def get_environment(self, env_id: int, user_id: str) -> Optional[Environment]:
        """Get an environment by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM environments WHERE id = %s AND user_id = %s',
                (env_id, user_id)
            )
            row = cursor.fetchone()
            return self._row_to_environment(row) if row else None

    def get_environment_for_move(self, move_id: int, user_id: str) -> Optional[Environment]:
        """Get the environment for a move."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM environments WHERE move_id = %s AND user_id = %s',
                (move_id, user_id)
            )
            row = cursor.fetchone()
            return self._row_to_environment(row) if row else None

    def update_environment(self, env: Environment) -> bool:
        """Update an existing environment. Returns success."""
        if not env.id:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE environments SET
                    wall_angle = %s,
                    start_left_hold_id = %s,
                    start_left_hold_type = %s,
                    start_left_hold_quality = %s,
                    start_right_hold_id = %s,
                    start_right_hold_type = %s,
                    start_right_hold_quality = %s,
                    end_hold_id = %s,
                    end_hold_type = %s,
                    end_hold_quality = %s,
                    foot_hold_id = %s,
                    foot_hold_type = %s,
                    foot_hold_quality = %s,
                    taxonomy_version = %s
                WHERE id = %s AND user_id = %s
            ''', (
                env.wall_angle,
                env.start_left_hold_id,
                env.start_left_hold_type,
                Jsonb(env.start_left_hold_quality),
                env.start_right_hold_id,
                env.start_right_hold_type,
                Jsonb(env.start_right_hold_quality),
                env.end_hold_id,
                env.end_hold_type,
                Jsonb(env.end_hold_quality),
                env.foot_hold_id,
                env.foot_hold_type,
                Jsonb(env.foot_hold_quality),
                env.taxonomy_version,
                env.id,
                env.user_id,
            ))
            return cursor.rowcount > 0

    def delete_environment(self, env_id: int, user_id: str) -> bool:
        """Delete an environment. Returns success."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM environments WHERE id = %s AND user_id = %s',
                (env_id, user_id)
            )
            return cursor.rowcount > 0

    # ==================== OUTCOME OPERATIONS ====================

    def create_outcome(self, outcome: Outcome) -> int:
        """Create a new outcome record. Returns outcome_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO outcomes (
                    move_id, user_id, result, reach_detail, confidence,
                    taxonomy_version, is_gold
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (
                outcome.move_id,
                outcome.user_id,
                outcome.result,
                outcome.reach_detail,
                outcome.confidence,
                outcome.taxonomy_version,
                outcome.is_gold,
            ))
            return cursor.fetchone()['id']

    def get_outcomes_for_move_all(self, move_id: int) -> List[Outcome]:
        """Every rater's outcome on a move. Admin export only."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM outcomes WHERE move_id = %s ORDER BY user_id', (move_id,)
            )
            return [self._row_to_outcome(row) for row in cursor.fetchall()]

    def get_outcome(self, outcome_id: int, user_id: str) -> Optional[Outcome]:
        """Get an outcome by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM outcomes WHERE id = %s AND user_id = %s',
                (outcome_id, user_id)
            )
            row = cursor.fetchone()
            return self._row_to_outcome(row) if row else None

    def get_outcome_for_move(self, move_id: int, user_id: str) -> Optional[Outcome]:
        """Get the outcome for a move."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM outcomes WHERE move_id = %s AND user_id = %s',
                (move_id, user_id)
            )
            row = cursor.fetchone()
            return self._row_to_outcome(row) if row else None

    def update_outcome(self, outcome: Outcome) -> bool:
        """Update an existing outcome. Returns success."""
        if not outcome.id:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE outcomes SET
                    result = %s,
                    reach_detail = %s,
                    confidence = %s,
                    taxonomy_version = %s
                WHERE id = %s AND user_id = %s
            ''', (
                outcome.result,
                outcome.reach_detail,
                outcome.confidence,
                outcome.taxonomy_version,
                outcome.id,
                outcome.user_id,
            ))
            return cursor.rowcount > 0

    def delete_outcome(self, outcome_id: int, user_id: str) -> bool:
        """Delete an outcome. Returns success."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM outcomes WHERE id = %s AND user_id = %s',
                (outcome_id, user_id)
            )
            return cursor.rowcount > 0

    # ==================== FRAME TAG OPERATIONS ====================

    def create_frame_tag(self, tag: FrameTag) -> int:
        """Create a new frame tag. Returns tag_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO frame_tags (
                    move_id, user_id, frame_number, timestamp_ms,
                    tag_type, side, level, locations, note, tagged_at,
                    taxonomy_version, is_gold
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (
                tag.move_id,
                tag.user_id,
                tag.frame_number,
                tag.timestamp_ms,
                tag.tag_type,
                tag.side,
                tag.level,
                Jsonb(tag.locations),
                tag.note,
                tag.tagged_at or datetime.now(timezone.utc),
                tag.taxonomy_version,
                tag.is_gold,
            ))
            return cursor.fetchone()['id']

    def get_frame_tags_for_move_all(self, move_id: int) -> List[FrameTag]:
        """Every rater's frame tags on a move. Admin export only."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM frame_tags WHERE move_id = %s ORDER BY user_id, frame_number, id',
                (move_id,)
            )
            return [self._row_to_frame_tag(row) for row in cursor.fetchall()]

    def get_frame_tag(self, tag_id: int, user_id: str) -> Optional[FrameTag]:
        """Get a frame tag by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM frame_tags WHERE id = %s AND user_id = %s',
                (tag_id, user_id)
            )
            row = cursor.fetchone()
            return self._row_to_frame_tag(row) if row else None

    def get_frame_tags_for_move(self, move_id: int, user_id: str) -> List[FrameTag]:
        """Get all frame tags for a move."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM frame_tags WHERE move_id = %s AND user_id = %s '
                'ORDER BY frame_number',
                (move_id, user_id)
            )
            return [self._row_to_frame_tag(row) for row in cursor.fetchall()]

    def delete_frame_tag(self, tag_id: int, user_id: str) -> bool:
        """Delete a frame tag. Returns success."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM frame_tags WHERE id = %s AND user_id = %s',
                (tag_id, user_id)
            )
            return cursor.rowcount > 0

    # ==================== RATER PROFILE OPERATIONS ====================

    def create_rater_profile(self, profile: RaterProfile) -> RaterProfile:
        """Insert a profile. Raises psycopg UniqueViolation if one exists."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO rater_profiles (
                    user_id, display_name, tier, years_climbing, coaching_cert,
                    highest_grade, research_background, validation_note, is_admin, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            ''', (
                profile.user_id,
                profile.display_name,
                profile.tier or 'open',
                profile.years_climbing,
                profile.coaching_cert,
                profile.highest_grade,
                profile.research_background,
                profile.validation_note,
                profile.is_admin,
                profile.created_at or datetime.now(timezone.utc),
            ))
            return self._row_to_rater_profile(cursor.fetchone())

    def get_rater_profile(self, user_id: str) -> Optional[RaterProfile]:
        """Get a user's profile, or None if they have not created one."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM rater_profiles WHERE user_id = %s', (user_id,))
            row = cursor.fetchone()
            return self._row_to_rater_profile(row) if row else None

    def is_admin(self, user_id: str) -> bool:
        """True when the user's profile carries the admin flag."""
        profile = self.get_rater_profile(user_id)
        return bool(profile and profile.is_admin)

    def list_rater_profiles(self) -> List[RaterProfile]:
        """Every profile, oldest first. Admin only."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM rater_profiles ORDER BY created_at, user_id')
            return [self._row_to_rater_profile(row) for row in cursor.fetchall()]

    def update_rater_profile(self, user_id: str, **fields) -> Optional[RaterProfile]:
        """Set admin-controlled fields on a profile. Returns the row, or None."""
        allowed = ('tier', 'validation_note', 'is_admin', 'display_name')
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return self.get_rater_profile(user_id)
        assignments = ', '.join(f'{k} = %s' for k in updates)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE rater_profiles SET {assignments} WHERE user_id = %s RETURNING *',
                (*updates.values(), user_id)
            )
            row = cursor.fetchone()
            return self._row_to_rater_profile(row) if row else None

    def update_rater_profile_self(self, user_id: str, **fields) -> Optional[RaterProfile]:
        """Set the rater-editable fields on a profile. Returns the row, or None.

        tier / validation_note / is_admin are deliberately not in the allowed
        list: those are update_rater_profile (admin) only. An empty string on
        a nullable text field clears it.
        """
        allowed = ('display_name', 'years_climbing', 'coaching_cert',
                   'highest_grade', 'research_background')
        updates = {}
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key in ('coaching_cert', 'highest_grade') and value == '':
                value = None
            updates[key] = value
        if not updates:
            return self.get_rater_profile(user_id)
        assignments = ', '.join(f'{k} = %s' for k in updates)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'UPDATE rater_profiles SET {assignments} WHERE user_id = %s RETURNING *',
                (*updates.values(), user_id)
            )
            row = cursor.fetchone()
            return self._row_to_rater_profile(row) if row else None

    # ==================== ASSIGNMENT OPERATIONS ====================

    def create_assignment(self, assignment: VideoAssignment) -> VideoAssignment:
        """Insert an assignment. Raises UniqueViolation on (video, rater) repeat."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO video_assignments (video_id, rater_user_id, cohort, status, assigned_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            ''', (
                assignment.video_id,
                assignment.rater_user_id,
                assignment.cohort,
                assignment.status or 'assigned',
                assignment.assigned_at or datetime.now(timezone.utc),
            ))
            return self._row_to_assignment(cursor.fetchone())

    def get_assignment(self, assignment_id: int) -> Optional[VideoAssignment]:
        """Get an assignment by ID (unscoped; callers check rater_user_id)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM video_assignments WHERE id = %s', (assignment_id,))
            row = cursor.fetchone()
            return self._row_to_assignment(row) if row else None

    def get_assignment_for(self, video_id: int, rater_user_id: str) -> Optional[VideoAssignment]:
        """The rater's assignment on a video, if any."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM video_assignments WHERE video_id = %s AND rater_user_id = %s',
                (video_id, rater_user_id)
            )
            row = cursor.fetchone()
            return self._row_to_assignment(row) if row else None

    def list_assignments(self, video_id: Optional[int] = None) -> List[VideoAssignment]:
        """Assignments, optionally for one video. Admin only."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if video_id is None:
                cursor.execute('SELECT * FROM video_assignments ORDER BY video_id, id')
            else:
                cursor.execute(
                    'SELECT * FROM video_assignments WHERE video_id = %s ORDER BY id',
                    (video_id,)
                )
            return [self._row_to_assignment(row) for row in cursor.fetchall()]

    def list_assignments_for_rater(self, rater_user_id: str) -> List[VideoAssignment]:
        """The rater's queue, oldest assignment first."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM video_assignments WHERE rater_user_id = %s ORDER BY assigned_at, id',
                (rater_user_id,)
            )
            return [self._row_to_assignment(row) for row in cursor.fetchall()]

    def set_assignment_status(
        self,
        assignment_id: int,
        status: str,
        completed_at: Optional[datetime] = None,
    ) -> Optional[VideoAssignment]:
        """Move an assignment to a new status. Returns the row, or None."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE video_assignments SET status = %s, completed_at = %s '
                'WHERE id = %s RETURNING *',
                (status, completed_at, assignment_id)
            )
            row = cursor.fetchone()
            return self._row_to_assignment(row) if row else None

    def delete_assignment(self, assignment_id: int) -> bool:
        """Delete an assignment. The rater's label rows are kept."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM video_assignments WHERE id = %s', (assignment_id,))
            return cursor.rowcount > 0

    # ==================== HELPER METHODS ====================

    @staticmethod
    def _row_to_video(row: dict) -> Video:
        """Convert database row to Video object."""
        return Video(
            id=row['id'],
            user_id=str(row['user_id']),
            filename=row['filename'],
            fps=row['fps'],
            total_frames=row['total_frames'],
            duration_ms=row['duration_ms'],
            # .get so a database still on v3 (no dimensions migration) reads back
            # as unknown rather than raising.
            width=row.get('width'),
            height=row.get('height'),
            r2_video_key=row['r2_video_key'],
            r2_pose_csv_key=row['r2_pose_csv_key'],
            r2_export_key=row['r2_export_key'],
            uploaded_at=row['uploaded_at'],
            # Dataset A columns; .get so a database without that migration
            # reads back as the Dataset B defaults.
            dataset=row.get('dataset') or 'B',
            prep_status=row.get('prep_status') or 'draft',
            route_grade=row.get('route_grade'),
            wall_type=row.get('wall_type'),
            climber_experience=row.get('climber_experience'),
            climber_height_cm=row.get('climber_height_cm'),
            climber_ape_index_cm=row.get('climber_ape_index_cm'),
            camera_angle=row.get('camera_angle'),
            gym=row.get('gym'),
            notes=row.get('notes'),
        )

    @staticmethod
    def _row_to_hold(row: dict) -> Hold:
        """Convert database row to Hold object."""
        return Hold(
            id=row['id'],
            video_id=row['video_id'],
            user_id=str(row['user_id']),
            bbox_x=row['bbox_x'],
            bbox_y=row['bbox_y'],
            bbox_w=row['bbox_w'],
            bbox_h=row['bbox_h'],
            source=row['source'],
            created_at=row['created_at'],
        )

    @staticmethod
    def _row_to_move(row: dict) -> Move:
        """Convert database row to Move object."""
        return Move(
            id=row['id'],
            video_id=row['video_id'],
            user_id=str(row['user_id']),
            frame_start=row['frame_start'],
            frame_end=row['frame_end'],
            timestamp_start_ms=row['timestamp_start_ms'],
            timestamp_end_ms=row['timestamp_end_ms'],
            approach=row['approach'],
            move_tags=row['move_tags'] or [],
            size=row['size'],
            form_quality=row['form_quality'],
            effort_level=row['effort_level'],
            confidence=row['confidence'] or '',
            description=row['description'] or '',
            labeled_at=row['labeled_at'],
        )

    @staticmethod
    def _row_to_environment(row: dict) -> Environment:
        """Convert database row to Environment object."""
        kwargs = {
            'id': row['id'],
            'move_id': row['move_id'],
            'user_id': str(row['user_id']),
            'wall_angle': row['wall_angle'],
        }
        for slot in HOLD_SLOTS:
            kwargs[f'{slot}_hold_id'] = row[f'{slot}_hold_id']
            kwargs[f'{slot}_hold_type'] = row[f'{slot}_hold_type']
            kwargs[f'{slot}_hold_quality'] = row[f'{slot}_hold_quality'] or []
        kwargs['taxonomy_version'] = row.get('taxonomy_version') or ''
        kwargs['is_gold'] = bool(row.get('is_gold'))
        return Environment(**kwargs)

    @staticmethod
    def _row_to_outcome(row: dict) -> Outcome:
        """Convert database row to Outcome object."""
        return Outcome(
            id=row['id'],
            move_id=row['move_id'],
            user_id=str(row['user_id']),
            result=row['result'],
            reach_detail=row['reach_detail'],
            confidence=row['confidence'] or '',
            taxonomy_version=row.get('taxonomy_version') or '',
            is_gold=bool(row.get('is_gold')),
        )

    @staticmethod
    def _row_to_frame_tag(row: dict) -> FrameTag:
        """Convert database row to FrameTag object."""
        return FrameTag(
            id=row['id'],
            move_id=row['move_id'],
            user_id=str(row['user_id']),
            frame_number=row['frame_number'],
            timestamp_ms=row['timestamp_ms'],
            tag_type=row['tag_type'],
            side=row['side'],
            level=row['level'],
            locations=row['locations'] or [],
            note=row['note'] or '',
            tagged_at=row['tagged_at'],
            taxonomy_version=row.get('taxonomy_version') or '',
            is_gold=bool(row.get('is_gold')),
        )

    @staticmethod
    def _row_to_rater_profile(row: dict) -> RaterProfile:
        """Convert database row to RaterProfile object."""
        return RaterProfile(
            user_id=str(row['user_id']),
            display_name=row['display_name'],
            tier=row['tier'],
            years_climbing=row['years_climbing'],
            coaching_cert=row['coaching_cert'],
            highest_grade=row['highest_grade'],
            research_background=bool(row['research_background']),
            validation_note=row['validation_note'],
            is_admin=bool(row['is_admin']),
            created_at=row['created_at'],
        )

    @staticmethod
    def _row_to_assignment(row: dict) -> VideoAssignment:
        """Convert database row to VideoAssignment object."""
        return VideoAssignment(
            id=row['id'],
            video_id=row['video_id'],
            rater_user_id=str(row['rater_user_id']),
            cohort=row['cohort'],
            status=row['status'],
            assigned_at=row['assigned_at'],
            completed_at=row['completed_at'],
        )
