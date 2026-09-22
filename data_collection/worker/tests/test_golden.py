"""
The CSV contract, byte for byte.

Port of the frontend's golden-file test (scripts/test_pose_math.mjs,
scripts/golden_frames.mjs, scripts/fixtures/golden_pose.csv). The frontend
feeds a seeded set of synthetic landmarks through computeResult + framesToCSV
and pins the bytes; golden_frames.py rebuilds the same landmarks and the
worker's angles.py must produce the identical file.

What this proves: the landmark column order (15 legacy first, 18 appended),
the 12 angle definitions and their evaluation order, 4-dp / 3-dp rounding,
JS number formatting, null/empty handling, and centre-of-mass speed - i.e.
everything downstream of the model. What it cannot prove: that the Python
MediaPipe runtime returns the same landmarks as the WASM one for a real frame
(it does not, to the bit; see README.md).
"""
import json
import math
import random
import re
import shutil
import subprocess

import pytest

from conftest import GOLDEN_CSV, POSE_MATH_JS, requires_node
import angles
import fdlibm
from golden_frames import golden_frames, FPS, FRAME_COUNT

# ==================== THE GOLDEN FILE ====================

def test_golden_csv_matches_byte_for_byte():
    expected = GOLDEN_CSV.read_bytes()
    actual = angles.frames_to_csv(golden_frames()).encode('utf-8')
    if actual != expected:
        # Point at the first differing cell rather than dumping 47 KB.
        for line_no, (a, e) in enumerate(zip(actual.split(b'\n'), expected.split(b'\n'))):
            if a != e:
                a_cells, e_cells = a.split(b','), e.split(b',')
                col = next(i for i, (x, y) in enumerate(zip(a_cells, e_cells)) if x != y)
                header = angles.csv_headers()[col]
                pytest.fail(f'line {line_no}, column {col} ({header}): got {a_cells[col]!r}, want {e_cells[col]!r}')
        pytest.fail(f'length differs: {len(actual)} vs {len(expected)}')


def test_golden_shape():
    frames = golden_frames()
    assert len(frames) == FRAME_COUNT
    csv_text = angles.frames_to_csv(frames)
    lines = csv_text.split('\n')
    assert len(lines) == FRAME_COUNT + 1
    assert not csv_text.endswith('\n')
    assert len(lines[0].split(',')) == 147
    for line in lines[1:]:
        assert len(line.split(',')) == 147
    # A pose-less frame is frame_number, timestamp, 0 speed, then 144 empties.
    empty = lines[4].split(',')
    assert empty[:3] == ['3', angles.js_number(angles.timestamp_for_frame(3, FPS)), '0']
    assert all(cell == '' for cell in empty[3:])


# ==================== CONTRACT CONSTANTS vs poseMath.js ====================

def _js_source() -> str:
    return POSE_MATH_JS.read_text()


def _js_string_list(block: str) -> list:
    return re.findall(r"'([a-z_]+)'", block)


def test_landmark_map_matches_pose_math_js():
    src = _js_source()
    block = re.search(r'export const LANDMARK_MAP = \{(.*?)\};', src, re.S).group(1)
    js_map = {int(k): v for k, v in re.findall(r"(\d+): '([a-z_]+)'", block)}
    assert js_map == angles.LANDMARK_MAP


def test_legacy_order_matches_pose_math_js():
    src = _js_source()
    block = re.search(r'export const LEGACY_LANDMARK_ORDER = \[(.*?)\];', src, re.S).group(1)
    assert _js_string_list(block) == angles.LEGACY_LANDMARK_ORDER


def test_angle_definitions_match_pose_math_js():
    src = _js_source()
    block = re.search(r'export const ANGLE_DEFINITIONS = \[(.*?)\];', src, re.S).group(1)
    rows = [tuple(_js_string_list(row)) for row in re.findall(r'\[(.*?)\]', block)]
    assert rows == [tuple(d) for d in angles.ANGLE_DEFINITIONS]
    assert len(angles.ANGLE_NAMES) == 12
    assert angles.ANGLE_NAMES[-2:] == ['upper_back', 'lower_back']


def test_rounding_constants_match_pose_math_js():
    src = _js_source()
    assert int(re.search(r'export const COORD_DECIMALS = (\d+);', src).group(1)) == angles.COORD_DECIMALS
    assert int(re.search(r'export const VISIBILITY_DECIMALS = (\d+);', src).group(1)) == angles.VISIBILITY_DECIMALS


def test_header_order_is_legacy_15_then_18_appended():
    headers = angles.csv_headers()
    assert headers[:3] == ['frame_number', 'timestamp_ms', 'speed_center_of_mass']
    assert headers[3:15] == [f'angle_{n}' for n in angles.ANGLE_NAMES]
    assert headers[15:19] == ['landmark_nose_x', 'landmark_nose_y', 'landmark_nose_z', 'landmark_nose_visibility']
    assert headers[19] == 'landmark_left_shoulder_x'
    # 15 legacy * 4 = 60 columns after the 15 scalar ones -> the 16th landmark
    # starts at column 75 and is the first appended one (left_eye_inner).
    assert headers[75] == 'landmark_left_eye_inner_x'
    assert headers[-1] == 'landmark_right_foot_index_visibility'
    assert headers == GOLDEN_CSV.read_text().split('\n')[0].split(',')


