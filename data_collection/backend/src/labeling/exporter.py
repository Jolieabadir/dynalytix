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


STRATEGY_FIELDS = ['approach', 'move_tags', 'size', 'form_quality', 'effort_level', 'confidence']
_EMPTY_STRATEGY = {f: None for f in STRATEGY_FIELDS}


def _blank(value):
    return '' if value is None else value


def strategy_for(db: Database, move, user_id: str) -> dict:
    """The Strategy lens values one labeler gave a move, as a dict.

    A rater's own `strategies` row when there is one (paper clips: every
    rater labels strategy independently; no effort level). Otherwise the
    canonical move row's strategy, but only for the labeler who created the
    move (the community owner labeling their own climb, or legacy rows).
    Anyone else has no strategy on that move: all values None.
    """
    row = db.get_strategy_for_move(move.id, user_id)
    if row:
        return {
            'approach': row.approach, 'move_tags': list(row.move_tags), 'size': row.size,
            'form_quality': row.form_quality, 'effort_level': None,
            'confidence': row.confidence or None,
        }
    if str(move.user_id) == str(user_id) and move.approach:
        return {
            'approach': move.approach, 'move_tags': list(move.move_tags or []), 'size': move.size,
            'form_quality': move.form_quality, 'effort_level': move.effort_level,
            'confidence': move.confidence or None,
        }
    return dict(_EMPTY_STRATEGY)


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

    def _build_frame_labels(
        self,
        video_id: int,
        user_id: str,
        moves: Optional[List] = None,
        hold_lookup=None,
    ) -> dict:
        """Expand each move's labels across every frame it covers.

        Default (per-video, owner) behaviour: the caller's own moves and
        labels. The admin full export passes the video's canonical move list
        and an unscoped hold lookup, and user_id is then the rater whose
        environment / outcome / frame tags are joined in.
        """
        frame_labels = {}
        if moves is None:
            moves = self.db.get_moves_for_video(video_id, user_id)
        if hold_lookup is None:
            hold_lookup = lambda hold_id: self.db.get_hold(hold_id, user_id)  # noqa: E731

        for move in moves:
            env = self.db.get_environment_for_move(move.id, user_id)
            outcome = self.db.get_outcome_for_move(move.id, user_id)
            tags = self.db.get_frame_tags_for_move(move.id, user_id)
            strategy = strategy_for(self.db, move, user_id)

            labels = {
                'move_id': move.id,
                # Lens 2: Strategy (the rater's own row; see strategy_for)
                'approach': strategy['approach'],
                'size': strategy['size'],
                'move_tags': _pipe(strategy['move_tags']),
                'form_quality': _blank(strategy['form_quality']),
                'effort_level': _blank(strategy['effort_level']),
                'move_confidence': strategy['confidence'] or '',
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
                    hold = hold_lookup(hold_id)
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
# Admin exports (runbook W1, reshaped for the single dataset in W2)
# =============================================================================
#
# Two CSVs an admin can pull across every video and every rater:
#
#   long  - one row per (video, move, rater, lens, field). The IRR input; a
#           notebook (or scripts/irr_alpha.py) pivots it by rater and computes
#           Krippendorff's alpha per field.
#   full  - the per-video export's shape (one row per pose frame, label columns
#           appended) for every video and every rater, with identity columns
#           in front. Frames of a video are repeated once per rater.

# Video-level provenance repeated on every row so each export stands alone.
# ifsc_profile_url is deliberately never exported.
VIDEO_PROVENANCE_COLUMNS = [
    'source_type', 'source_url', 'clip_start_ms', 'clip_end_ms',
    'event_name', 'event_date', 'athlete_id', 'height_cm', 'height_source',
]

LONG_COLUMNS = [
    'video_id', 'irr_overlap', *VIDEO_PROVENANCE_COLUMNS,
    'move_id', 'move_index', 'rater_user_id',
    'lens', 'field', 'value', 'taxonomy_version', 'is_gold',
]

LENS_ENVIRONMENT = 'environment'
LENS_STRATEGY = 'strategy'
LENS_OUTCOME = 'outcome'
LENS_FRAME_TAGS = 'frame_tags'

OUTCOME_FIELDS = ['result', 'reach_detail', 'confidence']

FULL_ID_COLUMNS = [
    'video_id', 'prep_status', 'irr_overlap', 'owner_user_id', 'filename',
    *VIDEO_PROVENANCE_COLUMNS,
    'rater_user_id',
]


def _pipe(values) -> str:
    return '|'.join(str(v) for v in values) if values else ''


def _cell(value) -> str:
    """Render one long-format value: None -> '', bool -> 'true'/'false',
    list -> pipe-delimited."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (list, tuple)):
        return _pipe(value)
    return str(value)


def environment_fields() -> List[str]:
    """The environment lens fields, in the order the long export emits them.

    wall_angle, then per hold slot the chosen hold's id, its type and its
    quality list (pipe-delimited). hold_id is included beyond the runbook's
    "type + quality" so agreement on WHICH hold was used can be measured too.
    """
    fields = ['wall_angle']
    for slot in HOLD_SLOTS:
        fields += [f'{slot}_hold_id', f'{slot}_hold_type', f'{slot}_hold_quality']
    return fields


def frame_tag_value(tag) -> str:
    """The long-export value of one frame tag: frame:level:side:locations.

    locations is itself pipe-delimited (a multi-select). level and side are
    empty for tag types that do not carry them.
    """
    level = '' if tag.level is None else str(tag.level)
    return f'{tag.frame_number}:{level}:{tag.side or ""}:{_pipe(tag.locations)}'


class AdminExporter:
    """Cross-user, cross-video exports for admins.

    Community videos (the dormant self-upload flow) are excluded unless
    include_community is set: the paper's exports are paper footage only.
    """

    def __init__(self, db: Database):
        self.db = db

    # ---------- shared lookups ----------

    def _assigned(self, video_id: int) -> set:
        """Every rater assigned to a video."""
        return {a.rater_user_id for a in self.db.list_assignments(video_id)}

    def _videos(self, video_id: Optional[int], include_community: bool,
                overlap_only: bool = False) -> List[Video]:
        return self.db.get_videos_for_export(
            video_id=video_id, include_community=include_community, overlap_only=overlap_only,
        )

    def _provenance(self, videos: List[Video]) -> Dict[int, dict]:
        """video_id -> the provenance cells (athlete height joined in)."""
        athletes = self.db.get_athletes_by_id(v.athlete_id for v in videos)
        out = {}
        for v in videos:
            athlete = athletes.get(v.athlete_id) if v.athlete_id else None
            out[v.id] = {
                'source_type': v.source_type,
                'source_url': v.source_url or '',
                'clip_start_ms': _blank(v.clip_start_ms),
                'clip_end_ms': _blank(v.clip_end_ms),
                'event_name': v.event_name or '',
                'event_date': v.event_date.isoformat() if v.event_date else '',
                'athlete_id': v.athlete_id or '',
                'height_cm': _blank(athlete.height_cm) if athlete else '',
                'height_source': athlete.height_source if athlete else '',
            }
        return out

    def _raters_on_move(self, move, assigned: set) -> set:
        raters = set(assigned)
        raters |= {s.user_id for s in self.db.get_strategies_for_move_all(move.id)}
        raters |= {e.user_id for e in self.db.get_environments_for_move_all(move.id)}
        raters |= {o.user_id for o in self.db.get_outcomes_for_move_all(move.id)}
        raters |= {t.user_id for t in self.db.get_frame_tags_for_move_all(move.id)}
        return raters

    # ---------- long format ----------

    def long_rows(self, video_id: Optional[int] = None, include_community: bool = False,
                  overlap_only: bool = False) -> List[dict]:
        """One dict per (video, move, rater, lens, field), sorted.

        Paper footage only by default (include_community adds the dormant
        self-upload videos); overlap_only keeps just the reliability subset;
        a video_id returns that one video whatever its source.

        Which raters appear on a move: everyone assigned to the video plus
        anyone who wrote a label row on the move; a move nobody has rated and
        nobody is assigned to falls back to the move's creator. Strategy
        comes from each rater's own strategies row (see strategy_for); a rater
        with none emits no strategy rows, which the alpha script reads as
        missing.
        """
        rows: List[dict] = []
        videos = self._videos(video_id, include_community, overlap_only)
        provenance = self._provenance(videos)

        for video in videos:
            assigned = self._assigned(video.id)
            moves = self.db.get_moves_for_video_any(video.id)

            for move_index, move in enumerate(moves):
                envs = {e.user_id: e for e in self.db.get_environments_for_move_all(move.id)}
                outcomes = {o.user_id: o for o in self.db.get_outcomes_for_move_all(move.id)}
                tags_by_rater: Dict[str, list] = {}
                for tag in self.db.get_frame_tags_for_move_all(move.id):
                    tags_by_rater.setdefault(tag.user_id, []).append(tag)
                strategies = {s.user_id: s for s in self.db.get_strategies_for_move_all(move.id)}

                raters = (set(assigned) | set(envs) | set(outcomes) | set(tags_by_rater)
                          | set(strategies))
                if not raters:
                    raters = {move.user_id}

                for rater in sorted(raters):
                    base = {
                        'video_id': video.id,
                        'irr_overlap': _cell(bool(video.irr_overlap)),
                        **provenance[video.id],
                        'move_id': move.id,
                        'move_index': move_index,
                        'rater_user_id': rater,
                    }

                    def emit(lens, field, value, taxonomy_version, is_gold):
                        rows.append(dict(
                            base, lens=lens, field=field, value=_cell(value),
                            taxonomy_version=taxonomy_version, is_gold=_cell(is_gold),
                        ))

                    env = envs.get(rater)
                    outcome = outcomes.get(rater)
                    tags = tags_by_rater.get(rater, [])

                    # Strategy: the rater's own row. On the creator's own
                    # community move it falls back to the move row, stamped
                    # with the version their other rows carry.
                    strategy_row = strategies.get(rater)
                    if strategy_row:
                        values = strategy_for(self.db, move, rater)
                        for field in STRATEGY_FIELDS:
                            if field == 'effort_level':
                                continue
                            emit(LENS_STRATEGY, field, values[field],
                                 strategy_row.taxonomy_version, strategy_row.is_gold)
                    elif str(move.user_id) == str(rater) and move.approach:
                        legacy_version = (
                            env.taxonomy_version if env else
                            outcome.taxonomy_version if outcome else
                            tags[0].taxonomy_version if tags else ''
                        )
                        for field in STRATEGY_FIELDS:
                            emit(LENS_STRATEGY, field, getattr(move, field), legacy_version, False)

                    if env:
                        for field in environment_fields():
                            emit(LENS_ENVIRONMENT, field, getattr(env, field),
                                 env.taxonomy_version, env.is_gold)

                    if outcome:
                        for field in OUTCOME_FIELDS:
                            emit(LENS_OUTCOME, field, getattr(outcome, field),
                                 outcome.taxonomy_version, outcome.is_gold)

                    for tag in tags:
                        emit(LENS_FRAME_TAGS, tag.tag_type, frame_tag_value(tag),
                             tag.taxonomy_version, tag.is_gold)

        rows.sort(key=lambda r: (
            r['video_id'], r['move_index'], r['move_id'], r['rater_user_id'],
            r['lens'], r['field'], r['value'],
        ))
        return rows

    def long_csv(self, video_id: Optional[int] = None, include_community: bool = False,
                 overlap_only: bool = False) -> str:
        """The long export as CSV text with exactly LONG_COLUMNS as the header."""
        return rows_to_csv(LONG_COLUMNS, self.long_rows(
            video_id=video_id, include_community=include_community, overlap_only=overlap_only,
        ))

    # ---------- full format ----------

    def full_rows(
        self,
        video_id: Optional[int] = None,
        include_community: bool = False,
    ) -> "tuple[List[str], List[dict]]":
        """(columns, rows): the per-video export shape across every user.

        For each video and each rater on it (assigned raters, anyone with a
        label row, else the owner), the video's pose CSV is streamed out of R2
        and that rater's labels are joined per frame exactly as
        Exporter.export_video does, with FULL_ID_COLUMNS in front. Pose
        columns are the union across videos, in first-seen order. A video
        whose pose CSV is missing from R2 still contributes one row per
        labeled frame with only frame_number filled, so no label is lost.
        """
        exporter = Exporter(self.db)
        pose_columns: List[str] = []
        seen = set()
        rows: List[dict] = []
        videos = self._videos(video_id, include_community)
        provenance = self._provenance(videos)

        for video in videos:
            assigned = self._assigned(video.id)
            moves = self.db.get_moves_for_video_any(video.id)
            holds = {h.id: h for h in self.db.get_holds_for_video_any(video.id)}

            raters = set(assigned)
            for move in moves:
                raters |= self._raters_on_move(move, set())
            if not raters:
                raters = {video.user_id}

            pose_rows = self._pose_rows(video)
            for name in (pose_rows[0].keys() if pose_rows else ['frame_number']):
                if name not in seen:
                    seen.add(name)
                    pose_columns.append(name)

            for rater in sorted(raters):
                frame_labels = exporter._build_frame_labels(
                    video.id, rater, moves=moves, hold_lookup=holds.get,
                )
                identity = {
                    'video_id': video.id,
                    'prep_status': video.prep_status,
                    'irr_overlap': _cell(bool(video.irr_overlap)),
                    'owner_user_id': video.user_id,
                    'filename': video.filename,
                    **provenance[video.id],
                    'rater_user_id': rater,
                }
                source_rows = pose_rows or [
                    {'frame_number': str(frame)} for frame in sorted(frame_labels)
                ]
                for pose_row in source_rows:
                    merged = exporter._merge_row(dict(pose_row), frame_labels)
                    rows.append(dict(identity, **merged))

        columns = FULL_ID_COLUMNS + pose_columns + Exporter.label_columns()
        return columns, rows

    def _pose_rows(self, video: Video) -> List[dict]:
        """The video's pose CSV as dict rows, or [] when it is not in R2 or
        the pose worker has not finished it (pose_status != 'done')."""
        if not video.r2_pose_csv_key or getattr(video, 'pose_status', 'done') != 'done':
            return []
        try:
            source = r2.get_object_stream(video.r2_pose_csv_key)
        except (FileNotFoundError, r2.R2NotConfigured):
            return []
        with source:
            text_stream = io.TextIOWrapper(source, encoding='utf-8', newline='')
            return list(csv.DictReader(text_stream))

    def full_csv(self, video_id: Optional[int] = None, include_community: bool = False) -> str:
        """The full export as CSV text."""
        columns, rows = self.full_rows(video_id=video_id, include_community=include_community)
        return rows_to_csv(columns, rows)


def rows_to_csv(columns: List[str], rows: List[dict]) -> str:
    """Serialize dict rows to CSV text with a fixed header."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()
