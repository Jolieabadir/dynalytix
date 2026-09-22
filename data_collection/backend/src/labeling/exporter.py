"""
Export service for combining pose data with labels.
Creates ML-ready CSV files with three-lens labeling schema.

Both ends are R2: the raw pose CSV is streamed out of the bucket and the joined
result is written straight back to it. Nothing touches local disk, so an export
survives a Railway redeploy.
"""
import csv
import io
from typing import Dict, List, Optional

from .database import Database
from .models import HOLD_SLOTS, Video
from ..storage import r2


class Exporter:
    """Combines raw pose CSV with labels from Postgres."""

    def __init__(self, db: Database):
        self.db = db

    def export_video(self, video_id: int, user_id: str) -> str:
        """
        Export combined data for one of this user's videos.

        Streams the pose CSV from R2, joins the labels, writes the result back
        to R2 and records the key on the video row.

        Returns the R2 key of the export.
        """
        video = self.db.get_video(video_id, user_id)
        if not video:
            raise ValueError(f"Video {video_id} not found")

        if not video.r2_pose_csv_key:
            raise ValueError(f"Video {video_id} has no pose CSV stored")

        frame_labels = self._build_frame_labels(video_id, user_id)

        try:
            source = r2.get_object_stream(video.r2_pose_csv_key)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc

        # StreamingBody yields bytes; wrap it so csv sees text.
        with source:
            text_stream = io.TextIOWrapper(source, encoding='utf-8', newline='')
            reader = csv.DictReader(text_stream)
            output = io.StringIO()
            writer = self._make_writer(output, reader.fieldnames or [])

            for row in reader:
                writer.writerow(self._merge_row(row, frame_labels))

        key = r2.export_key(user_id, video_id)
        r2.put_object(key, output.getvalue(), content_type='text/csv')
        self.db.set_video_r2_keys(video_id, user_id, r2_export_key=key)

        return key

    # ==================== INTERNALS ====================

    def _build_frame_labels(self, video_id: int, user_id: str) -> dict:
        """Expand each move's labels across every frame it covers."""
        frame_labels = {}

        for move in self.db.get_moves_for_video(video_id, user_id):
            env = self.db.get_environment_for_move(move.id, user_id)
            outcome = self.db.get_outcome_for_move(move.id, user_id)
            tags = self.db.get_frame_tags_for_move(move.id, user_id)

            labels = {
                'move_id': move.id,
                # Lens 2: Strategy
                'approach': move.approach,
                'size': move.size,
                'move_tags': '|'.join(move.move_tags) if move.move_tags else '',
                'form_quality': move.form_quality,
                'effort_level': move.effort_level,
                'move_confidence': move.confidence or '',
                # Lens 1: Environment
                'wall_angle': env.wall_angle if env else '',
                # Lens 3: Outcome
                'result': outcome.result if outcome else '',
                'reach_detail': outcome.reach_detail if outcome else '',
                'outcome_confidence': outcome.confidence if outcome else '',
            }

            # One group of columns per hold slot.
            for slot in HOLD_SLOTS:
                hold_id = getattr(env, f'{slot}_hold_id', None) if env else None
                hold_type = getattr(env, f'{slot}_hold_type', None) if env else None
                quality = getattr(env, f'{slot}_hold_quality', None) if env else None

                labels[f'{slot}_hold_id'] = hold_id if hold_id is not None else ''
                labels[f'{slot}_hold_type'] = hold_type or ''
                labels[f'{slot}_hold_quality'] = '|'.join(quality) if quality else ''

                # Denormalize the bbox so the export stands alone as a dataset.
                bbox = ''
                if hold_id is not None:
                    hold = self.db.get_hold(hold_id, user_id)
                    if hold:
                        bbox = f'{hold.bbox_x},{hold.bbox_y},{hold.bbox_w},{hold.bbox_h}'
                labels[f'{slot}_hold_bbox'] = bbox

            for frame in range(move.frame_start, move.frame_end + 1):
                frame_labels[frame] = dict(labels, frame_tags=[])

            for tag in tags:
                if tag.frame_number in frame_labels:
                    frame_labels[tag.frame_number]['frame_tags'].append({
                        'tag_type': tag.tag_type,
                        'level': tag.level,
                        'locations': tag.locations,
                        'side': tag.side,
                        'note': tag.note,
                    })

        return frame_labels

    @staticmethod
    def label_columns() -> list:
        """The label columns appended to the raw pose header, in order."""
        columns = [
            'move_id',
            # Lens 2: Strategy
            'approach', 'size', 'move_tags', 'form_quality', 'effort_level',
            'move_confidence',
            # Lens 1: Environment
            'wall_angle',
        ]
        for slot in HOLD_SLOTS:
            columns += [
                f'{slot}_hold_id',
                f'{slot}_hold_type',
                f'{slot}_hold_quality',
                f'{slot}_hold_bbox',
            ]
        columns += [
            # Lens 3: Outcome
            'result', 'reach_detail', 'outcome_confidence',
            # Sensation (Frame Tags) - pipe-delimited across tags on a frame
            'tag_types', 'tag_levels', 'tag_locations', 'tag_sides', 'tag_notes',
        ]
        return columns

    def _make_writer(self, output, source_fieldnames) -> csv.DictWriter:
        writer = csv.DictWriter(
            output,
            fieldnames=list(source_fieldnames) + self.label_columns(),
        )
        writer.writeheader()
        return writer

    def _merge_row(self, row: dict, frame_labels: dict) -> dict:
        """Attach the labels for this row's frame."""
        try:
            frame_num = int(row.get('frame_number', 0))
        except (TypeError, ValueError):
            frame_num = -1

        labels = frame_labels.get(frame_num, {})

        for column in self.label_columns():
            if column.startswith('tag_'):
                continue
            row[column] = labels.get(column, '')

        frame_tags = labels.get('frame_tags', [])
        if frame_tags:
            row['tag_types'] = '|'.join(t['tag_type'] for t in frame_tags)
            row['tag_levels'] = '|'.join(
                str(t['level']) if t['level'] is not None else '' for t in frame_tags
            )
            row['tag_locations'] = '|'.join(
                ','.join(t['locations']) if t['locations'] else '' for t in frame_tags
            )
            row['tag_sides'] = '|'.join(t['side'] or '' for t in frame_tags)
            row['tag_notes'] = '|'.join(t['note'] or '' for t in frame_tags)
        else:
            row['tag_types'] = ''
            row['tag_levels'] = ''
            row['tag_locations'] = ''
            row['tag_sides'] = ''
            row['tag_notes'] = ''

        return row


