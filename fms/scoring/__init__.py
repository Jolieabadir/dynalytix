"""Movement Scoring Engine - Rule-based movement assessment."""
from .deep_squat import score_deep_squat, DeepSquatResult, CriterionResult
from .dual_angle import (
    score_deep_squat_dual,
    PairedAssessment,
    CRITERION_PREFERRED_VIEW,
)

__all__ = [
    "score_deep_squat",
    "DeepSquatResult",
    "CriterionResult",
    "score_deep_squat_dual",
    "PairedAssessment",
    "CRITERION_PREFERRED_VIEW",
]
