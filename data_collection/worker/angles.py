"""
Pose geometry and the CSV contract, ported from the frontend's poseMath.js.

This is the single source of truth for what the worker writes. Every constant
and formula here mirrors `data_collection/frontend/src/services/poseMath.js`
(the LANDMARK_MAP, LEGACY_LANDMARK_ORDER, ANGLE_DEFINITIONS, `angleBetween`,
`computeResult`, `framesToCSV`, and the output rounding), and the golden test
in tests/test_golden.py asserts that the two agree byte for byte.

No MediaPipe, ffmpeg, Modal or numpy import: this module is pure Python so it
can be tested anywhere.

Number formatting deserves a note. The frontend stringifies numbers with JS's
Number::toString (shortest round-trip digits, no exponent between 1e-7 and
1e21, integers without a trailing ".0"). Python's repr() has the same shortest
round-trip digits but different exponent thresholds and prints "5.0" for an
integral float, so `js_number` below re-formats repr()'s digits the way JS
would. Angles and speeds are written unrounded, exactly as the frontend does.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence

from fdlibm import acos as _js_acos

# ==================== LANDMARKS ====================

#: All 33 MediaPipe Pose landmarks, index -> canonical name.
LANDMARK_MAP: Dict[int, str] = {
    0: 'nose',
    1: 'left_eye_inner',
    2: 'left_eye',
    3: 'left_eye_outer',
    4: 'right_eye_inner',
    5: 'right_eye',
    6: 'right_eye_outer',
    7: 'left_ear',
    8: 'right_ear',
    9: 'mouth_left',
    10: 'mouth_right',
    11: 'left_shoulder',
    12: 'right_shoulder',
    13: 'left_elbow',
    14: 'right_elbow',
    15: 'left_wrist',
    16: 'right_wrist',
    17: 'left_pinky',
    18: 'right_pinky',
    19: 'left_index',
    20: 'right_index',
    21: 'left_thumb',
    22: 'right_thumb',
    23: 'left_hip',
    24: 'right_hip',
    25: 'left_knee',
    26: 'right_knee',
    27: 'left_ankle',
    28: 'right_ankle',
    29: 'left_heel',
    30: 'right_heel',
    31: 'left_foot_index',
    32: 'right_foot_index',
}

LANDMARK_COUNT = len(LANDMARK_MAP)

#: The 15 landmarks emitted before the widening, in their original column order.
LEGACY_LANDMARK_ORDER: List[str] = [
    'nose',
    'left_shoulder',
    'right_shoulder',
    'left_elbow',
    'right_elbow',
    'left_wrist',
    'right_wrist',
    'left_hip',
    'right_hip',
    'left_knee',
    'right_knee',
    'left_ankle',
    'right_ankle',
    'left_heel',
    'right_heel',
]

#: CSV landmark column order: the original 15 first, then the 18 added ones in
#: MediaPipe index order. Deliberately not canonical index order, so the first
#: 75 columns stay where a positional reader of the old format expects them.
CSV_LANDMARK_ORDER: List[str] = LEGACY_LANDMARK_ORDER + [
    name for name in LANDMARK_MAP.values() if name not in LEGACY_LANDMARK_ORDER
]

#: Angle definitions: (name, pointA, pointB (vertex), pointC).
ANGLE_DEFINITIONS = [
    ('left_elbow', 'left_shoulder', 'left_elbow', 'left_wrist'),
    ('right_elbow', 'right_shoulder', 'right_elbow', 'right_wrist'),
    ('left_shoulder', 'left_hip', 'left_shoulder', 'left_elbow'),
    ('right_shoulder', 'right_hip', 'right_shoulder', 'right_elbow'),
    ('left_hip', 'left_shoulder', 'left_hip', 'left_knee'),
    ('right_hip', 'right_shoulder', 'right_hip', 'right_knee'),
    ('left_knee', 'left_hip', 'left_knee', 'left_ankle'),
    ('right_knee', 'right_hip', 'right_knee', 'right_ankle'),
    ('left_ankle', 'left_knee', 'left_ankle', 'left_heel'),
    ('right_ankle', 'right_knee', 'right_ankle', 'right_heel'),
]

#: The 12 angle column names, in order: the 10 above then the two back angles.
ANGLE_NAMES: List[str] = [name for name, *_ in ANGLE_DEFINITIONS] + ['upper_back', 'lower_back']

#: Decimal places kept for landmark coordinates / visibility in the CSV.
COORD_DECIMALS = 4
VISIBILITY_DECIMALS = 3


# ==================== GEOMETRY ====================

def angle_between(a: dict, b: dict, c: dict) -> Optional[float]:
    """Angle at vertex b, in degrees, from the 2-D (x, y) positions.

    Same formula and evaluation order as the frontend: dot / (|ab| |cb|),
    clamped to [-1, 1], acos, then times 180 / pi.
    """
    ab_x, ab_y = a['x'] - b['x'], a['y'] - b['y']
    cb_x, cb_y = c['x'] - b['x'], c['y'] - b['y']
    dot = ab_x * cb_x + ab_y * cb_y
    mag_ab = math.sqrt(ab_x ** 2 + ab_y ** 2)
    mag_cb = math.sqrt(cb_x ** 2 + cb_y ** 2)
    if mag_ab == 0 or mag_cb == 0:
        return None
    cos_angle = max(-1.0, min(1.0, dot / (mag_ab * mag_cb)))
    # fdlibm acos, not math.acos: see fdlibm.py for why the two differ.
    return _js_acos(cos_angle) * (180 / math.pi)


def midpoint(a: dict, b: dict) -> dict:
    return {
        'x': (a['x'] + b['x']) / 2,
        'y': (a['y'] + b['y']) / 2,
        'z': (a['z'] + b['z']) / 2,
    }


def distance(a: dict, b: dict) -> float:
    return math.sqrt((a['x'] - b['x']) ** 2 + (a['y'] - b['y']) ** 2)


def _upper_back(landmarks: dict) -> Optional[float]:
    ls, rs = landmarks.get('left_shoulder'), landmarks.get('right_shoulder')
    if not ls or not rs:
        return None
    return angle_between(ls, midpoint(ls, rs), rs)


def _lower_back(landmarks: dict) -> Optional[float]:
    names = ('left_shoulder', 'right_shoulder', 'left_hip', 'right_hip', 'left_knee', 'right_knee')
    pts = [landmarks.get(n) for n in names]
    if not all(pts):
        return None
    ls, rs, lh, rh, lk, rk = pts
    return angle_between(midpoint(ls, rs), midpoint(lh, rh), midpoint(lk, rk))


# ==================== FRAME RESULT ====================

def compute_result(
    raw_landmarks: Optional[Sequence[Optional[dict]]],
    video_width: int,
    video_height: int,
    timestamp_ms: float,
    prev_com: Optional[dict] = None,
    prev_timestamp_ms: Optional[float] = None,
) -> Optional[dict]:
    """Turn one frame's raw (normalized) MediaPipe landmarks into the row payload.

    `raw_landmarks` is indexable by MediaPipe index; an entry may be None for a
    landmark the model did not return. Each entry is a dict with x, y, z and an
    optional visibility, all normalized. x/y are denormalized against the
    ORIGINAL video dimensions here, so the CSV stores pixels at source
    resolution (the contract SkeletonOverlay and holdMatching rely on).

    Returns None for a pose-less frame, otherwise
    {landmarks, angles, com_speed, com}.
    """
    if raw_landmarks is None:
        return None

    landmarks: dict = {}
    for index, name in LANDMARK_MAP.items():
        lm = raw_landmarks[index] if index < len(raw_landmarks) else None
        if lm:
            landmarks[name] = {
                'x': lm['x'] * video_width,
                'y': lm['y'] * video_height,
                'z': lm['z'],
                'visibility': lm.get('visibility') or 0,
            }

    angles: dict = {}
    for angle_name, pt_a, pt_b, pt_c in ANGLE_DEFINITIONS:
        if pt_a in landmarks and pt_b in landmarks and pt_c in landmarks:
            angles[angle_name] = angle_between(landmarks[pt_a], landmarks[pt_b], landmarks[pt_c])
        else:
            angles[angle_name] = None
    angles['upper_back'] = _upper_back(landmarks)
    angles['lower_back'] = _lower_back(landmarks)

    com_speed: float = 0
    com = None
    if 'left_hip' in landmarks and 'right_hip' in landmarks:
        com = midpoint(landmarks['left_hip'], landmarks['right_hip'])
        if prev_com and prev_timestamp_ms is not None:
            dt = (timestamp_ms - prev_timestamp_ms) / 1000
            if dt > 0:
                com_speed = distance(com, prev_com) / dt

    return {'landmarks': landmarks, 'angles': angles, 'com_speed': com_speed, 'com': com}


# ==================== NUMBER FORMATTING ====================

def js_round(value: float) -> float:
    """ECMAScript Math.round: nearest integer, ties toward +infinity.

    Not `round()` (banker's rounding) and not `floor(x + 0.5)` (which is wrong
    for 0.49999999999999994, where the addition itself rounds up).
    """
    floor = math.floor(value)
    return float(floor + 1) if value - floor >= 0.5 else float(floor)


def round_for_csv(value, decimals: int):
    """The frontend's `round()`: Math.round(v * 10**d) / 10**d + 0.

    Applied in the writer only. `+ 0` collapses -0 to 0 so it stringifies as
    "0"; here that is a plain equality check for negative zero.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return value
    if not math.isfinite(value):
        return value
    factor = 10 ** decimals
    rounded = js_round(value * factor) / factor
    return 0.0 if rounded == 0 else rounded


