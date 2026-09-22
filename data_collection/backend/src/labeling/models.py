"""
Data models for labeling system.

Three-lens model: Environment / Strategy / Outcome
These are pure Python dataclasses with no database dependencies.
Database layer handles persistence separately.

Schema version 4 (storage v3): per-user scoping, hold bounding boxes, and
slot-based environments. Every record carries the owning Supabase user id.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


# =============================================================================
# TAXONOMY VERSION
# =============================================================================
#
# Stamped into every environment / outcome / frame_tag row at write time and
# exposed as `version` by /api/config, so an export can say which taxonomy a
# label was produced under. Bump it whenever a list below changes meaning.
# Rows written before the column existed were backfilled to 'pre-3.1'.

TAXONOMY_VERSION = "3.1.0"

# =============================================================================
# DATASET A / B CONSTANTS
# =============================================================================

DATASETS = ['A', 'B']
PREP_STATUSES = ['draft', 'ready', 'closed']
LOCKED_PREP_STATUSES = ['ready', 'closed']
ASSIGNMENT_COHORTS = ['validated', 'overlap']
ASSIGNMENT_STATUSES = ['assigned', 'in_progress', 'done']
RATER_TIERS = ['validated', 'open']


@dataclass
class Video:
    """Represents an uploaded video with metadata.

    Pose CSV, the original video and the export all live in R2; the table only
    keeps their object keys. ``r2_video_key`` stays None until the browser has
    finished its direct-to-R2 upload and called confirm-upload.
    """

    id: Optional[int] = None
    user_id: str = ""
    filename: str = ""
    fps: float = 0.0
    total_frames: int = 0
    duration_ms: float = 0.0
    # Intrinsic frame size in pixels. None for rows registered before the
    # dimensions migration; readers must treat that as "unknown", not a default.
    width: Optional[int] = None
    height: Optional[int] = None
    r2_video_key: Optional[str] = None
    r2_pose_csv_key: Optional[str] = None
    r2_export_key: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    # Server-side pose extraction job state. fps/total_frames/duration_ms/
    # width/height above are PROVISIONAL (client-measured from the <video>
    # element, fps defaulting to 30) until pose_status is 'done', at which
    # point the worker has overwritten them from ffprobe.
    pose_status: str = 'pending'
    pose_error: Optional[str] = None
    pose_started_at: Optional[datetime] = None
    pose_finished_at: Optional[datetime] = None

    # Dataset A / B split. ``user_id`` above is the owner / prepper
    # (owner_user_id semantics): the uploader on B, the admin who prepped on A.
    dataset: str = "B"  # A | B
    prep_status: str = "draft"  # draft | ready | closed
    # Prep-pass metadata, all optional.
    route_grade: Optional[str] = None
    wall_type: Optional[str] = None
    climber_experience: Optional[str] = None
    climber_height_cm: Optional[int] = None
    climber_ape_index_cm: Optional[int] = None
    camera_angle: Optional[str] = None
    gym: Optional[str] = None
    notes: Optional[str] = None

    def is_locked(self) -> bool:
        """True once holds and canonical moves may no longer change."""
        return self.prep_status in LOCKED_PREP_STATUSES

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        for key in ('uploaded_at', 'pose_started_at', 'pose_finished_at'):
            if getattr(self, key):
                data[key] = getattr(self, key).isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'Video':
        """Create from dictionary."""
        for key in ('uploaded_at', 'pose_started_at', 'pose_finished_at'):
            if key in data and isinstance(data[key], str):
                data[key] = datetime.fromisoformat(data[key])
        return cls(**data)


POSE_STATUSES = ('pending', 'processing', 'done', 'failed')


@dataclass
class Hold:
    """A hold on the wall, located by a normalized bounding box.

    Coordinates are fractions of frame width/height in the range 0-1 so they
    survive any later re-encode or resize of the source video.
    """

    id: Optional[int] = None
    video_id: int = 0
    user_id: str = ""
    bbox_x: float = 0.0
    bbox_y: float = 0.0
    bbox_w: float = 0.0
    bbox_h: float = 0.0
    source: str = "manual"  # detected | manual
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        if self.created_at:
            data['created_at'] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'Hold':
        """Create from dictionary."""
        if 'created_at' in data and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        return cls(**data)


@dataclass
class Move:
    """
    Represents a labeled climbing move (Lens 2: Strategy).

    Contains move boundaries and strategy information.
    """

    id: Optional[int] = None
    video_id: int = 0
    user_id: str = ""
    frame_start: int = 0
    frame_end: int = 0
    timestamp_start_ms: float = 0.0
    timestamp_end_ms: float = 0.0

    # Strategy lens
    approach: str = ""  # static | dynamic | coordination
    move_tags: list[str] = field(default_factory=list)  # multi-select from MOVE_TAGS
    size: str = ""  # small | medium | large

    # Quality metrics
    form_quality: int = 3  # 1-5
    effort_level: int = 5  # 0-10
    confidence: str = ""  # low | med | high

    description: str = ""

    # Metadata
    labeled_at: Optional[datetime] = None

    def duration_seconds(self) -> float:
        """Calculate move duration in seconds."""
        return (self.timestamp_end_ms - self.timestamp_start_ms) / 1000.0

    def frame_count(self) -> int:
        """Calculate number of frames in this move."""
        return self.frame_end - self.frame_start + 1

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        if self.labeled_at:
            data['labeled_at'] = self.labeled_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'Move':
        """Create from dictionary."""
        if 'labeled_at' in data and isinstance(data['labeled_at'], str):
            data['labeled_at'] = datetime.fromisoformat(data['labeled_at'])
        return cls(**data)


@dataclass
class Environment:
    """
    Represents the environment context for a move (Lens 1: Environment).

    One record per move, joined by move_id. Each of the four hold slots may
    point at a row in ``holds`` and carries its own type and quality list; all
    slots are optional, which covers no-hands, no-feet and one-hand moves.
    """

    id: Optional[int] = None
    move_id: int = 0
    user_id: str = ""

    wall_angle: str = ""  # slab | vertical | gentle_overhang | steep

    start_left_hold_id: Optional[int] = None
    start_left_hold_type: Optional[str] = None
    start_left_hold_quality: list[str] = field(default_factory=list)

    start_right_hold_id: Optional[int] = None
    start_right_hold_type: Optional[str] = None
    start_right_hold_quality: list[str] = field(default_factory=list)

    end_hold_id: Optional[int] = None
    end_hold_type: Optional[str] = None
    end_hold_quality: list[str] = field(default_factory=list)

    foot_hold_id: Optional[int] = None
    foot_hold_type: Optional[str] = None
    foot_hold_quality: list[str] = field(default_factory=list)

    # Taxonomy the row was labeled under; stamped by the API on every write.
    taxonomy_version: str = TAXONOMY_VERSION
    # Adjudicated / gold-standard row (set later, outside the rating pass).
    is_gold: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Environment':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class Outcome:
    """
    Represents the outcome of a move (Lens 3: Outcome).

    One record per move, joined by move_id.
    """

    id: Optional[int] = None
    move_id: int = 0
    user_id: str = ""

    result: str = ""  # success | fall
    reach_detail: str = ""  # reached_controlled | reached_not_controlled | didnt_reach
    confidence: str = ""  # low | med | high

    taxonomy_version: str = TAXONOMY_VERSION
    is_gold: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Outcome':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class FrameTag:
    """
    Represents a tag on a specific frame within a move.

    Used for precise sensation tracking (pain, instability, weakness, etc.).
    """

    id: Optional[int] = None
    move_id: int = 0
    user_id: str = ""
    frame_number: int = 0
    timestamp_ms: float = 0.0

    # Tag type from TAG_TYPES
    tag_type: str = ""

    side: Optional[str] = None  # left | right | null

    # For sensation tags (0-10 scale, None for non-sensation tags)
    level: Optional[int] = None

    # Body part locations (for sensation tags)
    locations: list[str] = field(default_factory=list)

    # Optional note
    note: str = ""

    # Metadata
    tagged_at: Optional[datetime] = None
    taxonomy_version: str = TAXONOMY_VERSION
    is_gold: bool = False

    def is_sensation_tag(self) -> bool:
        """Check if this is a sensation tag (pain/instability/weakness)."""
        return self.tag_type in ['sharp_pain', 'dull_pain', 'unstable', 'weak']

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        if self.tagged_at:
            data['tagged_at'] = self.tagged_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'FrameTag':
        """Create from dictionary."""
        if 'tagged_at' in data and isinstance(data['tagged_at'], str):
            data['tagged_at'] = datetime.fromisoformat(data['tagged_at'])
        return cls(**data)


@dataclass
class RaterProfile:
    """Who a labeler is, collected once at first sign-in.

    ``tier``/``validation_note``/``is_admin`` are set by an admin, never by the
    rater themself. ``is_admin`` doubles as the admin flag for the whole app.
    """

    user_id: str = ""
    display_name: str = ""
    tier: str = "open"  # validated | open
    years_climbing: Optional[int] = None
    coaching_cert: Optional[str] = None
    highest_grade: Optional[str] = None
    research_background: bool = False
    validation_note: Optional[str] = None
    is_admin: bool = False
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        if self.created_at:
            data['created_at'] = self.created_at.isoformat()
        return data


@dataclass
class VideoAssignment:
    """One rater's assignment to rate one Dataset A video."""

    id: Optional[int] = None
    video_id: int = 0
    rater_user_id: str = ""
    cohort: str = "validated"  # validated | overlap
    status: str = "assigned"  # assigned | in_progress | done
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def is_open(self) -> bool:
        """True while the rater may still write labels under it."""
        return self.status in ('assigned', 'in_progress')

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        for key in ('assigned_at', 'completed_at'):
            if getattr(self, key):
                data[key] = getattr(self, key).isoformat()
        return data