# =============================================================================
# Admin exports (Dataset A, runbook W1)
# =============================================================================
#
# Two CSVs an admin can pull across every video and every rater:
#
#   long  - one row per (rater, move, lens, field). The IRR input; a notebook
#           (or scripts/irr_alpha.py) pivots it by rater and computes
#           Krippendorff's alpha per field.
#   full  - one row per (video, move, rater) with the same label columns the
#           per-video export appends to the pose CSV (Exporter.label_columns),
#           plus identity columns. It does NOT carry pose data: joining every
#           video's pose CSV out of R2 into one file would be hundreds of MB
#           and triple for three raters. Pose rows stay in the per-video
#           export; join on (video_id, frame_number in frame_start..frame_end).

LONG_COLUMNS = [
    'video_id', 'dataset', 'move_id', 'move_index',
    'rater_user_id', 'rater_tier', 'cohort',
    'lens', 'field', 'value', 'taxonomy_version', 'is_gold',
]

# Strategy comes from the move row itself (canonical moves are created in
# prep, not by raters), so it is emitted once per move with the move's creator
# as the rater and cohort 'prep'.
STRATEGY_FIELDS = ['approach', 'move_tags', 'size', 'form_quality', 'effort_level', 'confidence']
OUTCOME_FIELDS = ['result', 'reach_detail', 'confidence']
FRAME_TAG_FIELDS = ['tag_type', 'side', 'level', 'locations', 'note', 'frame_number']
PREP_COHORT = 'prep'


def _pipe(values) -> str:
    return '|'.join(str(v) for v in values) if values else ''