def js_number(value) -> str:
    """Format a number exactly as JavaScript's Number::toString would.

    Digits come from Python's repr (shortest round-trip, identical to V8's);
    only the layout differs. JS writes plain decimal for 1e-7 <= |x| < 1e21 and
    never prints an integral value with a fraction part.
    """
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if value != value:
        return 'NaN'
    if value in (math.inf, -math.inf):
        return 'Infinity' if value > 0 else '-Infinity'
    if value == 0:
        return '0'

    sign = '-' if value < 0 else ''
    text = repr(abs(value))

    # Split repr into a digit string and a decimal exponent: value = 0.DIGITS x 10**n
    if 'e' in text:
        mantissa, exp = text.split('e')
        exp = int(exp)
    else:
        mantissa, exp = text, 0
    if '.' in mantissa:
        int_part, frac_part = mantissa.split('.')
    else:
        int_part, frac_part = mantissa, ''
    all_digits = int_part + frac_part
    digits = all_digits.lstrip('0')
    # n = position of the decimal point counted from the first significant
    # digit, so value = 0.<digits> x 10**n. Zeros stripped from the front (e.g.
    # "0.00015" -> "15") move the point left by that many places.
    n = len(int_part) + exp - (len(all_digits) - len(digits))
    digits = digits.rstrip('0') or '0'
    k = len(digits)

    # ECMA-262 Number::toString, steps 6-10.
    if k <= n <= 21:
        return sign + digits + '0' * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + '.' + digits[n:]
    if -6 < n <= 0:
        return sign + '0.' + '0' * (-n) + digits
    e = n - 1
    exp_text = ('+' if e >= 0 else '-') + str(abs(e))
    if k == 1:
        return sign + digits + 'e' + exp_text
    return sign + digits[0] + '.' + digits[1:] + 'e' + exp_text


