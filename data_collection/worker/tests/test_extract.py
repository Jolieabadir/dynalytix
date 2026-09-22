"""
End-to-end extraction on real files, CPU, vendored FULL model.

Synthetic clips (ffmpeg testsrc2) contain no person, so these check the
container/frame math and the CSV shape: header, row count, contiguous frame
numbers, timestamp_ms = frame / fps * 1000, rotation handling. The iPhone
sample under backend/videos/ (when present) adds a real person: every frame
gets a pose, coordinates land inside the rotated frame, and the row count
equals what the browser extractor produced for the same clip.
"""
import csv
import io
import re

import pytest

from conftest import (
    GOLDEN_CSV, IPHONE_CLIP, IPHONE_OLD_CSV, requires_ffmpeg, requires_mediapipe,
)
import extract
from angles import csv_headers, js_number, timestamp_for_frame

pytestmark = [requires_ffmpeg]

GOLDEN_HEADER = GOLDEN_CSV.read_text().split('\n')[0]


def _rows(csv_text: str):
    return list(csv.DictReader(io.StringIO(csv_text)))


def _assert_contract_shape(csv_text: str, fps: float, expected_rows: int, tolerance: int = 1):
    lines = csv_text.split('\n')
    assert lines[0] == GOLDEN_HEADER, 'header must be the frontend contract, byte for byte'
    assert not csv_text.endswith('\n')
    rows = _rows(csv_text)
    assert abs(len(rows) - expected_rows) <= tolerance, (len(rows), expected_rows)
    for i, row in enumerate(rows):
        assert row['frame_number'] == str(i), 'row N must be frame N (SkeletonOverlay indexes by position)'
        assert row['timestamp_ms'] == js_number(timestamp_for_frame(i, fps))
        assert len(row) == 147
    return rows


# ==================== ffprobe ====================

def test_probe_synthetic_30fps(clip_30fps_1s):
    probe = extract.probe_video(str(clip_30fps_1s))
    assert probe.fps == 30.0
    assert (probe.width, probe.height) == (320, 240)
    assert probe.rotation == 0
    assert probe.duration_ms == pytest.approx(1000, abs=50)
    assert probe.codec == 'h264'


def test_probe_rotated_clip_swaps_dimensions(clip_rotated):
    probe = extract.probe_video(str(clip_rotated))
    assert abs(probe.rotation) == 90
    assert (probe.coded_width, probe.coded_height) == (320, 240)
    assert (probe.width, probe.height) == (240, 320)


def test_probe_rejects_a_non_video(tmp_path):
    bogus = tmp_path / 'not_a_video.mov'
    bogus.write_bytes(b'hello')
    with pytest.raises(extract.PipelineError):
        extract.probe_video(str(bogus))


@pytest.mark.parametrize('measured, expected', [
    (30, 30.0), (30000 / 1001, 30.0), (60000 / 1001, 60.0), (24000 / 1001, 24.0),
    (25, 25.0), (15, 15.0), (27.324, 27.324), (119.88, 120.0),
])
def test_snap_fps(measured, expected):
    assert extract.snap_fps(measured) == expected


def test_snap_fps_rejects_zero():
    with pytest.raises(extract.PipelineError):
        extract.snap_fps(0)


# ==================== ffmpeg frames ====================

def test_iter_frames_yields_every_frame_with_pts(clip_30fps_1s):
    probe = extract.probe_video(str(clip_30fps_1s))
    frames = list(extract.iter_frames(str(clip_30fps_1s), probe))
    assert len(frames) == 30
    pts = [p for p, _ in frames]
    assert pts == sorted(pts)
    assert pts[0] == pytest.approx(0.0, abs=1e-6)
    assert pts[1] == pytest.approx(1 / 30, abs=1e-3)
    assert frames[0][1].shape == (240, 320, 3)
    assert [extract.frame_index_for(p, 30) for p in pts] == list(range(30))


