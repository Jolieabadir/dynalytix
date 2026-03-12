"""
Angle thresholds for FMS scoring.

Based on research data:
- Butler et al. (2010): Biomechanical analysis of FMS deep squat classifications
  Group 1 (score 1): knee flexion ~84.7°, hip flexion ~88.1°, dorsiflexion ~24.5°
  Group 2 (score 2): knee flexion ~110.0°, hip flexion ~117.5°, dorsiflexion ~27.9°
  Group 3 (score 3): greater than group 2 in all measures

- Heredia et al. (2021): Score 3 had significantly greater peak hip flexion,
  knee flexion, and ankle dorsiflexion vs scores 1 and 2.

- FMS Official Criteria (Cook et al.):
  Score 3: torso parallel to tibia, femur below horizontal, knees over feet
  Score 2: same as 3 but heels elevated
  Score 1: criteria not met
  Score 0: pain during movement (user-reported)

NOTE: These thresholds use the angle conventions from Dynalytix' MediaPipe pipeline.
Your angles are calculated as the interior angle at the joint vertex:
  - knee angle: hip → knee → ankle (straight leg ≈ 180°, deep bend < 90°)
  - hip angle: shoulder → hip → knee (standing ≈ 180°, deep squat < 90°)
  - ankle angle: knee → ankle → heel

These will need calibration against real video. Start here, then tune.
"""

# =============================================================================
# DEEP SQUAT THRESHOLDS
# =============================================================================

DEEP_SQUAT = {
    # Knee flexion angle (interior angle at knee joint)
    # In Dynalytix convention: straight leg ≈ 170-180°, deep bend ≈ 60-90°
    # "Femur below horizontal" roughly corresponds to knee angle < 100°
    "knee_flexion": {
        "score_3_max": 100.0,   # Must be below this (deep squat achieved)
        "score_2_max": 100.0,   # Same depth requirement as 3 (but heels elevated)
        "score_1_above": 100.0, # Above this = insufficient depth
    },

    # Hip flexion angle (interior angle at hip joint)
    # Standing ≈ 170-180°, deep squat ≈ 70-95°
    "hip_flexion": {
        "score_3_max": 95.0,    # Must be below this for adequate depth
        "score_1_above": 120.0, # Above this = clearly insufficient
    },

    # Ankle angle (knee → ankle → heel)
    # This helps detect heel rise - a key differentiator between score 2 and 3
    # When heels lift, this angle changes significantly
    "ankle_dorsiflexion": {
        "heel_rise_threshold": 140.0,  # Below this suggests heels are lifting
    },

    # Torso-tibia parallelism
    # Measured via lower_back angle (shoulder_mid → hip_mid → knee_mid)
    # When torso and tibia are parallel, this angle is moderate
    # When torso collapses forward, this drops significantly
    "lower_back": {
        "parallel_min": 100.0,  # Below this = excessive forward lean
        "parallel_max": 170.0,  # Above this = too upright (not squatting)
    },

    # Knee-over-foot alignment (frontal plane)
    # Measured as horizontal distance between knee and ankle x-coordinates
    # Normalized by shoulder width for body-size independence
    "knee_alignment": {
        "valgus_threshold": 0.15,  # Knee x deviates inward > 15% of shoulder width
    },
}


# =============================================================================
# FRAME SELECTION
# =============================================================================

# When analyzing a squat video, we need to find the "bottom" of the squat
# (max depth frame) to evaluate. These settings control that detection.
FRAME_SELECTION = {
    # Minimum frames into the video before looking for squat bottom
    # (skip the initial standing position)
    "skip_initial_frames": 10,

    # The squat bottom is the frame where hip angle is minimized
    # We use hip angle because it's the most reliable depth indicator
    "depth_metric": "angle_left_hip",  # or average of left + right
    "depth_metric_alt": "angle_right_hip",

    # Number of frames around the bottom to average (reduces noise)
    "averaging_window": 5,
}