# ==================== CSV SHAPING ====================

def csv_headers() -> List[str]:
    """The 147-column header. Order is a fixed contract."""
    headers = ['frame_number', 'timestamp_ms', 'speed_center_of_mass']
    headers += [f'angle_{name}' for name in ANGLE_NAMES]
    for name in CSV_LANDMARK_ORDER:
        headers += [
            f'landmark_{name}_x',
            f'landmark_{name}_y',
            f'landmark_{name}_z',
            f'landmark_{name}_visibility',
        ]
    return headers


def _cell(value) -> str:
    if value is None or value == '':
        return ''
    if isinstance(value, str):
        return value
    return js_number(value)


def frame_row(frame_num: int, timestamp_ms: float, result: Optional[dict]) -> List[str]:
    """One CSV row (already stringified) for a frame."""
    row = [
        _cell(frame_num),
        _cell(timestamp_ms),
        _cell(result['com_speed'] if result else 0),
    ]
    angles = result['angles'] if result else {}
    for name in ANGLE_NAMES:
        row.append(_cell(angles.get(name)))

    landmarks = result['landmarks'] if result else {}
    for name in CSV_LANDMARK_ORDER:
        lm = landmarks.get(name)
        if lm:
            row += [
                _cell(round_for_csv(lm['x'], COORD_DECIMALS)),
                _cell(round_for_csv(lm['y'], COORD_DECIMALS)),
                _cell(round_for_csv(lm['z'], COORD_DECIMALS)),
                _cell(round_for_csv(lm['visibility'], VISIBILITY_DECIMALS)),
            ]
        else:
            row += ['', '', '', '']
    return row


def frames_to_csv(frames: Iterable[dict]) -> str:
    """Build the CSV string.

    `frames` yields dicts {frame_num, timestamp_ms, result}. Rows are joined
    with "\\n", no trailing newline, no quoting: exactly the frontend's
    framesToCSV.
    """
    lines = [','.join(csv_headers())]
    for frame in frames:
        lines.append(','.join(frame_row(frame['frame_num'], frame['timestamp_ms'], frame['result'])))
    return '\n'.join(lines)


def timestamp_for_frame(frame_num: int, fps: float) -> float:
    """timestamp_ms for a frame index: (frame / fps) * 1000, in that order."""
    return (frame_num / fps) * 1000
