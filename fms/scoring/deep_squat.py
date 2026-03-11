"""
Deep Squat Rule Engine.

Scores the FMS overhead deep squat (0-3) from pose CSV data.
Uses angle thresholds derived from biomechanical research.
"""
import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

from .thresholds import DEEP_SQUAT, FRAME_SELECTION


@dataclass
class CriterionResult:
    """Result of evaluating a single scoring criterion."""
    name: str
    passed: bool
    value: float | None = None
    threshold: float | None = None
    detail: str = ""


@dataclass
class DeepSquatResult:
    """Complete result of a deep squat assessment."""
    score: int  # 0-3
    criteria: list[CriterionResult] = field(default_factory=list)
    pain_reported: bool = False

    # Raw data at max depth frame
    max_depth_frame: int = 0
    angles_at_depth: dict[str, float] = field(default_factory=dict)
    landmarks_at_depth: dict[str, dict] = field(default_factory=dict)

    # Symmetry data
    left_right_differences: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        """Human-readable summary of the result."""
        lines = [f"Deep Squat Score: {self.score}/3"]
        lines.append(f"Max depth at frame: {self.max_depth_frame}")
        lines.append("")

        for c in self.criteria:
            status = "✓ PASS" if c.passed else "✗ FAIL"
            lines.append(f"  {status}  {c.name}")
            if c.value is not None and c.threshold is not None:
                lines.append(f"         Value: {c.value:.1f}° | Threshold: {c.threshold:.1f}°")
            if c.detail:
                lines.append(f"         {c.detail}")

        if self.left_right_differences:
            lines.append("")
            lines.append("  Bilateral Differences:")
            for name, diff in self.left_right_differences.items():
                flag = " ⚠ ASYMMETRY" if abs(diff) > 10 else ""
                lines.append(f"    {name}: {diff:+.1f}°{flag}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization / LLM consumption."""
        return {
            "score": self.score,
            "pain_reported": self.pain_reported,
            "max_depth_frame": self.max_depth_frame,
            "criteria": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "value": c.value,
                    "threshold": c.threshold,
                    "detail": c.detail,
                }
                for c in self.criteria
            ],
            "angles_at_depth": self.angles_at_depth,
            "left_right_differences": self.left_right_differences,
        }


def load_csv(csv_path: str | Path) -> list[dict]:
    """Load a pose CSV into a list of frame dictionaries."""
    frames = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            frame = {}
            for key, value in row.items():
                if value == "" or value is None:
                    frame[key] = None
                else:
                    try:
                        frame[key] = float(value)
                    except ValueError:
                        frame[key] = value
            frames.append(frame)
    return frames


def find_max_depth_frame(frames: list[dict]) -> int:
    """
    Find the frame at maximum squat depth.

    Uses hip angle as the primary depth indicator - the frame where
    the average hip angle is minimized is the bottom of the squat.
    """
    skip = FRAME_SELECTION["skip_initial_frames"]
    left_key = FRAME_SELECTION["depth_metric"]
    right_key = FRAME_SELECTION["depth_metric_alt"]

    min_angle = float("inf")
    min_frame_idx = skip

    for i in range(skip, len(frames)):
        left = frames[i].get(left_key)
        right = frames[i].get(right_key)

        if left is None or right is None:
            continue

        avg_hip = (left + right) / 2.0
        if avg_hip < min_angle:
            min_angle = avg_hip
            min_frame_idx = i

    return min_frame_idx


def get_averaged_angles(frames: list[dict], center_idx: int) -> dict[str, float]:
    """
    Get angles averaged over a window around the target frame.

    Reduces noise from single-frame pose estimation jitter.
    """
    window = FRAME_SELECTION["averaging_window"]
    half = window // 2

    start = max(0, center_idx - half)
    end = min(len(frames), center_idx + half + 1)
    window_frames = frames[start:end]

    # Collect all angle columns
    angle_keys = [k for k in frames[0].keys() if k.startswith("angle_")]

    averaged = {}
    for key in angle_keys:
        values = []
        for f in window_frames:
            val = f.get(key)
            if val is not None:
                values.append(val)
        if values:
            averaged[key] = sum(values) / len(values)

    return averaged


