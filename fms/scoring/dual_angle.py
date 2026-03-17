"""
Dual-Angle Processing for Movement Assessments.

The patient performs the assessment TWICE — once filmed from the front,
once from the side. Each recording is an independent performance.

Each recording is scored independently using the existing single-angle
engine. Then the final result merges criterion-level results, picking
from whichever view is optimal for each measurement.

This is simpler and more robust than frame-level alignment because
the two recordings have completely different timestamps and depth frames.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .deep_squat import (
    score_deep_squat,
    CriterionResult,
    DeepSquatResult,
)


# Which view is preferred for each criterion
# Side view: sagittal plane measurements (depth, trunk/tibia inclination, ankle)
# Front view: frontal plane measurements (knee valgus/varus, bilateral asymmetry)
CRITERION_PREFERRED_VIEW: dict[str, str] = {
    "Squat Depth (femur below horizontal)": "side",
    "Torso-Tibia Alignment": "side",
    "Knee-Over-Foot Alignment": "front",
    "Heel Position (ankle dorsiflexion)": "side",
    "Lumbar Flexion Control": "side",
}

# Bilateral differences are best measured from the front view
BILATERAL_PREFERRED_VIEW = "front"


@dataclass
class PairedAssessment:
    """Result of a dual-angle assessment."""
    front_result: Optional[DeepSquatResult] = None
    side_result: Optional[DeepSquatResult] = None
    merged_result: Optional[DeepSquatResult] = None
    view_sources: dict[str, str] = field(default_factory=dict)
    front_csv_path: str = ""
    side_csv_path: str = ""
    has_front: bool = False
    has_side: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "dual_angle": True,
            "has_front": self.has_front,
            "has_side": self.has_side,
            "view_sources": self.view_sources,
            "front_csv": self.front_csv_path,
            "side_csv": self.side_csv_path,
        }
        if self.merged_result:
            result["merged"] = self.merged_result.to_dict()
        if self.front_result:
            result["front"] = self.front_result.to_dict()
        if self.side_result:
            result["side"] = self.side_result.to_dict()
        return result


def _find_criterion_by_name(
    criteria: list[CriterionResult],
    name: str,
) -> Optional[CriterionResult]:
    """Find a criterion by name in a list of results."""
    for c in criteria:
        if c.name == name:
            return c
    return None


def _merge_criteria(
    front_result: Optional[DeepSquatResult],
    side_result: Optional[DeepSquatResult],
) -> tuple[list[CriterionResult], dict[str, str]]:
    """
    Merge criteria from both views, picking preferred view for each.

    Returns:
        Tuple of (merged criteria list, view source mapping)
    """
    merged = []
    sources = {}

    # Collect all criterion names from both views
    all_names = []
    if side_result:
        all_names = [c.name for c in side_result.criteria]
    if front_result:
        for c in front_result.criteria:
            if c.name not in all_names:
                all_names.append(c.name)

    for name in all_names:
        preferred = CRITERION_PREFERRED_VIEW.get(name, "side")

        front_c = _find_criterion_by_name(front_result.criteria, name) if front_result else None
        side_c = _find_criterion_by_name(side_result.criteria, name) if side_result else None

        # Pick from preferred view if available, fall back to other view
        if preferred == "front" and front_c:
            chosen = CriterionResult(
                name=front_c.name,
                passed=front_c.passed,
                value=front_c.value,
                threshold=front_c.threshold,
                detail=front_c.detail + " [from front view]",
            )
            sources[name] = "front"
        elif preferred == "side" and side_c:
            chosen = CriterionResult(
                name=side_c.name,
                passed=side_c.passed,
                value=side_c.value,
                threshold=side_c.threshold,
                detail=side_c.detail + " [from side view]",
            )
            sources[name] = "side"
        elif front_c:
            # Preferred view unavailable, use front as fallback
            chosen = CriterionResult(
                name=front_c.name,
                passed=front_c.passed,
                value=front_c.value,
                threshold=front_c.threshold,
                detail=front_c.detail + " [from front view — preferred view unavailable]",
            )
            sources[name] = "front (fallback)"
        elif side_c:
            # Preferred view unavailable, use side as fallback
            chosen = CriterionResult(
                name=side_c.name,
                passed=side_c.passed,
                value=side_c.value,
                threshold=side_c.threshold,
                detail=side_c.detail + " [from side view — preferred view unavailable]",
            )
            sources[name] = "side (fallback)"
        else:
            # No data from either view
            chosen = CriterionResult(
                name=name,
                passed=False,
                detail="No data from either view",
            )
            sources[name] = "none"

        merged.append(chosen)

    return merged, sources


def score_deep_squat_dual(
    front_csv_path: str = "",
    side_csv_path: str = "",
    pain_reported: bool = False,
) -> PairedAssessment:
    """
    Score a deep squat from two separate recordings (front and side views).

    Each recording is scored independently using the existing single-angle engine.
    Results are merged at the criterion level, with each criterion pulling from
    whichever view is optimal for that measurement.

    Args:
        front_csv_path: Path to the front view pose CSV (optional).
        side_csv_path: Path to the side view pose CSV (optional).
        pain_reported: Whether pain was reported during either recording.

    Returns:
        PairedAssessment with individual and merged results.
    """
    paired = PairedAssessment(
        front_csv_path=front_csv_path,
        side_csv_path=side_csv_path,
    )

    # Pain override — applies to the whole assessment
    if pain_reported:
        pain_result = DeepSquatResult(
            score=0,
            pain_reported=True,
            criteria=[
                CriterionResult(
                    name="Pain Screen",
                    passed=False,
                    detail="Pain reported. Score set to 0.",
                )
            ],
        )
        paired.merged_result = pain_result
        return paired

    # Score front view if provided
    if front_csv_path and Path(front_csv_path).exists():
        try:
            paired.front_result = score_deep_squat(front_csv_path, pain_reported=False)
            paired.has_front = True
        except Exception as e:
            print(f"Front view scoring failed: {e}")

    # Score side view if provided
    if side_csv_path and Path(side_csv_path).exists():
        try:
            paired.side_result = score_deep_squat(side_csv_path, pain_reported=False)
            paired.has_side = True
        except Exception as e:
            print(f"Side view scoring failed: {e}")

    # Handle single-view fallback cases
    if paired.has_front and not paired.has_side:
        paired.merged_result = paired.front_result
        paired.view_sources = {c.name: "front (only view)" for c in paired.front_result.criteria}
        return paired

    if paired.has_side and not paired.has_front:
        paired.merged_result = paired.side_result
        paired.view_sources = {c.name: "side (only view)" for c in paired.side_result.criteria}
        return paired

    if not paired.has_front and not paired.has_side:
        paired.merged_result = DeepSquatResult(
            score=1,
            criteria=[
                CriterionResult(
                    name="No Data",
                    passed=False,
                    detail="No valid recordings available.",
                )
            ],
        )
        return paired

    # Both views available — merge at criterion level
    merged_criteria, view_sources = _merge_criteria(paired.front_result, paired.side_result)
    paired.view_sources = view_sources

    # Bilateral differences from preferred view
    if BILATERAL_PREFERRED_VIEW == "front":
        bilateral = paired.front_result.left_right_differences
    else:
        bilateral = paired.side_result.left_right_differences

    # Merge angles from both views
    merged_angles = {}
    if paired.side_result:
        merged_angles.update(paired.side_result.angles_at_depth)
    if paired.front_result:
        for k, v in paired.front_result.angles_at_depth.items():
            # Prefix with "front_" if key already exists from side view
            merged_angles[f"front_{k}" if k in merged_angles else k] = v

    # === SCORING LOGIC ===
    # Depth is the gatekeeper. All other criteria are compensations.
    depth = _find_criterion_by_name(merged_criteria, "Squat Depth (femur below horizontal)")
    alignment = _find_criterion_by_name(merged_criteria, "Torso-Tibia Alignment")
    knee = _find_criterion_by_name(merged_criteria, "Knee-Over-Foot Alignment")
    heel = _find_criterion_by_name(merged_criteria, "Heel Position (ankle dorsiflexion)")
    lumbar = _find_criterion_by_name(merged_criteria, "Lumbar Flexion Control")

    can_complete = depth.passed if depth else False
    no_compensations = (
        (alignment.passed if alignment else True)
        and (knee.passed if knee else True)
        and (heel.passed if heel else True)
        and (lumbar.passed if lumbar else True)
    )

    if can_complete and no_compensations:
        score = 3
    elif can_complete:
        score = 2
    else:
        score = 1

    paired.merged_result = DeepSquatResult(
        score=score,
        criteria=merged_criteria,
        pain_reported=False,
        max_depth_frame=paired.side_result.max_depth_frame if paired.side_result else 0,
        angles_at_depth=merged_angles,
        landmarks_at_depth=paired.side_result.landmarks_at_depth if paired.side_result else {},
        left_right_differences=bilateral,
    )

    return paired