# =============================================================================
# LENS 2: STRATEGY CONSTANTS
# =============================================================================

APPROACHES = ['static', 'dynamic', 'coordination']

SIZES = ['small', 'medium', 'large']

MOVE_TAGS = [
    'bump',
    'mantle',
    'balance',
    'upper_body_coordination',
    'lower_body_coordination',
    'heel_hook',
    'toe_hook',
    'no_feet_on',
    'deadpoint',
    'dyno',
    'foot_move',
    'no_hands',
    'technical',
    'tension',
]

# =============================================================================
# LENS 1: ENVIRONMENT CONSTANTS
# =============================================================================

WALL_ANGLES = ['slab', 'vertical', 'gentle_overhang', 'steep']

HOLD_TYPES = ['horizontal_edge', 'gaston', 'side_pull', 'undercling', 'jug', 'pinch']

HOLD_QUALITIES = ['incut', 'sloped', 'small']

# The four hold slots an environment can reference. Column names are derived
# from these: {slot}_hold_id, {slot}_hold_type, {slot}_hold_quality.
HOLD_SLOTS = ['start_left', 'start_right', 'end', 'foot']

HOLD_SOURCES = ['detected', 'manual']

# =============================================================================
# LENS 3: OUTCOME CONSTANTS
# =============================================================================

