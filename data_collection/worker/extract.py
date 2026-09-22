"""
Pose extraction pipeline: video file -> pose CSV string.

Pure Python plus ffmpeg and MediaPipe; no Modal import, so it runs identically
on a laptop CPU (tests) and on the Modal T4 (production).

    probe = probe_video(path)                       # ffprobe: fps, size, duration
    csv_text, meta = extract_pose_csv(path, model_path)

Or from a shell:  python extract.py clip.mov > clip.csv

Stages:

1. ffprobe: nominal fps, display width/height (after the container's rotation
   tag - iPhone clips are stored landscape with a -90 rotation, and the browser
   reports the rotated size as videoWidth/videoHeight, which is the resolution
   the CSV's pixel coordinates must be in) and duration.
2. ffmpeg decodes to raw RGB frames over a pipe, auto-rotated and in
   presentation order, with the `showinfo` filter reporting each output
   frame's presentation time on stderr. That is the same quantity the browser
   read from requestVideoFrameCallback's mediaTime, and it already has the
   container's edit list applied (an iPhone clip carries pre-roll packets at
   negative pts that never reach the screen; packet-level probing would count
   them, showinfo does not).
3. PoseLandmarker FULL in VIDEO mode, one call per frame.
4. The 12 angles and the CSV via angles.py: the exact frontend contract.

Frame indexing follows the browser extractor's rules (poseMath.buildRows):
frame_number = round(pts * fps), first writer wins on a duplicate index, any
hole is filled with a pose-less row, and timestamp_ms = frame_number / fps *
1000 exactly. SkeletonOverlay indexes the parsed CSV by position, so row N must
be frame N with no gaps.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path
from typing import Callable, Iterator, List, Optional

import numpy as np

from angles import compute_result, frames_to_csv, js_round, timestamp_for_frame

log = logging.getLogger('extract')

#: fps values a phone or camera actually produces. Mirrors poseMath.KNOWN_FPS.
#: A measured 29.97 or 59.94 snaps to its nominal neighbour, as the browser did.
KNOWN_FPS = [24, 25, 30, 48, 50, 60, 120]

#: How far (relative) a measured rate may sit from a known one and still snap.
SNAP_TOLERANCE = 0.02

MODEL_URL = (
    'https://storage.googleapis.com/mediapipe-models/pose_landmarker/'
    'pose_landmarker_full/float16/1/pose_landmarker_full.task'
)

#: The FULL model vendored next to this file (9.4 MB), so tests and the Modal
#: image use the same bytes.
DEFAULT_MODEL_PATH = str(Path(__file__).resolve().parent / 'models' / 'pose_landmarker_full.task')


class PipelineError(RuntimeError):
    """A stage failed in a way that retrying the same file will not fix."""


@dataclass
class VideoProbe:
    fps: float
    width: int
    height: int
    duration_ms: float
    #: Container frame count (nb_frames), for progress only: it may include
    #: frames the edit list trims, so the decoded count is the real one.
    nominal_frames: int
    #: Raw stream size before rotation.
    coded_width: int
    coded_height: int
    rotation: int
    codec: str


@dataclass
class ExtractionMeta:
    fps: float
    total_frames: int
    duration_ms: float
    width: int
    height: int
    frames_decoded: int
    frames_with_pose: int

    def to_dict(self) -> dict:
        return asdict(self)


# ==================== ffprobe ====================

def _run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, **kwargs)
    except FileNotFoundError as exc:
        raise PipelineError(f'{cmd[0]} is not installed') from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode('utf-8', 'replace')[-2000:] if exc.stderr else ''
        raise PipelineError(f'{cmd[0]} failed ({exc.returncode}): {stderr}') from exc


def snap_fps(measured: float) -> float:
    """Snap a measured rate to the nearest plausible capture rate when close.

    29.97 -> 30, 59.94 -> 60. A rate that is not near any known one (a
    time-lapse, a screen recording at 15fps) is kept as measured, rounded to
    3 decimals so it survives the videos.fps `real` column unchanged.
    """
    if not (measured > 0):
        raise PipelineError(f'Unusable frame rate: {measured}')
    best = min(KNOWN_FPS, key=lambda k: abs(k - measured))
    if abs(best - measured) / best <= SNAP_TOLERANCE:
        return float(best)
    return round(measured, 3)


def _parse_rate(text: Optional[str]) -> Optional[float]:
    if not text or text in ('0/0', 'N/A'):
        return None
    try:
        value = float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def _rotation(stream: dict) -> int:
    for side in stream.get('side_data_list') or []:
        if 'rotation' in side:
            try:
                return int(round(float(side['rotation'])))
            except (TypeError, ValueError):
                pass
    tag = (stream.get('tags') or {}).get('rotate')
    if tag:
        try:
            return int(tag)
        except ValueError:
            pass
    return 0


def probe_video(path: str) -> VideoProbe:
    """Read the video stream metadata with ffprobe."""
    info = json.loads(_run([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries',
        'stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames'
        ':stream_side_data=rotation:stream_tags=rotate:format=duration',
        '-of', 'json', path,
    ]).stdout)

    streams = info.get('streams') or []
    if not streams:
        raise PipelineError('No video stream found')
    stream = streams[0]

    coded_width, coded_height = int(stream['width']), int(stream['height'])
    rotation = _rotation(stream)
    if abs(rotation) % 180 == 90:
        width, height = coded_height, coded_width
    else:
        width, height = coded_width, coded_height

    duration_s = None
    fmt_duration = (info.get('format') or {}).get('duration')
    if fmt_duration not in (None, 'N/A'):
        duration_s = float(fmt_duration)

    # r_frame_rate is the nominal capture rate; avg_frame_rate is skewed by
    # the edit list (an iPhone clip reports 27.3 avg at a 30fps nominal).
    # Fall back to nb_frames / duration when neither parses.
    measured = _parse_rate(stream.get('r_frame_rate')) or _parse_rate(stream.get('avg_frame_rate'))
    try:
        nominal_frames = int(stream.get('nb_frames') or 0)
    except ValueError:
        nominal_frames = 0
    if measured is None and duration_s and nominal_frames:
        measured = nominal_frames / duration_s
    if measured is None:
        raise PipelineError('Could not determine the frame rate')
    fps = snap_fps(measured)

    if duration_s is None:
        raise PipelineError('Could not determine the duration')

    return VideoProbe(
        fps=fps,
        width=width,
        height=height,
        duration_ms=duration_s * 1000,
        nominal_frames=nominal_frames,
        coded_width=coded_width,
        coded_height=coded_height,
        rotation=rotation,
        codec=stream.get('codec_name', ''),
    )


# ==================== ffmpeg frames ====================

_SHOWINFO_RE = re.compile(r'\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:(-?[0-9.]+)')


def _read_showinfo(stream, out: dict, tail: list):
    """Collect n -> pts_time from showinfo lines; keep the rest for errors."""
    for raw in iter(stream.readline, b''):
        line = raw.decode('utf-8', 'replace')
        match = _SHOWINFO_RE.search(line)
        if match and 'showinfo' in line:
            out[int(match.group(1))] = float(match.group(3))
        elif 'showinfo' not in line:
            tail.append(line)
            del tail[:-50]


def iter_frames(path: str, probe: VideoProbe) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (pts_seconds, frame) for every frame ffmpeg outputs.

    Frames are RGB uint8 arrays of shape (height, width, 3), auto-rotated, in
    presentation order. pts comes from the showinfo filter, so it is the time
    the frame is actually presented at, edit list applied.
    """
    width, height = probe.width, probe.height
    frame_bytes = width * height * 3
    cmd = [
        'ffmpeg', '-nostdin', '-nostats', '-v', 'info',
        '-i', path,
        '-map', '0:v:0',
        '-vf', 'showinfo',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24',
        '-vsync', 'passthrough',
        'pipe:1',
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=frame_bytes * 4)
    except FileNotFoundError as exc:
        raise PipelineError('ffmpeg is not installed') from exc

    pts_by_n: dict = {}
    stderr_tail: list = []
    reader = threading.Thread(target=_read_showinfo, args=(proc.stderr, pts_by_n, stderr_tail), daemon=True)
    reader.start()

    try:
        n = 0
        while True:
            chunk = proc.stdout.read(frame_bytes)
            if not chunk:
                break
            if len(chunk) < frame_bytes:
                raise PipelineError(
                    f'Truncated frame from ffmpeg ({len(chunk)} of {frame_bytes} bytes); '
                    f'probed size {width}x{height} may be wrong'
                )
            frame = np.frombuffer(chunk, dtype=np.uint8).reshape((height, width, 3))
            # showinfo logs before the frame is written, but the stderr thread
            # may not have parsed it yet; wait briefly rather than guess.
            for _ in range(2000):
                if n in pts_by_n:
                    break
                time.sleep(0.001)
            pts = pts_by_n.get(n)
            if pts is None:
                pts = n / probe.fps
                log.warning('no showinfo pts for frame %d; assuming %.4fs', n, pts)
            yield pts, frame
            n += 1
        code = proc.wait()
        reader.join(timeout=5)
        if code != 0:
            raise PipelineError(f'ffmpeg exited {code}: {"".join(stderr_tail)[-2000:]}')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