def _cell(value) -> str:
    """Render one long-format value: None -> '', bool -> 'true'/'false'."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (list, tuple)):
        return _pipe(value)
    return str(value)


def environment_fields() -> List[str]:
    """The environment lens fields, in the order the long export emits them."""
    fields = ['wall_angle']
    for slot in HOLD_SLOTS:
        fields += [f'{slot}_hold_id', f'{slot}_hold_type', f'{slot}_hold_quality']
    return fields


class AdminExporter:
    """Cross-user, cross-video exports for admins.

    Holds a Database and small per-call caches for profiles and assignments so
    a long export over N videos does not run one profile query per row.
    """

    def __init__(self, db: Database):
        self.db = db

    # ---------- shared lookups ----------

    def _tier(self, cache: dict, user_id: str) -> str:
        if user_id not in cache:
            profile = self.db.get_rater_profile(user_id)
            cache[user_id] = profile.tier if profile else ''
        return cache[user_id]

    def _cohorts(self, video_id: int) -> Dict[str, str]:
        return {a.rater_user_id: a.cohort for a in self.db.list_assignments(video_id)}

    def _videos(self, video_id: Optional[int], dataset: Optional[str]) -> List[Video]:
        return self.db.get_videos_for_export(video_id=video_id, dataset=dataset)

    # ---------- long format ----------

    def long_rows(self, video_id: Optional[int] = None, dataset: Optional[str] = 'A') -> List[dict]:
        """One dict per (rater, move, lens, field).

        Defaults to Dataset A only; pass dataset=None for everything, or a
        video_id for one video regardless of dataset.
        """
        if video_id is not None:
            dataset = None
        tiers: Dict[str, str] = {}
        rows: List[dict] = []

        for video in self._videos(video_id, dataset):
            cohorts = self._cohorts(video.id)
            moves = self.db.get_moves_for_video_any(video.id)

            for move_index, move in enumerate(moves):
                base = {
                    'video_id': video.id,
                    'dataset': video.dataset,
                    'move_id': move.id,
                    'move_index': move_index,
                }

                def emit(rater: str, cohort: str, lens: str, field: str, value,
                         taxonomy_version: str, is_gold: bool):
                    rows.append(dict(
                        base,
                        rater_user_id=rater,
                        rater_tier=self._tier(tiers, rater),
                        cohort=cohort,
                        lens=lens,
                        field=field,
                        value=_cell(value),
                        taxonomy_version=taxonomy_version,
                        is_gold=_cell(is_gold),
                    ))

                # Strategy: from the move row, once per move.
                for field in STRATEGY_FIELDS:
                    emit(move.user_id, PREP_COHORT, 'strategy', field,
                         getattr(move, field), '', False)

                for env in self.db.get_environments_for_move_all(move.id):
                    cohort = cohorts.get(env.user_id, '')
                    for field in environment_fields():
                        emit(env.user_id, cohort, 'environment', field,
                             getattr(env, field), env.taxonomy_version, env.is_gold)

                for outcome in self.db.get_outcomes_for_move_all(move.id):
                    cohort = cohorts.get(outcome.user_id, '')
                    for field in OUTCOME_FIELDS:
                        emit(outcome.user_id, cohort, 'outcome', field,
                             getattr(outcome, field), outcome.taxonomy_version, outcome.is_gold)

                for tag in self.db.get_frame_tags_for_move_all(move.id):
                    cohort = cohorts.get(tag.user_id, '')
                    for field in FRAME_TAG_FIELDS:
                        emit(tag.user_id, cohort, 'frame_tag', field,
                             getattr(tag, field), tag.taxonomy_version, tag.is_gold)

        return rows

    def long_csv(self, video_id: Optional[int] = None, dataset: Optional[str] = 'A') -> str:
        """The long export as CSV text with exactly LONG_COLUMNS as the header."""
        return rows_to_csv(LONG_COLUMNS, self.long_rows(video_id=video_id, dataset=dataset))

    # ---------- full format ----------

    @staticmethod
    def full_columns() -> List[str]:
        """Identity columns, then the per-video export's label columns."""
        return [
            'video_id', 'dataset', 'prep_status', 'owner_user_id', 'filename',
            'move_index', 'rater_user_id', 'rater_tier', 'cohort',
            'frame_start', 'frame_end', 'timestamp_start_ms', 'timestamp_end_ms',
            'description', 'taxonomy_version', 'is_gold',
        ] + Exporter.label_columns() + ['tag_frames']

    def full_rows(self, video_id: Optional[int] = None, dataset: Optional[str] = None) -> List[dict]:
        """One dict per (video, move, rater) with every label column.

        A rater appears on a move if they have an environment, an outcome or
        any frame tag on it. A move nobody has labeled yet still appears once,
        with the move's creator as rater and empty label cells, so the export
        shows what is outstanding.
        """
        tiers: Dict[str, str] = {}
        rows: List[dict] = []

        for video in self._videos(video_id, dataset):
            cohorts = self._cohorts(video.id)
            holds = {h.id: h for h in self.db.get_holds_for_video_any(video.id)}

            for move_index, move in enumerate(self.db.get_moves_for_video_any(video.id)):
                envs = {e.user_id: e for e in self.db.get_environments_for_move_all(move.id)}
                outcomes = {o.user_id: o for o in self.db.get_outcomes_for_move_all(move.id)}
                tags_by_rater: Dict[str, list] = {}
                for tag in self.db.get_frame_tags_for_move_all(move.id):
                    tags_by_rater.setdefault(tag.user_id, []).append(tag)

                raters = sorted(set(envs) | set(outcomes) | set(tags_by_rater)) or [move.user_id]

                for rater in raters:
                    env = envs.get(rater)
                    outcome = outcomes.get(rater)
                    tags = tags_by_rater.get(rater, [])
                    versions = {
                        x.taxonomy_version for x in ([env] if env else []) + ([outcome] if outcome else []) + tags
                    }
                    gold = any(x.is_gold for x in ([env] if env else []) + ([outcome] if outcome else []) + tags)

                    row = {
                        'video_id': video.id,
                        'dataset': video.dataset,
                        'prep_status': video.prep_status,
                        'owner_user_id': video.user_id,
                        'filename': video.filename,
                        'move_index': move_index,
                        'rater_user_id': rater,
                        'rater_tier': self._tier(tiers, rater),
                        'cohort': cohorts.get(rater, PREP_COHORT if rater == move.user_id else ''),
                        'frame_start': move.frame_start,
                        'frame_end': move.frame_end,
                        'timestamp_start_ms': move.timestamp_start_ms,
                        'timestamp_end_ms': move.timestamp_end_ms,
                        'description': move.description,
                        'taxonomy_version': _pipe(sorted(versions)),
                        'is_gold': _cell(gold),
                        'move_id': move.id,
                        'approach': move.approach,
                        'size': move.size,
                        'move_tags': _pipe(move.move_tags),
                        'form_quality': move.form_quality,
                        'effort_level': move.effort_level,
                        'move_confidence': move.confidence or '',
                        'wall_angle': env.wall_angle if env else '',
                        'result': outcome.result if outcome else '',
                        'reach_detail': outcome.reach_detail if outcome else '',
                        'outcome_confidence': outcome.confidence if outcome else '',
                    }
                    for slot in HOLD_SLOTS:
                        hold_id = getattr(env, f'{slot}_hold_id', None) if env else None
                        hold = holds.get(hold_id) if hold_id is not None else None
                        row[f'{slot}_hold_id'] = hold_id if hold_id is not None else ''
                        row[f'{slot}_hold_type'] = (getattr(env, f'{slot}_hold_type', None) or '') if env else ''
                        row[f'{slot}_hold_quality'] = _pipe(getattr(env, f'{slot}_hold_quality', None)) if env else ''
                        row[f'{slot}_hold_bbox'] = (
                            f'{hold.bbox_x},{hold.bbox_y},{hold.bbox_w},{hold.bbox_h}' if hold else ''
                        )
                    row['tag_types'] = _pipe(t.tag_type for t in tags)
                    row['tag_levels'] = _pipe('' if t.level is None else t.level for t in tags)
                    row['tag_locations'] = _pipe(','.join(t.locations) for t in tags)
                    row['tag_sides'] = _pipe(t.side or '' for t in tags)
                    row['tag_notes'] = _pipe(t.note or '' for t in tags)
                    row['tag_frames'] = _pipe(t.frame_number for t in tags)
                    rows.append(row)

        return rows

    def full_csv(self, video_id: Optional[int] = None, dataset: Optional[str] = None) -> str:
        """The full export as CSV text."""
        return rows_to_csv(self.full_columns(), self.full_rows(video_id=video_id, dataset=dataset))


def rows_to_csv(columns: List[str], rows: List[dict]) -> str:
    """Serialize dict rows to CSV text with a fixed header."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()