RESULTS = ['success', 'fall']

REACH_DETAILS = ['reached_controlled', 'reached_not_controlled', 'didnt_reach']

CONFIDENCE_LEVELS = ['low', 'med', 'high']

# =============================================================================
# SENSATION (FRAME TAG) CONSTANTS
# =============================================================================

TAG_TYPES = {
    'sharp_pain': 'Sharp Pain',
    'dull_pain': 'Dull Pain',
    'audible_pop': 'Audible Pop',
    'unstable': 'Unstable',
    'stretch': 'Stretch',
    'strong': 'Strong',
    'weak': 'Weak',
    'pumped': 'Pumped',
    'fatigue': 'Fatigue',
}

SIDES = ['left', 'right']

# Body part options for sensation tagging (unchanged - 16 entries)
BODY_PARTS = [
    'left_shoulder', 'right_shoulder',
    'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist',
    'left_hip', 'right_hip',
    'left_knee', 'right_knee',
    'left_ankle', 'right_ankle',
    'lower_back', 'upper_back',
    'core', 'forearms',
]


# =============================================================================
# DEFINITIONS
# =============================================================================
#
# Plain climber-facing wording for every option the labeling UI renders, so a
# first-time labeler never has to guess what a value means. Served by
# /api/config as `definitions` and shown as an "i" tooltip beside each option.
#
# Shape: {taxonomy_key: {value: {"description": str, "display_label": str?}}}
#
# `description` is required on every option. `display_label` is optional and
# overrides the label the UI would otherwise derive from the value — it exists
# so wording can be changed without touching a stored enum value (see
# REACH_DETAILS, where the wording is still being settled).
#
# These are additive: the flat taxonomy lists above remain the source of truth
# for validation, and a value missing from this map still renders, just with no
# tooltip.

