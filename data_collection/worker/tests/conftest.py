"""
Shared fixtures for the worker tests.

Everything runs on CPU with the vendored FULL model. Synthetic clips are made
with ffmpeg on demand (a second or two each) under tests/tmp/, which is
gitignored. The real iPhone sample under backend/videos/ is used when present.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

WORKER_ROOT = Path(__file__).resolve().parents[1]
REPO_DATA_COLLECTION = WORKER_ROOT.parent
sys.path.insert(0, str(WORKER_ROOT))
sys.path.insert(0, str(WORKER_ROOT / 'tests'))

FRONTEND_ROOT = REPO_DATA_COLLECTION / 'frontend'
BACKEND_ROOT = REPO_DATA_COLLECTION / 'backend'
GOLDEN_CSV = FRONTEND_ROOT / 'scripts' / 'fixtures' / 'golden_pose.csv'
POSE_MATH_JS = FRONTEND_ROOT / 'src' / 'services' / 'poseMath.js'
IPHONE_CLIP = BACKEND_ROOT / 'videos' / 'video_db05f67df8134306acfe505b8840fc71_IMG_8524.mov'
IPHONE_OLD_CSV = BACKEND_ROOT / 'data' / 'video_db05f67df8134306acfe505b8840fc71_IMG_8524.csv'

TMP = WORKER_ROOT / 'tests' / 'tmp'

has_ffmpeg = shutil.which('ffmpeg') is not None and shutil.which('ffprobe') is not None
requires_ffmpeg = pytest.mark.skipif(not has_ffmpeg, reason='ffmpeg/ffprobe not installed')
requires_node = pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')


def _has_mediapipe() -> bool:
    try:
        import mediapipe  # noqa: F401
        return True
    except ImportError:
        return False


requires_mediapipe = pytest.mark.skipif(not _has_mediapipe(), reason='mediapipe not installed')


def make_clip(name: str, fps: int, seconds: float, size: str = '320x240', extra: list = None) -> Path:
    """A moving-shape H.264 clip, like frontend/scripts/make_test_video.sh."""
    TMP.mkdir(parents=True, exist_ok=True)
    out = TMP / name
    if out.exists():
        return out
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'lavfi', '-i', f'testsrc2=size={size}:rate={fps}:duration={seconds}',
        '-vf', f"drawbox=x='(iw-40)*t/{seconds}':y='ih/2-20':w=40:h=40:color=red@0.9:t=fill",
        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-r', str(fps),
    ] + (extra or []) + [str(out)]
    subprocess.run(cmd, check=True)
    return out


@pytest.fixture(scope='session')
def clip_30fps_1s():
    return make_clip('synthetic_30fps_1s.mp4', 30, 1.0)


@pytest.fixture(scope='session')
def clip_60fps_1s():
    return make_clip('synthetic_60fps_1s.mp4', 60, 1.0)


@pytest.fixture(scope='session')
def clip_rotated():
    """A 320x240 clip carrying a 90-degree display rotation, like a phone."""
    src = make_clip('synthetic_30fps_1s.mp4', 30, 1.0)
    TMP.mkdir(parents=True, exist_ok=True)
    out = TMP / 'synthetic_rotated.mp4'
    if not out.exists():
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error', '-display_rotation', '90',
            '-i', str(src), '-c', 'copy', str(out),
        ], check=True)
    return out


def dsn_for_tests() -> str:
    return os.environ.get('TEST_DATABASE_URL', '')