# ==================== NUMBER FORMATTING ====================

@pytest.mark.parametrize('value, text', [
    (0.0, '0'), (-0.0, '0'), (1.0, '1'), (5.0, '5'), (1234.5678, '1234.5678'),
    (0.1, '0.1'), (0.5, '0.5'), (100.0, '100'), (1e21, '1e+21'), (1e-7, '1e-7'),
    (0.000001, '0.000001'), (1.5e-7, '1.5e-7'), (123456789012345680000.0, '123456789012345680000'),
    (33.333333333333336, '33.333333333333336'), (66.66666666666667, '66.66666666666667'),
    (-12.25, '-12.25'), (3, '3'), (True, 'true'), (float('nan'), 'NaN'), (float('inf'), 'Infinity'),
])
def test_js_number(value, text):
    assert angles.js_number(value) == text


@pytest.mark.parametrize('value, expected', [
    (0.5, 1), (1.5, 2), (2.5, 3), (-0.5, 0), (-1.5, -1), (0.49999999999999994, 0), (2.4999, 2),
])
def test_js_round_ties_toward_positive_infinity(value, expected):
    assert angles.js_round(value) == expected


def test_round_for_csv():
    assert angles.round_for_csv(552.93921, 4) == 552.9392
    assert angles.round_for_csv(0.12345, 3) == 0.123
    assert angles.round_for_csv(-0.00001, 4) == 0.0 and not math.copysign(1, angles.round_for_csv(-0.00001, 4)) < 0
    assert angles.round_for_csv(None, 4) is None
    assert angles.js_number(angles.round_for_csv(1.0000001, 4)) == '1'


@requires_node
def test_js_number_matches_node_for_random_values():
    """Python repr digits + JS layout must equal Number#toString exactly."""
    rng = random.Random(20260922)
    values = [rng.uniform(-2000, 2000) for _ in range(2000)]
    values += [rng.uniform(0, 1) for _ in range(2000)]
    values += [angles.round_for_csv(v, 4) for v in values[:1000]]
    values += [angles.round_for_csv(v, 3) for v in values[2000:3000]]
    script = 'const v=JSON.parse(require("fs").readFileSync(0,"utf8"));console.log(JSON.stringify(v.map(x=>String(x))))'
    out = subprocess.run(['node', '-e', script], input=json.dumps(values), capture_output=True, text=True, check=True)
    expected = json.loads(out.stdout)
    assert [angles.js_number(v) for v in values] == expected


# ==================== GEOMETRY ====================

def test_angle_between_degenerate_returns_none():
    p = {'x': 1.0, 'y': 1.0}
    assert angles.angle_between(p, p, {'x': 2.0, 'y': 2.0}) is None


def test_angle_between_right_angle():
    assert angles.angle_between({'x': 1, 'y': 0}, {'x': 0, 'y': 0}, {'x': 0, 'y': 1}) == pytest.approx(90.0)


@requires_node
def test_fdlibm_acos_is_bit_identical_to_v8_math_acos():
    """The angle columns are written unrounded, so acos must match V8 to the bit."""
    rng = random.Random(1)
    xs = [rng.uniform(-1, 1) for _ in range(20000)] + [-1.0, 1.0, 0.0, 0.5, -0.5, 0.25, -0.75, 1e-20, -1e-20]
    script = 'const v=JSON.parse(require("fs").readFileSync(0,"utf8"));console.log(JSON.stringify(v.map(x=>String(Math.acos(x)))))'
    out = subprocess.run(['node', '-e', script], input=json.dumps(xs), capture_output=True, text=True, check=True)
    expected = json.loads(out.stdout)
    actual = [angles.js_number(fdlibm.acos(x)) for x in xs]
    mismatches = [(x, a, e) for x, a, e in zip(xs, actual, expected) if a != e]
    assert not mismatches, mismatches[:5]


@requires_node
def test_math_acos_would_not_match_v8():
    """Documents why fdlibm.py exists: glibc acos differs from V8 in the last bit."""
    rng = random.Random(2)
    xs = [rng.uniform(-1, 1) for _ in range(20000)]
    script = 'const v=JSON.parse(require("fs").readFileSync(0,"utf8"));console.log(JSON.stringify(v.map(x=>String(Math.acos(x)))))'
    out = subprocess.run(['node', '-e', script], input=json.dumps(xs), capture_output=True, text=True, check=True)
    expected = json.loads(out.stdout)
    glibc = [angles.js_number(math.acos(x)) for x in xs]
    differing = sum(1 for a, e in zip(glibc, expected) if a != e)
    # If this ever becomes 0, fdlibm.py can be retired - but not before.
    assert differing > 0


def test_compute_result_denormalizes_against_source_size():
    raw = [{'x': 0.5, 'y': 0.25, 'z': 0.1, 'visibility': 0.9}] * angles.LANDMARK_COUNT
    result = angles.compute_result(raw, 1080, 1920, 0)
    assert result['landmarks']['nose'] == {'x': 540.0, 'y': 480.0, 'z': 0.1, 'visibility': 0.9}
    # Every landmark identical -> every angle degenerate -> None, speed 0 on frame one.
    assert all(v is None for v in result['angles'].values())
    assert result['com_speed'] == 0
    assert angles.compute_result(None, 1, 1, 0) is None
