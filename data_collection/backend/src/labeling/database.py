"""
Database layer for labeling system.

Handles all SQLite operations. Models know nothing about the database.
Schema version 2: Three-lens model (Environment / Strategy / Outcome)
"""
import sqlite3
import json
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from contextlib import contextmanager

from .models import Video, Move, Environment, Outcome, FrameTag

SCHEMA_VERSION = 2


class Database:
    """
    Database handler with clean separation of concerns.

    Usage:
        db = Database('data/labels.db')
        db.init()

        # Create
        video_id = db.create_video(video)
        move_id = db.create_move(move)
        env_id = db.create_environment(env)
        outcome_id = db.create_outcome(outcome)

        # Read
        video = db.get_video(video_id)
        moves = db.get_moves_for_video(video_id)
        env = db.get_environment_for_move(move_id)
        outcome = db.get_outcome_for_move(move_id)

        # Update
        db.update_move(move)
        db.update_environment(env)
        db.update_outcome(outcome)

        # Delete
        db.delete_frame_tag(tag_id)
    """

    def __init__(self, db_path: str = 'data/labels.db'):
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self):
        """Initialize database schema."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Schema version table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL
                )
            ''')

            # Check current schema version
            cursor.execute('SELECT MAX(version) FROM schema_version')
            row = cursor.fetchone()
            current_version = row[0] if row[0] is not None else 0

            if current_version < SCHEMA_VERSION:
                self._apply_schema(cursor)
                cursor.execute(
                    'INSERT INTO schema_version (version, applied_at) VALUES (?, ?)',
                    (SCHEMA_VERSION, datetime.now().isoformat())
                )

    def _apply_schema(self, cursor):
        """Apply the current schema (drops and recreates tables except videos)."""
        # Videos table (unchanged)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                path TEXT NOT NULL,
                csv_path TEXT NOT NULL,
                fps REAL NOT NULL,
                total_frames INTEGER NOT NULL,
                duration_ms REAL NOT NULL,
                uploaded_at TEXT NOT NULL
            )
        ''')

        # Drop old tables if they exist (order matters for foreign keys)
        cursor.execute('DROP TABLE IF EXISTS frame_tags')
        cursor.execute('DROP TABLE IF EXISTS outcomes')
        cursor.execute('DROP TABLE IF EXISTS environments')
        cursor.execute('DROP TABLE IF EXISTS moves')

        # Moves table (Lens 2: Strategy)
        cursor.execute('''
            CREATE TABLE moves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER NOT NULL,
                frame_start INTEGER NOT NULL,
                frame_end INTEGER NOT NULL,
                timestamp_start_ms REAL NOT NULL,
                timestamp_end_ms REAL NOT NULL,
                approach TEXT NOT NULL,
                size TEXT NOT NULL,
                move_tags TEXT NOT NULL,
                form_quality INTEGER NOT NULL,
                effort_level INTEGER NOT NULL,
                contextual_data TEXT NOT NULL,
                tags TEXT NOT NULL,
                description TEXT NOT NULL,
                labeled_at TEXT NOT NULL,
                FOREIGN KEY (video_id) REFERENCES videos(id)
            )
        ''')

        # Environments table (Lens 1: Environment)
        cursor.execute('''
            CREATE TABLE environments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                move_id INTEGER NOT NULL UNIQUE,
                wall_angle TEXT NOT NULL,
                hold_type_reaching TEXT NOT NULL,
                hold_type_non_reaching TEXT NOT NULL,
                hold_quality TEXT NOT NULL,
                FOREIGN KEY (move_id) REFERENCES moves(id)
            )
        ''')

        # Outcomes table (Lens 3: Outcome)
        cursor.execute('''
            CREATE TABLE outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                move_id INTEGER NOT NULL UNIQUE,
                result TEXT NOT NULL,
                reach_detail TEXT NOT NULL,
                foot_cut INTEGER NOT NULL,
                confidence TEXT NOT NULL,
                FOREIGN KEY (move_id) REFERENCES moves(id)
            )
        ''')

        # Frame tags table (Sensation)
        cursor.execute('''
            CREATE TABLE frame_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                move_id INTEGER NOT NULL,
                frame_number INTEGER NOT NULL,
                timestamp_ms REAL NOT NULL,
                tag_type TEXT NOT NULL,
                level INTEGER,
                locations TEXT NOT NULL,
                side TEXT,
                traction_source TEXT,
                traction_direction TEXT,
                note TEXT NOT NULL,
                tagged_at TEXT NOT NULL,
                FOREIGN KEY (move_id) REFERENCES moves(id)
            )
        ''')

        # Create indexes
        cursor.execute('CREATE INDEX idx_moves_video ON moves(video_id)')
        cursor.execute('CREATE INDEX idx_frame_tags_move ON frame_tags(move_id)')
        cursor.execute('CREATE INDEX idx_environments_move ON environments(move_id)')
        cursor.execute('CREATE INDEX idx_outcomes_move ON outcomes(move_id)')

    def get_schema_version(self) -> int:
        """Get the current schema version."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT MAX(version) FROM schema_version')
            row = cursor.fetchone()
            return row[0] if row[0] is not None else 0

    # ==================== VIDEO OPERATIONS ====================

    def create_video(self, video: Video) -> int:
        """Create a new video record. Returns video_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO videos (filename, path, csv_path, fps, total_frames, duration_ms, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                video.filename,
                video.path,
                video.csv_path,
                video.fps,
                video.total_frames,
                video.duration_ms,
                (video.uploaded_at or datetime.now()).isoformat()
            ))
            return cursor.lastrowid

    def get_video(self, video_id: int) -> Optional[Video]:
        """Get a video by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM videos WHERE id = ?', (video_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return Video(
                id=row['id'],
                filename=row['filename'],
                path=row['path'],
                csv_path=row['csv_path'],
                fps=row['fps'],
                total_frames=row['total_frames'],
                duration_ms=row['duration_ms'],
                uploaded_at=datetime.fromisoformat(row['uploaded_at'])
            )

    def get_all_videos(self) -> List[Video]:
        """Get all videos."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM videos ORDER BY uploaded_at DESC')
            rows = cursor.fetchall()

            return [
                Video(
                    id=row['id'],
                    filename=row['filename'],
                    path=row['path'],
                    csv_path=row['csv_path'],
                    fps=row['fps'],
                    total_frames=row['total_frames'],
                    duration_ms=row['duration_ms'],
                    uploaded_at=datetime.fromisoformat(row['uploaded_at'])
                )
                for row in rows
            ]

    # ==================== MOVE OPERATIONS ====================

    def create_move(self, move: Move) -> int:
        """Create a new move. Returns move_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO moves (
                    video_id, frame_start, frame_end, timestamp_start_ms, timestamp_end_ms,
                    approach, size, move_tags, form_quality, effort_level,
                    contextual_data, tags, description, labeled_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                move.video_id,
                move.frame_start,
                move.frame_end,
                move.timestamp_start_ms,
                move.timestamp_end_ms,
                move.approach,
                move.size,
                json.dumps(move.move_tags),
                move.form_quality,
                move.effort_level,
                json.dumps(move.contextual_data),
                json.dumps(move.tags),
                move.description,
                (move.labeled_at or datetime.now()).isoformat()
            ))
            return cursor.lastrowid

    def get_move(self, move_id: int) -> Optional[Move]:
        """Get a move by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM moves WHERE id = ?', (move_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_move(row)

    def get_moves_for_video(self, video_id: int) -> List[Move]:
        """Get all moves for a video."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM moves WHERE video_id = ? ORDER BY frame_start',
                (video_id,)
            )
            rows = cursor.fetchall()
            return [self._row_to_move(row) for row in rows]

    def update_move(self, move: Move) -> bool:
        """Update an existing move. Returns success."""
        if not move.id:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE moves SET
                    frame_start = ?,
                    frame_end = ?,
                    timestamp_start_ms = ?,
                    timestamp_end_ms = ?,
                    approach = ?,
                    size = ?,
                    move_tags = ?,
                    form_quality = ?,
                    effort_level = ?,
                    contextual_data = ?,
                    tags = ?,
                    description = ?
                WHERE id = ?
            ''', (
                move.frame_start,
                move.frame_end,
                move.timestamp_start_ms,
                move.timestamp_end_ms,
                move.approach,
                move.size,
                json.dumps(move.move_tags),
                move.form_quality,
                move.effort_level,
                json.dumps(move.contextual_data),
                json.dumps(move.tags),
                move.description,
                move.id
            ))
            return cursor.rowcount > 0

    def delete_move(self, move_id: int) -> bool:
        """Delete a move and its related records. Returns success."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Delete related records first (foreign key constraints)
            cursor.execute('DELETE FROM frame_tags WHERE move_id = ?', (move_id,))
            cursor.execute('DELETE FROM environments WHERE move_id = ?', (move_id,))
            cursor.execute('DELETE FROM outcomes WHERE move_id = ?', (move_id,))

            # Delete move
            cursor.execute('DELETE FROM moves WHERE id = ?', (move_id,))

            return cursor.rowcount > 0

    # ==================== ENVIRONMENT OPERATIONS ====================

    def create_environment(self, env: Environment) -> int:
        """Create a new environment record. Returns environment_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO environments (
                    move_id, wall_angle, hold_type_reaching, hold_type_non_reaching, hold_quality
                )
                VALUES (?, ?, ?, ?, ?)
            ''', (
                env.move_id,
                env.wall_angle,
                env.hold_type_reaching,
                env.hold_type_non_reaching,
                json.dumps(env.hold_quality)
            ))
            return cursor.lastrowid

    def get_environment(self, env_id: int) -> Optional[Environment]:
        """Get an environment by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM environments WHERE id = ?', (env_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_environment(row)

    def get_environment_for_move(self, move_id: int) -> Optional[Environment]:
        """Get the environment for a move."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM environments WHERE move_id = ?', (move_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_environment(row)

    def update_environment(self, env: Environment) -> bool:
        """Update an existing environment. Returns success."""
        if not env.id:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE environments SET
                    wall_angle = ?,
                    hold_type_reaching = ?,
                    hold_type_non_reaching = ?,
                    hold_quality = ?
                WHERE id = ?
            ''', (
                env.wall_angle,
                env.hold_type_reaching,
                env.hold_type_non_reaching,
                json.dumps(env.hold_quality),
                env.id
            ))
            return cursor.rowcount > 0

    def delete_environment(self, env_id: int) -> bool:
        """Delete an environment. Returns success."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM environments WHERE id = ?', (env_id,))
            return cursor.rowcount > 0

    # ==================== OUTCOME OPERATIONS ====================

    def create_outcome(self, outcome: Outcome) -> int:
        """Create a new outcome record. Returns outcome_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO outcomes (
                    move_id, result, reach_detail, foot_cut, confidence
                )
                VALUES (?, ?, ?, ?, ?)
            ''', (
                outcome.move_id,
                outcome.result,
                outcome.reach_detail,
                1 if outcome.foot_cut else 0,
                outcome.confidence
            ))
            return cursor.lastrowid

    def get_outcome(self, outcome_id: int) -> Optional[Outcome]:
        """Get an outcome by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM outcomes WHERE id = ?', (outcome_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_outcome(row)

    def get_outcome_for_move(self, move_id: int) -> Optional[Outcome]:
        """Get the outcome for a move."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM outcomes WHERE move_id = ?', (move_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_outcome(row)

    def update_outcome(self, outcome: Outcome) -> bool:
        """Update an existing outcome. Returns success."""
        if not outcome.id:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE outcomes SET
                    result = ?,
                    reach_detail = ?,
                    foot_cut = ?,
                    confidence = ?
                WHERE id = ?
            ''', (
                outcome.result,
                outcome.reach_detail,
                1 if outcome.foot_cut else 0,
                outcome.confidence,
                outcome.id
            ))
            return cursor.rowcount > 0

    def delete_outcome(self, outcome_id: int) -> bool:
        """Delete an outcome. Returns success."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM outcomes WHERE id = ?', (outcome_id,))
            return cursor.rowcount > 0

    # ==================== FRAME TAG OPERATIONS ====================

    def create_frame_tag(self, tag: FrameTag) -> int:
        """Create a new frame tag. Returns tag_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO frame_tags (
                    move_id, frame_number, timestamp_ms, tag_type, level, locations,
                    side, traction_source, traction_direction, note, tagged_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tag.move_id,
                tag.frame_number,
                tag.timestamp_ms,
                tag.tag_type,
                tag.level,
                json.dumps(tag.locations),
                tag.side,
                tag.traction_source,
                tag.traction_direction,
                tag.note,
                (tag.tagged_at or datetime.now()).isoformat()
            ))
            return cursor.lastrowid

    def get_frame_tag(self, tag_id: int) -> Optional[FrameTag]:
        """Get a frame tag by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM frame_tags WHERE id = ?', (tag_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_frame_tag(row)

    def get_frame_tags_for_move(self, move_id: int) -> List[FrameTag]:
        """Get all frame tags for a move."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM frame_tags WHERE move_id = ? ORDER BY frame_number',
                (move_id,)
            )
            rows = cursor.fetchall()
            return [self._row_to_frame_tag(row) for row in rows]

    def delete_frame_tag(self, tag_id: int) -> bool:
        """Delete a frame tag. Returns success."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM frame_tags WHERE id = ?', (tag_id,))
            return cursor.rowcount > 0

    # ==================== HELPER METHODS ====================

    def _row_to_move(self, row: sqlite3.Row) -> Move:
        """Convert database row to Move object."""
        return Move(
            id=row['id'],
            video_id=row['video_id'],
            frame_start=row['frame_start'],
            frame_end=row['frame_end'],
            timestamp_start_ms=row['timestamp_start_ms'],
            timestamp_end_ms=row['timestamp_end_ms'],
            approach=row['approach'],
            size=row['size'],
            move_tags=json.loads(row['move_tags']),
            form_quality=row['form_quality'],
            effort_level=row['effort_level'],
            contextual_data=json.loads(row['contextual_data']),
            tags=json.loads(row['tags']),
            description=row['description'],
            labeled_at=datetime.fromisoformat(row['labeled_at'])
        )

    def _row_to_environment(self, row: sqlite3.Row) -> Environment:
        """Convert database row to Environment object."""
        return Environment(
            id=row['id'],
            move_id=row['move_id'],
            wall_angle=row['wall_angle'],
            hold_type_reaching=row['hold_type_reaching'],
            hold_type_non_reaching=row['hold_type_non_reaching'],
            hold_quality=json.loads(row['hold_quality'])
        )

    def _row_to_outcome(self, row: sqlite3.Row) -> Outcome:
        """Convert database row to Outcome object."""
        return Outcome(
            id=row['id'],
            move_id=row['move_id'],
            result=row['result'],
            reach_detail=row['reach_detail'],
            foot_cut=bool(row['foot_cut']),
            confidence=row['confidence']
        )

    def _row_to_frame_tag(self, row: sqlite3.Row) -> FrameTag:
        """Convert database row to FrameTag object."""
        return FrameTag(
            id=row['id'],
            move_id=row['move_id'],
            frame_number=row['frame_number'],
            timestamp_ms=row['timestamp_ms'],
            tag_type=row['tag_type'],
            level=row['level'],
            locations=json.loads(row['locations']),
            side=row['side'],
            traction_source=row['traction_source'],
            traction_direction=row['traction_direction'],
            note=row['note'],
            tagged_at=datetime.fromisoformat(row['tagged_at'])
        )