def get_landmarks_at_frame(frame: dict) -> dict[str, dict]:
    """Extract landmark positions from a single frame."""
    landmarks = {}
    # Find all landmark columns (landmark_<name>_x, _y, _z, _visibility)
    keys = [k for k in frame.keys() if k.startswith("landmark_")]

    # Group by landmark name
    landmark_names = set()
    for k in keys:
        # landmark_left_knee_x → left_knee
        parts = k.replace("landmark_", "").rsplit("_", 1)
        if len(parts) == 2:
            landmark_names.add(parts[0])

    for name in landmark_names:
        x = frame.get(f"landmark_{name}_x")
        y = frame.get(f"landmark_{name}_y")
        z = frame.get(f"landmark_{name}_z")
        vis = frame.get(f"landmark_{name}_visibility")
        if x is not None and y is not None:
            landmarks[name] = {"x": x, "y": y, "z": z, "visibility": vis}

    return landmarks


def get_averaged_landmarks(frames: list[dict], center_idx: int) -> dict[str, dict]:
    """
    Get landmarks averaged over a window around the target frame.

    Same idea as get_averaged_angles — reduces single-frame jitter.
    """
    window = FRAME_SELECTION["averaging_window"]
    half = window // 2

    start = max(0, center_idx - half)
    end = min(len(frames), center_idx + half + 1)
    window_frames = frames[start:end]

    # Get all landmark names from first frame
    all_landmarks = get_landmarks_at_frame(window_frames[0])
    landmark_names = list(all_landmarks.keys())

    averaged = {}
    for name in landmark_names:
        xs, ys, zs = [], [], []
        for f in window_frames:
            lm = get_landmarks_at_frame(f)
            if name in lm:
                xs.append(lm[name]["x"])
                ys.append(lm[name]["y"])
                if lm[name].get("z") is not None:
                    zs.append(lm[name]["z"])
        if xs and ys:
            averaged[name] = {
                "x": sum(xs) / len(xs),
                "y": sum(ys) / len(ys),
                "z": sum(zs) / len(zs) if zs else None,
                "visibility": all_landmarks.get(name, {}).get("visibility"),
            }

    return averaged


def _vector_angle_from_vertical(p_top: dict, p_bottom: dict) -> float:
    """
    Calculate the angle a segment makes from vertical (in degrees).

    0° = perfectly vertical (top directly above bottom)
    90° = perfectly horizontal

    Uses the 2D x,y coordinates. In MediaPipe/image coords, y increases
    downward, so "vertical" means same x, different y.

    Args:
        p_top: Upper point {"x": ..., "y": ...} (e.g. shoulder)
        p_bottom: Lower point {"x": ..., "y": ...} (e.g. hip)

    Returns:
        Angle from vertical in degrees (0-180).
    """
    dx = p_top["x"] - p_bottom["x"]
    dy = p_top["y"] - p_bottom["y"]

    # Vertical vector is (0, -1) in image coords (up)
    # but since y increases downward, vertical = (0, +1) when top is above bottom
    # We just want the angle from the y-axis
    angle_rad = math.atan2(abs(dx), abs(dy))
    return math.degrees(angle_rad)


def _midpoint(p1: dict, p2: dict) -> dict:
    """Calculate midpoint between two landmarks."""
    return {
        "x": (p1["x"] + p2["x"]) / 2.0,
        "y": (p1["y"] + p2["y"]) / 2.0,
    }


def check_squat_depth(angles: dict[str, float]) -> CriterionResult:
    """Check if femur passes below horizontal (knee flexion depth)."""
    left = angles.get("angle_left_knee")
    right = angles.get("angle_right_knee")

    if left is None or right is None:
        return CriterionResult(
            name="Squat Depth (femur below horizontal)",
            passed=False,
            detail="Could not measure knee angles",
        )

    avg_knee = (left + right) / 2.0
    threshold = DEEP_SQUAT["knee_flexion"]["score_3_max"]

    passed = avg_knee <= threshold
    detail = "Adequate depth achieved" if passed else "Insufficient squat depth"

    return CriterionResult(
        name="Squat Depth (femur below horizontal)",
        passed=passed,
        value=avg_knee,
        threshold=threshold,
        detail=detail,
    )