# ==================== MediaPipe ====================

def make_landmarker(model_path: str, use_gpu: bool = False):
    """Build a PoseLandmarker FULL in VIDEO mode.

    `use_gpu` asks for the TFLite GPU delegate (OpenGL ES via EGL). It is not
    available on every container - and never on a laptop test run - so a
    failure to create the GPU landmarker falls back to CPU with a warning
    rather than failing the job. Landmark output is the same model either way.
    """
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    def build(delegate):
        options = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=model_path, delegate=delegate),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            # MediaPipe Tasks defaults; the browser used the same ones.
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_segmentation_masks=False,
        )
        return vision.PoseLandmarker.create_from_options(options)

    if use_gpu:
        try:
            return build(mp_python.BaseOptions.Delegate.GPU), mp
        except Exception as exc:  # noqa: BLE001 - any delegate failure means "no GPU here"
            log.warning('GPU delegate unavailable (%s: %s); using CPU', type(exc).__name__, exc)
    return build(mp_python.BaseOptions.Delegate.CPU), mp


def landmarks_from_result(result) -> Optional[list]:
    """First detected pose as a list of 33 {x, y, z, visibility}, or None."""
    poses = getattr(result, 'pose_landmarks', None)
    if not poses:
        return None
    pose = poses[0]
    if not pose:
        return None
    return [
        {'x': lm.x, 'y': lm.y, 'z': lm.z, 'visibility': lm.visibility}
        for lm in pose
    ]


