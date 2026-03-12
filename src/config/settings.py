"""
Configuration settings for Dynalytix.
"""
from dataclasses import dataclass, field


@dataclass
class Settings:
    """
    Configuration settings for pose estimation and analysis.
    
    Attributes:
        min_detection_confidence: Minimum confidence for pose detection
        min_tracking_confidence: Minimum confidence for pose tracking
        visibility_threshold: Minimum visibility to consider landmark valid
    """
    min_detection_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    visibility_threshold: float = 0.5
    
    # Angle definitions: (name, point_a, point_b, point_c)
    # Angle is measured at point_b
    ANGLE_DEFINITIONS: list[tuple[str, str, str, str]] = field(default_factory=lambda: [
        # Arms
        ('left_elbow', 'left_shoulder', 'left_elbow', 'left_wrist'),
        ('right_elbow', 'right_shoulder', 'right_elbow', 'right_wrist'),
        ('left_shoulder', 'left_hip', 'left_shoulder', 'left_elbow'),
        ('right_shoulder', 'right_hip', 'right_shoulder', 'right_elbow'),
        
        # Legs
        ('left_hip', 'left_shoulder', 'left_hip', 'left_knee'),
        ('right_hip', 'right_shoulder', 'right_hip', 'right_knee'),
        ('left_knee', 'left_hip', 'left_knee', 'left_ankle'),
        ('right_knee', 'right_hip', 'right_knee', 'right_ankle'),
        ('left_ankle', 'left_knee', 'left_ankle', 'left_heel'),
        ('right_ankle', 'right_knee', 'right_ankle', 'right_heel'),
    ])