def test_iter_frames_rotated_clip_is_portrait(clip_rotated):
    probe = extract.probe_video(str(clip_rotated))
    _, frame = next(iter(extract.iter_frames(str(clip_rotated), probe)))
    assert frame.shape == (320, 240, 3)


def test_build_rows_fills_holes_and_keeps_first_writer():
    rows = extract.build_rows({0: 'a', 2: 'c'}, 30)
    assert [r['frame_num'] for r in rows] == [0, 1, 2]
    assert [r['result'] for r in rows] == ['a', None, 'c']
    assert rows[2]['timestamp_ms'] == timestamp_for_frame(2, 30)
    assert extract.build_rows({}, 30) == []


# ==================== the whole pipeline ====================

@requires_mediapipe
def test_extract_synthetic_30fps(clip_30fps_1s):
    csv_text, meta = extract.extract_pose_csv(str(clip_30fps_1s))
    rows = _assert_contract_shape(csv_text, 30, 30)
    assert meta.fps == 30.0
    assert meta.total_frames == len(rows)
    assert (meta.width, meta.height) == (320, 240)
    assert meta.frames_decoded == 30
    # A test pattern has no person; every row is pose-less but well-formed.
    assert all(r['speed_center_of_mass'] == '0' for r in rows)


@requires_mediapipe
def test_extract_synthetic_60fps_processes_every_frame(clip_60fps_1s):
    csv_text, meta = extract.extract_pose_csv(str(clip_60fps_1s))
    rows = _assert_contract_shape(csv_text, 60, 60)
    assert meta.fps == 60.0
    assert len(rows) == 60
    assert rows[1]['timestamp_ms'] == '16.666666666666668'


@requires_mediapipe
def test_extract_rotated_clip_reports_display_size(clip_rotated):
    _, meta = extract.extract_pose_csv(str(clip_rotated))
    assert (meta.width, meta.height) == (240, 320)


@requires_mediapipe
@pytest.mark.skipif(not IPHONE_CLIP.exists(), reason='iPhone sample clip not checked out')
def test_extract_real_iphone_clip():
    """HEVC, 1920x1080 stored with rotation -90, 30fps nominal, edit list."""
    csv_text, meta = extract.extract_pose_csv(str(IPHONE_CLIP))
    assert meta.fps == 30.0
    assert (meta.width, meta.height) == (1080, 1920), 'rotation must be applied'
    rows = _assert_contract_shape(csv_text, 30, meta.total_frames, tolerance=0)

    # The browser extractor produced 130 rows for this clip (backend/data/...csv).
    if IPHONE_OLD_CSV.exists():
        old_rows = list(csv.DictReader(IPHONE_OLD_CSV.open()))
        assert len(rows) == len(old_rows)

    with_pose = [r for r in rows if r['landmark_nose_x']]
    assert len(with_pose) >= 0.95 * len(rows), 'a person is in frame throughout'

    coord = re.compile(r'^-?\d+(\.\d{1,4})?$')
    vis = re.compile(r'^-?\d+(\.\d{1,3})?$')
    for row in with_pose:
        x, y = float(row['landmark_nose_x']), float(row['landmark_nose_y'])
        assert 0 <= x <= meta.width and 0 <= y <= meta.height, 'pixels at source resolution'
        for name in ('nose', 'left_hip', 'right_foot_index'):
            assert coord.match(row[f'landmark_{name}_x']), row[f'landmark_{name}_x']
            assert coord.match(row[f'landmark_{name}_z'])
            assert vis.match(row[f'landmark_{name}_visibility'])
        # Angles are written unrounded, like the frontend.
        assert 0 <= float(row['angle_left_elbow']) <= 180
        assert 0 <= float(row['angle_lower_back']) <= 180
    # Centre-of-mass speed is 0 on the first posed frame and positive after.
    assert with_pose[0]['speed_center_of_mass'] == '0'
    assert any(float(r['speed_center_of_mass']) > 0 for r in with_pose[1:])