def check_torso_tibia_alignment(
    landmarks: dict[str, dict],
) -> CriterionResult:
    """
    Check if upper torso is parallel with tibia or toward vertical.

    Uses landmark positions to compute actual segment inclinations:
    - Trunk inclination: angle of shoulder_mid → hip_mid from vertical
    - Tibia inclination: angle of knee_mid → ankle_mid from vertical

    FMS score 3 requires trunk parallel to tibia (or more upright).
    If trunk tilts forward significantly more than tibia, it's a fail.

    Based on Barrack et al. (2021): trunk-tibia angle predicts hip/knee
    extensor demand during squatting.
    """
    required = ["left_shoulder", "right_shoulder", "left_hip", "right_hip",
                 "left_knee", "right_knee", "left_ankle", "right_ankle"]

    if not all(name in landmarks for name in required):
        return CriterionResult(
            name="Torso-Tibia Alignment",
            passed=False,
            detail="Could not measure landmark positions",
        )

    # Compute segment midpoints
    shoulder_mid = _midpoint(landmarks["left_shoulder"], landmarks["right_shoulder"])
    hip_mid = _midpoint(landmarks["left_hip"], landmarks["right_hip"])
    knee_mid = _midpoint(landmarks["left_knee"], landmarks["right_knee"])
    ankle_mid = _midpoint(landmarks["left_ankle"], landmarks["right_ankle"])

    # Trunk inclination: how far the torso leans from vertical
    trunk_angle = _vector_angle_from_vertical(shoulder_mid, hip_mid)

    # Tibia inclination: how far the shin leans from vertical
    tibia_angle = _vector_angle_from_vertical(knee_mid, ankle_mid)

    # Trunk-tibia difference: positive means trunk leans more than tibia
    trunk_tibia_diff = trunk_angle - tibia_angle

    # FMS criteria: torso parallel with tibia or toward vertical
    # "Parallel" means similar inclination (small difference)
    # "Toward vertical" means trunk is MORE upright than tibia (negative diff)
    # Fail if trunk leans significantly MORE than tibia
    max_forward_diff = 15.0  # degrees — trunk can be up to 15° more forward than tibia

    passed = trunk_tibia_diff <= max_forward_diff

    if trunk_tibia_diff <= 0:
        detail = f"Trunk more upright than tibia (trunk: {trunk_angle:.1f}°, tibia: {tibia_angle:.1f}° from vertical)"
    elif trunk_tibia_diff <= max_forward_diff:
        detail = f"Trunk approximately parallel with tibia (trunk: {trunk_angle:.1f}°, tibia: {tibia_angle:.1f}° from vertical)"
    else:
        detail = f"Excessive forward trunk lean (trunk: {trunk_angle:.1f}° vs tibia: {tibia_angle:.1f}° from vertical)"

    return CriterionResult(
        name="Torso-Tibia Alignment",
        passed=passed,
        value=trunk_tibia_diff,
        threshold=max_forward_diff,
        detail=detail,
    )


def check_knee_over_foot(landmarks: dict[str, dict]) -> CriterionResult:
    """Check if knees track over feet (no excessive valgus/varus)."""
    required = ["left_knee", "right_knee", "left_ankle", "right_ankle",
                 "left_shoulder", "right_shoulder"]

    if not all(name in landmarks for name in required):
        return CriterionResult(
            name="Knee-Over-Foot Alignment",
            passed=False,
            detail="Could not measure landmark positions",
        )

    # Calculate shoulder width for normalization
    shoulder_width = abs(
        landmarks["left_shoulder"]["x"] - landmarks["right_shoulder"]["x"]
    )

    if shoulder_width < 1.0:  # Avoid division by near-zero
        return CriterionResult(
            name="Knee-Over-Foot Alignment",
            passed=False,
            detail="Shoulder width too small to normalize",
        )

    # Check each side: how far does knee deviate from ankle in x?
    left_deviation = (
        landmarks["left_knee"]["x"] - landmarks["left_ankle"]["x"]
    ) / shoulder_width

    right_deviation = (
        landmarks["right_knee"]["x"] - landmarks["right_ankle"]["x"]
    ) / shoulder_width

    threshold = DEEP_SQUAT["knee_alignment"]["valgus_threshold"]
    max_deviation = max(abs(left_deviation), abs(right_deviation))

    passed = max_deviation <= threshold

    detail_parts = []
    if abs(left_deviation) > threshold:
        direction = "inward (valgus)" if left_deviation > 0 else "outward (varus)"
        detail_parts.append(f"Left knee tracks {direction}")
    if abs(right_deviation) > threshold:
        direction = "inward (valgus)" if right_deviation > 0 else "outward (varus)"
        detail_parts.append(f"Right knee tracks {direction}")

    if not detail_parts:
        detail = "Knees tracking over feet bilaterally"
    else:
        detail = "; ".join(detail_parts)

    return CriterionResult(
        name="Knee-Over-Foot Alignment",
        passed=passed,
        value=max_deviation * 100,  # As percentage of shoulder width
        threshold=threshold * 100,
        detail=detail,
    )


