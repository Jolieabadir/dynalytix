"""
Database layer for movement assessment system.

Handles all SQLite operations. Models know nothing about the database.
"""
import sqlite3
import json
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from contextlib import contextmanager

from .models import Video, Assessment, FrameTag


class Database:
    """
    Database handler with clean separation of concerns.

    Usage:
        db = Database('data/labels.db')
        db.init()

        # Create
        video_id = db.create_video(video)

        # Read
        video = db.get_video(video_id)
        assessments = db.get_assessments_for_video(video_id)

        # Update
        db.update_assessment(assessment)

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

            # Videos table
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

            # Assessments table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    frame_start INTEGER NOT NULL,
                    frame_end INTEGER NOT NULL,
                    timestamp_start_ms REAL NOT NULL,
                    timestamp_end_ms REAL NOT NULL,
                    test_type TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    criteria_data TEXT NOT NULL,
                    compensations TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    assessed_at TEXT NOT NULL,
                    FOREIGN KEY (video_id) REFERENCES videos(id)
                )
            ''')

            # Frame tags table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS frame_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assessment_id INTEGER NOT NULL,
                    frame_number INTEGER NOT NULL,
                    timestamp_ms REAL NOT NULL,
                    tag_type TEXT NOT NULL,
                    level INTEGER,
                    locations TEXT NOT NULL,
                    note TEXT NOT NULL,
                    tagged_at TEXT NOT NULL,
                    FOREIGN KEY (assessment_id) REFERENCES assessments(id)
                )
            ''')

            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_assessments_video ON assessments(video_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_frame_tags_assessment ON frame_tags(assessment_id)')

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

    # ==================== ASSESSMENT OPERATIONS ====================

    def create_assessment(self, assessment: Assessment) -> int:
        """Create a new assessment. Returns assessment_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO assessments (
                    video_id, frame_start, frame_end, timestamp_start_ms, timestamp_end_ms,
                    test_type, score, criteria_data, compensations,
                    tags, notes, assessed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                assessment.video_id,
                assessment.frame_start,
                assessment.frame_end,
                assessment.timestamp_start_ms,
                assessment.timestamp_end_ms,
                assessment.test_type,
                assessment.score,
                json.dumps(assessment.criteria_data),
                json.dumps(assessment.compensations),
                json.dumps(assessment.tags),
                assessment.notes,
                (assessment.assessed_at or datetime.now()).isoformat()
            ))
            return cursor.lastrowid

    def get_assessment(self, assessment_id: int) -> Optional[Assessment]:
        """Get an assessment by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM assessments WHERE id = ?', (assessment_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_assessment(row)

    def get_assessments_for_video(self, video_id: int) -> List[Assessment]:
        """Get all assessments for a video."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM assessments WHERE video_id = ? ORDER BY frame_start',
                (video_id,)
            )
            rows = cursor.fetchall()
            return [self._row_to_assessment(row) for row in rows]

    def update_assessment(self, assessment: Assessment) -> bool:
        """Update an existing assessment. Returns success."""
        if not assessment.id:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE assessments SET
                    frame_start = ?,
                    frame_end = ?,
                    timestamp_start_ms = ?,
                    timestamp_end_ms = ?,
                    test_type = ?,
                    score = ?,
                    criteria_data = ?,
                    compensations = ?,
                    tags = ?,
                    notes = ?
                WHERE id = ?
            ''', (
                assessment.frame_start,
                assessment.frame_end,
                assessment.timestamp_start_ms,
                assessment.timestamp_end_ms,
                assessment.test_type,
                assessment.score,
                json.dumps(assessment.criteria_data),
                json.dumps(assessment.compensations),
                json.dumps(assessment.tags),
                assessment.notes,
                assessment.id
            ))
            return cursor.rowcount > 0

    def delete_assessment(self, assessment_id: int) -> bool:
        """Delete an assessment and its frame tags. Returns success."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Delete frame tags first (foreign key constraint)
            cursor.execute('DELETE FROM frame_tags WHERE assessment_id = ?', (assessment_id,))

            # Delete assessment
            cursor.execute('DELETE FROM assessments WHERE id = ?', (assessment_id,))

            return cursor.rowcount > 0

    # ==================== FRAME TAG OPERATIONS ====================

    def create_frame_tag(self, tag: FrameTag) -> int:
        """Create a new frame tag. Returns tag_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO frame_tags (
                    assessment_id, frame_number, timestamp_ms, tag_type, level, locations, note, tagged_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tag.assessment_id,
                tag.frame_number,
                tag.timestamp_ms,
                tag.tag_type,
                tag.level,
                json.dumps(tag.locations),
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

    def get_frame_tags_for_assessment(self, assessment_id: int) -> List[FrameTag]:
        """Get all frame tags for an assessment."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM frame_tags WHERE assessment_id = ? ORDER BY frame_number',
                (assessment_id,)
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

    def _row_to_assessment(self, row: sqlite3.Row) -> Assessment:
        """Convert database row to Assessment object."""
        return Assessment(
            id=row['id'],
            video_id=row['video_id'],
            frame_start=row['frame_start'],
            frame_end=row['frame_end'],
            timestamp_start_ms=row['timestamp_start_ms'],
            timestamp_end_ms=row['timestamp_end_ms'],
            test_type=row['test_type'],
            score=row['score'],
            criteria_data=json.loads(row['criteria_data']),
            compensations=json.loads(row['compensations']),
            tags=json.loads(row['tags']),
            notes=row['notes'],
            assessed_at=datetime.fromisoformat(row['assessed_at'])
        )

    def _row_to_frame_tag(self, row: sqlite3.Row) -> FrameTag:
        """Convert database row to FrameTag object."""
        return FrameTag(
            id=row['id'],
            assessment_id=row['assessment_id'],
            frame_number=row['frame_number'],
            timestamp_ms=row['timestamp_ms'],
            tag_type=row['tag_type'],
            level=row['level'],
            locations=json.loads(row['locations']),
            note=row['note'],
            tagged_at=datetime.fromisoformat(row['tagged_at'])
        )