# ==================== ROW SHAPING ====================

def build_rows(indexed_results: dict, fps: float) -> List[dict]:
    """Contiguous rows from {frame_index: result}, holes filled with None.

    Same rule as the frontend's buildRows.
    """
    if not indexed_results:
        return []
    max_index = max(indexed_results)
    return [
        {
            'frame_num': n,
            'timestamp_ms': timestamp_for_frame(n, fps),
            'result': indexed_results.get(n),
        }
        for n in range(max_index + 1)
    ]


def frame_index_for(pts_seconds: float, fps: float) -> int:
    """frame_number for a presentation time: round(pts * fps), as the browser did."""
    return int(js_round(pts_seconds * fps))


# ==================== DRIVER ====================

def extract_pose_csv(
    video_path: str,
    model_path: str = DEFAULT_MODEL_PATH,
    use_gpu: bool = False,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> tuple[str, ExtractionMeta]:
    """Run the whole pipeline. Returns (csv_text, meta)."""
    probe = probe_video(video_path)
    log.info(
        'probe: %s %dx%d (coded %dx%d, rot %d) fps=%s frames=%d duration=%.0fms',
        probe.codec, probe.width, probe.height, probe.coded_width, probe.coded_height,
        probe.rotation, probe.fps, probe.nominal_frames, probe.duration_ms,
    )

    landmarker, mp = make_landmarker(model_path, use_gpu=use_gpu)
    indexed: dict = {}
    prev_com = None
    prev_timestamp_ms = None
    decoded = 0
    with_pose = 0
    last_mp_ts = -1

    try:
        for pts, frame in iter_frames(video_path, probe):
            decoded += 1
            frame_num = frame_index_for(pts, probe.fps)
            if frame_num < 0:
                continue  # before the clip's own zero; never presented
            if frame_num in indexed:
                continue  # first writer wins, as in the browser
            timestamp_ms = timestamp_for_frame(frame_num, probe.fps)

            # MediaPipe VIDEO mode needs strictly increasing integer ms.
            mp_ts = max(int(round(timestamp_ms)), last_mp_ts + 1)
            last_mp_ts = mp_ts

            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame))
            raw = landmarks_from_result(landmarker.detect_for_video(image, mp_ts))

            result = compute_result(
                raw, probe.width, probe.height, timestamp_ms,
                prev_com=prev_com, prev_timestamp_ms=prev_timestamp_ms,
            )
            if result is not None:
                with_pose += 1
                if result['com']:
                    prev_com = result['com']
                    prev_timestamp_ms = timestamp_ms
            indexed[frame_num] = result

            if on_progress and decoded % 100 == 0:
                on_progress(decoded, probe.nominal_frames)
    finally:
        landmarker.close()

    if decoded == 0:
        raise PipelineError('ffmpeg produced no frames')

    rows = build_rows(indexed, probe.fps)
    csv_text = frames_to_csv(rows)
    meta = ExtractionMeta(
        fps=probe.fps,
        total_frames=len(rows),
        duration_ms=probe.duration_ms,
        width=probe.width,
        height=probe.height,
        frames_decoded=decoded,
        frames_with_pose=with_pose,
    )
    log.info('done: %d rows, %d decoded, %d with a pose', len(rows), decoded, with_pose)
    return csv_text, meta


if __name__ == '__main__':  # pragma: no cover - manual use
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='Video -> pose CSV (frontend contract).')
    parser.add_argument('video')
    parser.add_argument('--model', default=DEFAULT_MODEL_PATH)
    parser.add_argument('--gpu', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
    text, info = extract_pose_csv(args.video, args.model, use_gpu=args.gpu)
    sys.stdout.write(text)
    print(json.dumps(info.to_dict()), file=sys.stderr)
