"""
Data models for FMS (Functional Movement Screen) assessment system.

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
class Assessment:
    """
    Represents an FMS (Functional Movement Screen) assessment.

    Contains assessment boundaries, test type, and scoring data.
    """

    id: Optional[int] = None
    video_id: int = 0
    frame_start: int = 0
    frame_end: int = 0
    timestamp_start_ms: float = 0.0
    timestamp_end_ms: float = 0.0

    # Core assessment data
    test_type: str = ""  # 'deep_squat', etc.
    score: int = 2  # FMS 0-3 scale (0=pain, 1=can't complete, 2=compensation, 3=perfect)

    # Scoring criteria observations (stored as dict - specific to test type)
    # Example: {'heels_elevated': True, 'knees_cave_inward': False, ...}
    criteria_data: dict = field(default_factory=dict)

    # Compensation patterns observed
    # Example: ['heel_rise', 'forward_lean', 'knee_valgus']
    compensations: list[str] = field(default_factory=list)

    # Tags and notes
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    # Metadata
    assessed_at: Optional[datetime] = None

    def duration_seconds(self) -> float:
        """Calculate assessment duration in seconds."""
        return (self.timestamp_end_ms - self.timestamp_start_ms) / 1000.0

    def frame_count(self) -> int:
        """Calculate number of frames in this assessment."""
        return self.frame_end - self.frame_start + 1

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        if self.assessed_at:
            data['assessed_at'] = self.assessed_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'Assessment':
        """Create from dictionary."""
        if 'assessed_at' in data and isinstance(data['assessed_at'], str):
            data['assessed_at'] = datetime.fromisoformat(data['assessed_at'])
        return cls(**data)


@dataclass
class FrameTag:
    """
    Represents a tag on a specific frame within an assessment.

    Used for precise observation tracking (pain, compensation, form breakdown).
    """

    id: Optional[int] = None
    assessment_id: int = 0
    frame_number: int = 0
    timestamp_ms: float = 0.0
    
    # Tag type: 'pain', 'tightness', 'weakness', 'asymmetry', 'compensation', 'loss_of_balance'
    tag_type: str = ""

    # Severity level (0-10 scale, None if not applicable)
    level: Optional[int] = None

    # Body part locations
    # Example: ['left_knee', 'lower_back']
    locations: list[str] = field(default_factory=list)
    
    # Optional note
    note: str = ""
    
    # Metadata
    tagged_at: Optional[datetime] = None
    
    def is_body_tag(self) -> bool:
        """Check if this is a body-related tag (pain/tightness/weakness)."""
        return self.tag_type in ['pain', 'tightness', 'weakness']
    
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
# FMS TEST TYPES
# =============================================================================
FMS_TESTS = [
    'deep_squat',
]

# =============================================================================
# FMS SCORING SCALE
# Standard FMS 0-3 scoring system
# =============================================================================
FMS_SCORES = {
    0: {
        'label': 'Pain',
        'description': 'Pain reported during any part of the movement'
    },
    1: {
        'label': "Can't Complete",
        'description': 'Unable to complete the movement pattern'
    },
    2: {
        'label': 'Compensation',
        'description': 'Completes movement with compensation patterns'
    },
    3: {
        'label': 'Perfect',
        'description': 'Performs movement correctly without compensation'
    },
}

# =============================================================================
# COMPENSATION PATTERNS - Observable movement dysfunctions
# =============================================================================
COMPENSATION_PATTERNS = [
    {
        'id': 'heel_rise',
        'label': 'Heel Rise',
        'description': 'Heels lift off the ground during descent'
    },
    {
        'id': 'forward_lean',
        'label': 'Excessive Forward Lean',
        'description': 'Torso leans forward excessively'
    },
    {
        'id': 'knee_valgus',
        'label': 'Knee Valgus',
        'description': 'Knees collapse inward'
    },
    {
        'id': 'arms_fall_forward',
        'label': 'Arms Fall Forward',
        'description': 'Unable to keep arms overhead'
    },
    {
        'id': 'lumbar_flexion',
        'label': 'Lumbar Flexion',
        'description': 'Rounding of the lower back'
    },
]

# =============================================================================
# FMS SCORING CRITERIA - Specific to each test type
# =============================================================================
FMS_SCORING_CRITERIA = {
    'deep_squat': {
        'dowel_position': {
            'question': 'Dowel position at bottom of squat',
            'options': ['overhead_aligned', 'forward_of_feet', 'lost_completely']
        },
        'torso_alignment': {
            'question': 'Torso alignment',
            'options': ['parallel_to_tibia', 'slight_forward_lean', 'excessive_forward_lean']
        },
        'knee_alignment': {
            'question': 'Knee alignment over feet',
            'options': ['aligned_over_toes', 'slight_valgus', 'significant_valgus']
        },
        'squat_depth': {
            'question': 'Squat depth achieved',
            'options': ['below_parallel', 'at_parallel', 'above_parallel']
        },
        'heel_contact': {
            'question': 'Heel contact with floor',
            'options': ['heels_down', 'slight_rise', 'heels_elevated']
        },
        'femur_position': {
            'question': 'Femur position at bottom',
            'options': ['below_horizontal', 'at_horizontal', 'above_horizontal']
        },
        'pain_reported': {
            'question': 'Pain reported during movement',
            'options': ['no_pain', 'discomfort', 'pain'],
            'auto_score_0': 'pain'  # If pain selected, score is automatically 0
        },
    },
}

# Body part options for pain/observation tagging
BODY_PARTS = [
    'left_shoulder', 'right_shoulder',
    'left_hip', 'right_hip',
    'left_knee', 'right_knee',
    'left_ankle', 'right_ankle',
    'lower_back', 'upper_back',
    'thoracic_spine', 'lumbar_spine',
]

# Tag types for FMS observations
TAG_TYPES = {
    'pain': 'Pain',
    'tightness': 'Tightness',
    'weakness': 'Weakness',
    'asymmetry': 'Asymmetry',
    'compensation': 'Compensation',
    'loss_of_balance': 'Loss of Balance',
}