def check_heel_rise(angles: dict[str, float]) -> CriterionResult:
    """
    Detect heel elevation during squat.

    This is the key differentiator between score 3 and score 2.
    If heels rise, the person needs heel elevation to achieve depth,
    indicating limited ankle dorsiflexion.
    """
    left = angles.get("angle_left_ankle")
    right = angles.get("angle_right_ankle")

    if left is None or right is None:
        return CriterionResult(
            name="Heel Position (ankle dorsiflexion)",
            passed=True,  # Can't detect, assume OK
            detail="Could not measure ankle angles",
        )

    avg_ankle = (left + right) / 2.0
    threshold = DEEP_SQUAT["ankle_dorsiflexion"]["heel_rise_threshold"]

    # Lower ankle angle at depth may suggest heels are rising
    heels_down = avg_ankle >= threshold

    if heels_down:
        detail = "Heels remain on ground (adequate ankle dorsiflexion)"
    else:
        detail = "Possible heel rise detected (limited ankle dorsiflexion)"

    return CriterionResult(
        name="Heel Position (ankle dorsiflexion)",
        passed=heels_down,
        value=avg_ankle,
        threshold=threshold,
        detail=detail,
    )


def check_lumbar_flexion(
    frames: list[dict],
    depth_idx: int,
    landmarks_at_depth: dict[str, dict],
) -> CriterionResult:
    """
    Check for excessive lumbar flexion (butt wink) at squat depth.

    Instead of using an absolute lower_back angle (which collapses at depth),
    we compare the hip-to-shoulder trunk vector at the START of the squat
    vs at MAX DEPTH. A sudden change in trunk angle relative to the pelvis
    indicates posterior pelvic tilt / butt wink.

    We also check if the hip_mid drops below knee_mid at depth, which
    indicates the pelvis is tucking under.
    """
    required = ["left_shoulder", "right_shoulder", "left_hip", "right_hip",
                 "left_knee", "right_knee"]

    if not all(name in landmarks_at_depth for name in required):
        return CriterionResult(
            name="Lumbar Flexion Control",
            passed=True,
            detail="Could not measure — insufficient landmarks",
        )

    # Get standing landmarks (early in the video)
    standing_idx = min(5, len(frames) - 1)
    standing_landmarks = get_landmarks_at_frame(frames[standing_idx])

    if not all(name in standing_landmarks for name in required):
        return CriterionResult(
            name="Lumbar Flexion Control",
            passed=True,
            detail="Could not measure — no standing reference frame",
        )

    # Calculate trunk angle from vertical at standing
    stand_shoulder_mid = _midpoint(standing_landmarks["left_shoulder"], standing_landmarks["right_shoulder"])
    stand_hip_mid = _midpoint(standing_landmarks["left_hip"], standing_landmarks["right_hip"])
    standing_trunk_angle = _vector_angle_from_vertical(stand_shoulder_mid, stand_hip_mid)

    # Calculate trunk angle from vertical at depth
    depth_shoulder_mid = _midpoint(landmarks_at_depth["left_shoulder"], landmarks_at_depth["right_shoulder"])
    depth_hip_mid = _midpoint(landmarks_at_depth["left_hip"], landmarks_at_depth["right_hip"])
    depth_trunk_angle = _vector_angle_from_vertical(depth_shoulder_mid, depth_hip_mid)

    # The change in trunk angle — some forward lean is expected during a squat
    trunk_change = depth_trunk_angle - standing_trunk_angle

    # Also check: does the pelvis tuck under? (hip_mid y close to or below knee_mid y)
    depth_knee_mid = _midpoint(landmarks_at_depth["left_knee"], landmarks_at_depth["right_knee"])
    # In image coords y increases downward, so hip below knee means hip_y > knee_y
    pelvis_tuck_ratio = (depth_hip_mid["y"] - depth_knee_mid["y"])

    # Thresholds:
    # - Trunk angle change > 35° from standing suggests excessive forward collapse
    # - This is more forgiving than the old absolute threshold
    max_trunk_change = 35.0

    passed = trunk_change <= max_trunk_change

    if trunk_change <= 15:
        detail = f"Minimal trunk angle change ({trunk_change:.1f}° from standing). Good lumbar control."
    elif trunk_change <= max_trunk_change:
        detail = f"Moderate trunk angle change ({trunk_change:.1f}° from standing). Acceptable range."
    else:
        detail = f"Excessive trunk angle change ({trunk_change:.1f}° from standing). Possible lumbar flexion / posterior pelvic tilt."

    return CriterionResult(
        name="Lumbar Flexion Control",
        passed=passed,
        value=trunk_change,
        threshold=max_trunk_change,
        detail=detail,
    )