DEFINITIONS = {
    # --- Lens 2: Strategy ---
    'approaches': {
        'static': {
            'description': 'Controlled throughout. The climber could stop and hold '
                           'still at any point in the move.',
        },
        'dynamic': {
            'description': 'Uses momentum. There is a point where the climber is '
                           'committed and could not stop halfway.',
        },
        'coordination': {
            'description': 'Several body parts have to move in a specific order or '
                           'rhythm for the move to work at all.',
        },
    },
    'sizes': {
        'small': {
            'description': 'A short movement — roughly a forearm\'s length or less. '
                           'Adjusting, matching, or a small bump.',
        },
        'medium': {
            'description': 'A normal reach. The climber moves about an arm\'s length '
                           'without fully extending.',
        },
        'large': {
            'description': 'A long movement — full extension, or a jump. The climber '
                           'covers as much distance as they can.',
        },
    },
    'move_tags': {
        'bump': {
            'description': 'Moving a hand to an intermediate hold, then straight on '
                           'to the real target without settling.',
        },
        'mantle': {
            'description': 'Pressing down on a hold to push the body up over it, '
                           'like climbing out of a swimming pool.',
        },
        'balance': {
            'description': 'Staying on depends on body position rather than on '
                           'pulling hard.',
        },
        'upper_body_coordination': {
            'description': 'The arms and torso have to time together — for example '
                           'both hands moving in sequence during one motion.',
        },
        'lower_body_coordination': {
            'description': 'The legs and hips have to time together — for example a '
                           'foot swap or a rockover driven from below.',
        },
        'heel_hook': {
            'description': 'The heel is placed on a hold and pulled with, so the leg '
                           'works like a third arm.',
        },
        'toe_hook': {
            'description': 'The top of the foot pulls against a hold or volume to '
                           'stop the body swinging out.',
        },
        'no_feet_on': {
            'description': 'Both feet are off the wall for some part of the move, '
                           'while at least one hand stays on.',
        },
        'deadpoint': {
            'description': 'A dynamic reach caught at the weightless top of the '
                           'motion. At least one hand stays on the wall throughout.',
        },
        'dyno': {
            'description': 'A jump. Every point of contact leaves the wall at the '
                           'same time.',
        },
        'foot_move': {
            'description': 'The hands stay where they are; the move is all in the '
                           'feet.',
        },
        'no_hands': {
            'description': 'The hands are entirely off the wall — the climber is '
                           'held on by feet and body position alone.',
        },
        'technical': {
            'description': 'Succeeds on precision rather than power. Getting it '
                           'slightly wrong makes it much harder.',
        },
        'tension': {
            'description': 'Demands core and body tension to keep the hips in and '
                           'the feet from cutting.',
        },
    },
    # --- Lens 1: Environment ---
    'wall_angles': {
        'slab': {
            'description': 'Leans away from the climber — less than vertical. Weight '
                           'sits mostly on the feet.',
        },
        'vertical': {
            'description': 'Straight up and down, near 90°.',
        },
        'gentle_overhang': {
            'description': 'Leans over the climber slightly. Noticeably steeper than '
                           'vertical but not roof-like.',
        },
        'steep': {
            'description': 'Leans well over the climber. Body tension is needed just '
                           'to keep the feet on.',
        },
    },
    'hold_types': {
        'horizontal_edge': {
            'description': 'A flat edge gripped from above with the fingers, pulling '
                           'straight down.',
        },
        'gaston': {
            'description': 'A vertical hold pulled outward with the thumb down and '
                           'the elbow out, like opening a sliding door.',
        },
        'side_pull': {
            'description': 'A vertical hold pulled sideways toward the body, with '
                           'the thumb up.',
        },
        'undercling': {
            'description': 'A hold gripped from underneath, palm up, pulling up '
                           'into it.',
        },
        'jug': {
            'description': 'A big, obvious hold the whole hand fits into. Easy to '
                           'hang from.',
        },
        'pinch': {
            'description': 'Squeezed between the thumb on one side and the fingers '
                           'on the other.',
        },
    },
    'hold_qualities': {
        'incut': {
            'description': 'The gripping surface curves back in toward the wall, so '
                           'the fingers get a positive lip to pull on.',
        },
        'sloped': {
            'description': 'The surface rounds away with no positive edge. Held by '
                           'friction and body position.',
        },
        'small': {
            'description': 'Little room for the fingers — a pad or two at most.',
        },
    },
    'hold_slots': {
        'start_left': {
            'description': 'The hold the left hand is on when the move begins.',
        },
        'start_right': {
            'description': 'The hold the right hand is on when the move begins.',
        },
        'end': {
            'description': 'The hold the climber is moving to — what the reaching '
                           'hand is aiming for.',
        },
        'foot': {
            'description': 'The main foothold the move is driven from. Optional — '
                           'leave empty if no single foot matters.',
        },
    },
    # --- Lens 3: Outcome ---
    'results': {
        'success': {
            'description': 'The climber finished the move and stayed on the wall.',
        },
        'fall': {
            'description': 'The climber came off the wall during or at the end of '
                           'this move.',
        },
    },
    # Wording here is still being settled with Taylor. The stored values are
    # fixed; `display_label` is what the UI shows, so the wording can change
    # without a schema migration or a rewrite of existing rows.
    'reach_details': {
        'reached_controlled': {
            'display_label': 'Reached it — in control',
            'description': 'Got the target hold and was immediately stable on it, '
                           'ready to move again.',
        },
        'reached_not_controlled': {
            'display_label': 'Reached it — not in control',
            'description': 'Touched or caught the target hold but was off balance, '
                           'swinging, or barely holding on.',
        },
        'didnt_reach': {
            'display_label': 'Did not reach it',
            'description': 'Never made contact with the target hold.',
        },
    },
    'confidence_levels': {
        'low': {
            'description': 'You are unsure about the labels you just gave — the '
                           'camera angle, the speed, or the taxonomy made it a guess.',
        },
        'med': {
            'description': 'You are reasonably sure about the labels, with some '
                           'doubt on one or two fields.',
        },
        'high': {
            'description': 'You are confident the labels describe what happened.',
        },
    },
    # --- Sensation (Frame Tags) ---
    'tag_types': {
        'sharp_pain': {
            'description': 'A sudden, stabbing pain at a specific spot. Worth '
                           'stopping for.',
        },
        'dull_pain': {
            'description': 'A duller, spread-out ache rather than a sharp point.',
        },
        'audible_pop': {
            'description': 'A pop, click, or snap that could be heard or felt.',
        },
        'unstable': {
            'description': 'The joint or body position felt like it could give way.',
        },
        'stretch': {
            'description': 'A strong stretching sensation at the end of the range '
                           'of motion.',
        },
        'strong': {
            'description': 'The position felt powerful and solid — more in reserve.',
        },
        'weak': {
            'description': 'The position felt underpowered — not enough strength in '
                           'that direction.',
        },
        'pumped': {
            'description': 'Forearms burning and swelling from sustained gripping.',
        },
        'fatigue': {
            'description': 'General tiredness across the body, not localized.',
        },
    },
}
