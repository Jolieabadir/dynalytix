"""
Data models for labeling system.

Three-lens model: Environment / Strategy / Outcome
These are pure Python dataclasses with no database dependencies.
Database layer handles persistence separately.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Video:
    """Represents an uploaded video with metadata."""

    id: Optional[int] = None
    filename: str = ""
    path: str = ""
    csv_path: str = ""
    fps: float = 0.0
    total_frames: int = 0
    duration_ms: float = 0.0
    uploaded_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        if self.uploaded_at:
            data['uploaded_at'] = self.uploaded_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'Video':
        """Create from dictionary."""
        if 'uploaded_at' in data and isinstance(data['uploaded_at'], str):
            data['uploaded_at'] = datetime.fromisoformat(data['uploaded_at'])
        return cls(**data)


@dataclass
class Move:
    """
    Represents a labeled climbing move (Lens 2: Strategy).

    Contains move boundaries and strategy information.
    """

    id: Optional[int] = None
    video_id: int = 0
    frame_start: int = 0
    frame_end: int = 0
    timestamp_start_ms: float = 0.0
    timestamp_end_ms: float = 0.0

    # Strategy lens
    approach: str = ""  # static | dynamic | coordination
    size: str = ""  # small | medium | large
    move_tags: list[str] = field(default_factory=list)  # multi-select from MOVE_TAGS
    timing: Optional[str] = None  # simultaneous | sequential | alternating
    dyno_style: Optional[str] = None  # double_clutch | paddle | single_arm_catch (only when dyno tag)

    # Quality metrics (unchanged)
    form_quality: int = 3  # 1-5
    effort_level: int = 5  # 0-10

    # Contextual data (kept but unused - design decision pending)
    contextual_data: dict = field(default_factory=dict)

    # Tags and description
    tags: list[str] = field(default_factory=list)
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

    One record per move, joined by move_id.
    """

    id: Optional[int] = None
    move_id: int = 0

    wall_angle: str = ""  # slab | vertical | gentle_overhang | steep
    hold_type_reaching: str = ""  # horizontal_edge | gaston | side_pull | undercling
    hold_type_non_reaching: str = ""  # horizontal_edge | gaston | side_pull | undercling
    hold_quality: list[str] = field(default_factory=list)  # multi-select: incut | sloped | small

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

    result: str = ""  # success | fall
    reach_detail: str = ""  # reached_controlled | reached_not_controlled | didnt_reach
    foot_cut: bool = False
    confidence: str = ""  # low | med | high

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
    frame_number: int = 0
    timestamp_ms: float = 0.0

    # Tag type from TAG_TYPES
    tag_type: str = ""

    # For sensation tags (0-10 scale, None for non-sensation tags)
    level: Optional[int] = None

    # Body part locations (for sensation tags)
    locations: list[str] = field(default_factory=list)

    # New fields for three-lens schema
    side: Optional[str] = None  # left | right | null
    traction_source: Optional[str] = None  # hip | hand | null
    traction_direction: Optional[str] = None  # free text, nullable

    # Optional note
    note: str = ""

    # Metadata
    tagged_at: Optional[datetime] = None

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
]

TIMINGS = ['simultaneous', 'sequential', 'alternating']

DYNO_STYLES = ['double_clutch', 'paddle', 'single_arm_catch']

# =============================================================================
# LENS 1: ENVIRONMENT CONSTANTS
# =============================================================================

WALL_ANGLES = ['slab', 'vertical', 'gentle_overhang', 'steep']

HOLD_TYPES = ['horizontal_edge', 'gaston', 'side_pull', 'undercling', 'jug', 'pinch']

HOLD_QUALITIES = ['incut', 'sloped', 'small']

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

TRACTION_SOURCES = ['hip', 'hand']

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