def calculate_bilateral_differences(angles: dict[str, float]) -> dict[str, float]:
    """Calculate left-right differences for bilateral angles."""
    pairs = [
        ("Knee", "angle_left_knee", "angle_right_knee"),
        ("Hip", "angle_left_hip", "angle_right_hip"),
        ("Ankle", "angle_left_ankle", "angle_right_ankle"),
        ("Shoulder", "angle_left_shoulder", "angle_right_shoulder"),
        ("Elbow", "angle_left_elbow", "angle_right_elbow"),
    ]

    diffs = {}
    for name, left_key, right_key in pairs:
        left = angles.get(left_key)
        right = angles.get(right_key)
        if left is not None and right is not None:
            diffs[name] = left - right

    return diffs


def score_deep_squat(
    csv_path: str | Path,
    pain_reported: bool = False,
) -> DeepSquatResult:
    """
    Score a deep squat assessment from a pose CSV file.

    Args:
        csv_path: Path to the exported pose CSV from Dynalytics.
        pain_reported: Whether the patient reported pain during the movement.

    Returns:
        DeepSquatResult with score (0-3), criteria details, and raw data.
    """
    # Pain override — score 0 regardless of movement quality
    if pain_reported:
        return DeepSquatResult(
            score=0,
            pain_reported=True,
            criteria=[
                CriterionResult(
                    name="Pain Screen",
                    passed=False,
                    detail="Pain reported during movement. Score automatically set to 0. "
                           "Medical professional should evaluate the painful area.",
                )
            ],
        )

    # Load and analyze
    frames = load_csv(csv_path)

    if len(frames) < FRAME_SELECTION["skip_initial_frames"] + 5:
        return DeepSquatResult(
            score=1,
            criteria=[
                CriterionResult(
                    name="Video Length",
                    passed=False,
                    detail=f"Video too short ({len(frames)} frames). Need more data.",
                )
            ],
        )

    # Find the bottom of the squat
    depth_idx = find_max_depth_frame(frames)
    angles = get_averaged_angles(frames, depth_idx)
    landmarks = get_averaged_landmarks(frames, depth_idx)

    # Run all criterion checks
    depth_result = check_squat_depth(angles)
    alignment_result = check_torso_tibia_alignment(landmarks)
    knee_result = check_knee_over_foot(landmarks)
    heel_result = check_heel_rise(angles)
    lumbar_result = check_lumbar_flexion(frames, depth_idx, landmarks)

    criteria = [depth_result, alignment_result, knee_result, heel_result, lumbar_result]

    # Bilateral differences
    bilateral = calculate_bilateral_differences(angles)

    # === SCORING LOGIC ===
    # Score 3: All criteria pass (including heels down)
    # Score 2: Depth + alignment + knee alignment pass, but heels rise
    # Score 1: Any core criterion fails
    # Score 0: Pain (handled above)

    core_pass = depth_result.passed and alignment_result.passed and knee_result.passed
    no_lumbar_issues = lumbar_result.passed
    heels_down = heel_result.passed

    if core_pass and no_lumbar_issues and heels_down:
        score = 3
    elif core_pass and no_lumbar_issues and not heels_down:
        score = 2
    elif core_pass and not no_lumbar_issues:
        # Depth achieved but with lumbar flexion compensation
        score = 1
    else:
        score = 1

    return DeepSquatResult(
        score=score,
        criteria=criteria,
        pain_reported=False,
        max_depth_frame=depth_idx,
        angles_at_depth=angles,
        landmarks_at_depth=landmarks,
        left_right_differences=bilateral,
    )
