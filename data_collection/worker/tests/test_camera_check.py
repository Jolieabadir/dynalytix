"""
camera_check.CameraCheck on synthetic footage: a static camera scores near
zero, a pan scores high, a zoom shows in the zoom range, two shots spliced
together are a cut, the climber's own motion is masked out, and a failure in
the check never fails the pose job.
"""
import subprocess

import numpy as np
import pytest

from camera_check import CameraCheck
from conftest import TMP, requires_ffmpeg, requires_mediapipe

W, H = 640, 360


def textured_world(seed=0, w=2400, h=1400):
    """A climbing-wall-ish texture: random 'holds' on a noisy background,
    large enough to pan and zoom across."""
    rng = np.random.default_rng(seed)
    world = rng.integers(60, 120, size=(h, w, 3), dtype=np.uint8)
    for _ in range(900):
        x, y = int(rng.integers(0, w - 30)), int(rng.integers(0, h - 30))
        size = int(rng.integers(8, 28))
        colour = rng.integers(0, 255, size=3, dtype=np.uint8)
        world[y:y + size, x:x + size] = colour
    return world


def view(world, x, y, zoom=1.0):
    """The W x H frame a camera at (x, y) with `zoom` sees of the world."""
    import cv2
    cw, ch = int(W / zoom), int(H / zoom)
    crop = world[y:y + ch, x:x + cw]
    return cv2.resize(crop, (W, H), interpolation=cv2.INTER_LINEAR)


def run(frames, landmarks=None):
    check = CameraCheck(W, H)
    for i, frame in enumerate(frames):
        check.feed(frame, landmarks[i] if landmarks else None)
    return check.summary()


def test_static_camera_scores_near_zero():
    world = textured_world()
    frames = [view(world, 500, 400) for _ in range(30)]
    m = run(frames)
    assert m['has_cut'] is False and m['cut_frames'] == []
    assert m['camera_motion_score'] < 0.0005
    assert m['camera_zoom_range'] < 1.01
    assert m['camera_motion_frames_pct'] == 0.0
    assert m['camera_frames_measured'] == 29


def test_pan_scores_above_the_default_threshold():
    world = textured_world(1)
    # 8 px/frame at 640x360 (diag ~734) = ~1.1% of the diagonal per frame.
    frames = [view(world, 300 + 8 * i, 400) for i in range(30)]
    m = run(frames)
    assert m['has_cut'] is False
    assert m['camera_motion_score'] > 0.002
    # Normalized by the diagonal, so independent of the analysis resolution.
    assert m['camera_motion_score'] == pytest.approx(8 / np.hypot(W, H), rel=0.25)
    assert m['camera_motion_frames_pct'] > 90


def test_slow_drift_is_measured_but_small():
    world = textured_world(2)
    frames = [view(world, 300 + i // 3, 400) for i in range(30)]  # ~0.33 px/frame
    m = run(frames)
    assert m['camera_motion_score'] < 0.002


def test_zoom_shows_in_zoom_range_not_motion():
    world = textured_world(3)
    # Zoom in about the frame centre from 1.0x to ~1.5x.
    frames = []
    for i in range(30):
        zoom = 1.0 + 0.5 * i / 29
        cx, cy = 1200, 700
        cw, ch = int(W / zoom), int(H / zoom)
        frames.append(view(world, cx - cw // 2, cy - ch // 2, zoom))
    m = run(frames)
    assert m['camera_zoom_range'] > 1.3
    assert m['has_cut'] is False


def test_two_shots_spliced_together_are_a_cut():
    a, b = textured_world(4), textured_world(5)
    b = (b * np.array([1.0, 0.4, 0.4])).astype(np.uint8)  # a differently lit shot
    frames = [view(a, 500, 400) for _ in range(15)] + [view(b, 100, 100) for _ in range(15)]
    m = run(frames)
    assert m['has_cut'] is True and m['cut_frames'] == [15]
    # Motion across the cut is not counted: still a static camera otherwise.
    assert m['camera_motion_score'] < 0.0005


def test_climber_motion_is_masked_out():
    """A large moving block (the climber) in front of a static wall: with its
    pose box masked the camera reads as static."""
    world = textured_world(6)
    frames, landmarks = [], []
    for i in range(30):
        frame = view(world, 500, 400).copy()
        x0 = 100 + 10 * i
        frame[80:300, x0:x0 + 120] = np.random.default_rng(i).integers(0, 255, (220, 120, 3), dtype=np.uint8)
        frames.append(frame)
        landmarks.append([
            {'x': x0 / W, 'y': 80 / H}, {'x': (x0 + 120) / W, 'y': 300 / H},
        ])
    masked = run(frames, landmarks)
    assert masked['camera_motion_score'] < 0.001


def test_too_few_features_is_skipped_not_still():
    flat = [np.full((H, W, 3), 90, dtype=np.uint8) for _ in range(10)]
    m = run(flat)
    assert m['camera_frames_measured'] == 0 and m['camera_frames_skipped'] == 9
    assert m['camera_motion_score'] is None and m['camera_motion_frames_pct'] is None
    assert m['camera_zoom_range'] == 1.0


def test_rejects_a_zero_size_frame():
    with pytest.raises(ValueError):
        CameraCheck(0, 100)


# ==================== inside extract.py ====================

def _ffmpeg_clip(name, crop, seconds=1.5, fps=30):
    """An H.264 clip of a still textured wall, viewed through `crop` (an
    ffmpeg crop filter whose x/y may depend on t to pan)."""
    import cv2
    TMP.mkdir(parents=True, exist_ok=True)
    wall = TMP / 'cam_wall.png'
    if not wall.exists():
        cv2.imwrite(str(wall), cv2.cvtColor(textured_world(9, w=1600, h=900), cv2.COLOR_RGB2BGR))
    out = TMP / name
    if not out.exists():
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error', '-loop', '1', '-framerate', str(fps),
            '-i', str(wall), '-t', str(seconds), '-vf', crop,
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(out),
        ], check=True)
    return out


@requires_ffmpeg
@requires_mediapipe
def test_extract_reports_camera_metrics_for_a_static_and_a_panning_clip():
    from extract import extract_pose_csv

    static = _ffmpeg_clip('cam_static.mp4', 'crop=640:360:320:180')
    panning = _ffmpeg_clip('cam_pan.mp4', "crop=640:360:'t*400':180")
    _, meta_static = extract_pose_csv(str(static))
    _, meta_pan = extract_pose_csv(str(panning))
    assert meta_static.camera is not None and meta_pan.camera is not None
    assert meta_static.camera['has_cut'] is False
    assert meta_pan.camera['camera_motion_score'] > meta_static.camera['camera_motion_score']
    assert meta_pan.camera['camera_motion_score'] > 0.002
    assert meta_static.to_dict()['camera']['camera_zoom_range'] < 1.05


@requires_ffmpeg
@requires_mediapipe
def test_a_crash_in_the_check_never_fails_the_pose(monkeypatch):
    from extract import extract_pose_csv

    def boom(self, frame, landmarks=None):
        raise RuntimeError('synthetic failure')

    monkeypatch.setattr(CameraCheck, 'feed', boom)
    static = _ffmpeg_clip('cam_static.mp4', 'crop=640:360:320:180')
    csv_text, meta = extract_pose_csv(str(static))
    assert csv_text.startswith('frame_number,') and meta.total_frames > 0
    assert meta.camera is None
