"""
Camera-motion and cut check for one clip (runbook W2 Worker).

Broadcast footage pans, zooms and cuts. Two things downstream assume a fixed
camera: hold boxes are drawn once, on frame 1, and the pose features are in
pixel coordinates, so a pan shows up as climber velocity (and pushes moves
towards "dynamic"). The paper only uses clips with a static or near-static
camera and no cuts. This module measures that; the backend refuses to mark a
clip ready when it fails (unless an admin overrides with a note).

Fed one frame at a time by extract.py, reusing the decoded frames and the
pose landmarks, so it adds no second decode:

    check = CameraCheck(width, height)
    for frame, landmarks in ...:
        check.feed(frame, landmarks)      # RGB uint8 (H, W, 3); landmarks or None
    metrics = check.summary()

Metrics (all on a downscaled grayscale copy, ANALYSIS_WIDTH px wide):

    has_cut                  any consecutive pair whose colour histograms
                             differ by more than CUT_DISTANCE (Bhattacharyya)
    cut_frames               indices of the frames that start a new shot
    camera_motion_score      95th percentile of the per-frame background
                             displacement, as a fraction of the frame
                             diagonal (0.002 = 0.2% of the diagonal per frame)
    camera_zoom_range        max / min of the cumulative scale of the
                             background (1.0 = no zoom)
    camera_motion_frames_pct share of measured frame pairs whose background
                             moved more than MOVING_FRAME_DISPLACEMENT

Background motion: features are tracked frame to frame with Lucas-Kanade
optical flow, outside the climber's bounding box (from the pose landmarks,
dilated PERSON_BOX_MARGIN on each side; the whole frame when no pose), and a
similarity transform is fit with RANSAC. Its translation and scale are the
camera's motion. A frame pair with too few trackable features is skipped
(counted in frames_skipped), not treated as still.

Pure numpy + OpenCV, no Modal import, so it runs the same in tests.
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional

import numpy as np

log = logging.getLogger('camera_check')

#: Width the analysis runs at. Motion is normalized by the diagonal, so the
#: metrics do not depend on it; it only bounds the cost per frame.
ANALYSIS_WIDTH = 320

#: Bhattacharyya distance between consecutive HSV histograms above which the
#: pair is a cut. Same-shot frames, even with a fast pan, sit well under 0.3.
CUT_DISTANCE = 0.5

#: Fraction of the box size added on each side of the climber's box.
PERSON_BOX_MARGIN = 0.20

#: Fewer tracked background points than this and the pair is not measured.
MIN_TRACKED_POINTS = 12

#: Per-frame displacement (fraction of the diagonal) above which a frame pair
#: counts as "camera moving" for camera_motion_frames_pct.
MOVING_FRAME_DISPLACEMENT = 0.0005

#: Which percentile of the per-frame displacement is the score.
SCORE_PERCENTILE = 95

#: Per-frame scale changes smaller than this are treated as 1.0 when building
#: the cumulative zoom track. Estimation noise of a few tenths of a percent per
#: frame would otherwise compound over hundreds of frames into a fake zoom.
ZOOM_DEADBAND = 0.002


def _cv2():
    import cv2  # local: keeps `import camera_check` cheap and testable
    return cv2


class CameraCheck:
    """Accumulates per-frame camera motion and cuts for one clip."""

    def __init__(self, width: int, height: int):
        if width <= 0 or height <= 0:
            raise ValueError('frame size must be positive')
        scale = min(1.0, ANALYSIS_WIDTH / float(width))
        self.width = max(16, int(round(width * scale)))
        self.height = max(16, int(round(height * scale)))
        self.diagonal = math.hypot(self.width, self.height)

        self._prev_gray: Optional[np.ndarray] = None
        self._prev_hist: Optional[np.ndarray] = None
        self._prev_mask: Optional[np.ndarray] = None
        self._index = -1

        self.cut_frames: List[int] = []
        self.displacements: List[float] = []
        self._cumulative_scale = 1.0
        self.scale_track: List[float] = [1.0]
        self.frames_seen = 0
        self.frames_skipped = 0

    # ---------- per frame ----------

    def _mask_for(self, landmarks) -> np.ndarray:
        """255 where background features may be taken, 0 over the climber."""
        mask = np.full((self.height, self.width), 255, dtype=np.uint8)
        if not landmarks:
            return mask
        xs = [lm['x'] for lm in landmarks if lm is not None and 'x' in lm]
        ys = [lm['y'] for lm in landmarks if lm is not None and 'y' in lm]
        if not xs or not ys:
            return mask
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        mx, my = (x1 - x0) * PERSON_BOX_MARGIN, (y1 - y0) * PERSON_BOX_MARGIN
        left = int(max(0.0, (x0 - mx)) * self.width)
        right = int(min(1.0, (x1 + mx)) * self.width)
        top = int(max(0.0, (y0 - my)) * self.height)
        bottom = int(min(1.0, (y1 + my)) * self.height)
        if right > left and bottom > top:
            mask[top:bottom, left:right] = 0
        return mask

    def _histogram(self, small_rgb: np.ndarray) -> np.ndarray:
        cv2 = _cv2()
        hsv = cv2.cvtColor(small_rgb, cv2.COLOR_RGB2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist

    def _motion(self, prev_gray, gray, mask) -> Optional[tuple]:
        """(normalized displacement, scale) of the background, or None."""
        cv2 = _cv2()
        points = cv2.goodFeaturesToTrack(prev_gray, maxCorners=200, qualityLevel=0.01,
                                         minDistance=6, mask=mask)
        if points is None or len(points) < MIN_TRACKED_POINTS:
            return None
        moved, status, _err = cv2.calcOpticalFlowPyrLK(prev_gray, gray, points, None,
                                                       winSize=(21, 21), maxLevel=3)
        if moved is None or status is None:
            return None
        ok = status.reshape(-1) == 1
        src, dst = points.reshape(-1, 2)[ok], moved.reshape(-1, 2)[ok]
        if len(src) < MIN_TRACKED_POINTS:
            return None
        matrix, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                                      ransacReprojThreshold=2.0)
        if matrix is None or inliers is None or int(inliers.sum()) < MIN_TRACKED_POINTS:
            return None
        a, b = float(matrix[0, 0]), float(matrix[1, 0])
        tx, ty = float(matrix[0, 2]), float(matrix[1, 2])
        scale = math.hypot(a, b)
        if not math.isfinite(scale) or scale <= 0:
            return None
        # Translation of the frame centre, so a pure zoom about the centre
        # reads as zero displacement and shows up in the scale instead.
        cx, cy = self.width / 2.0, self.height / 2.0
        dx = matrix[0, 0] * cx + matrix[0, 1] * cy + tx - cx
        dy = matrix[1, 0] * cx + matrix[1, 1] * cy + ty - cy
        return math.hypot(dx, dy) / self.diagonal, scale

    def feed(self, frame_rgb: np.ndarray, landmarks=None) -> None:
        """Add the next frame (RGB uint8) and the pose found on it, if any."""
        cv2 = _cv2()
        self._index += 1
        self.frames_seen += 1
        small = cv2.resize(frame_rgb, (self.width, self.height), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        hist = self._histogram(small)
        mask = self._mask_for(landmarks)

        if self._prev_gray is not None:
            distance = cv2.compareHist(self._prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
            if distance > CUT_DISTANCE:
                # A new shot: motion across a cut is meaningless, and the
                # zoom track restarts from the new shot's framing.
                self.cut_frames.append(self._index)
            else:
                # Exclude the climber in BOTH frames: the previous frame's
                # box is where features are picked.
                measured = self._motion(self._prev_gray, gray, self._prev_mask)
                if measured is None:
                    self.frames_skipped += 1
                else:
                    displacement, scale = measured
                    self.displacements.append(displacement)
                    if abs(scale - 1.0) >= ZOOM_DEADBAND:
                        self._cumulative_scale *= scale
                    self.scale_track.append(self._cumulative_scale)

        self._prev_gray, self._prev_hist, self._prev_mask = gray, hist, mask

    # ---------- result ----------

    def summary(self) -> dict:
        """The metrics for the videos row."""
        if self.displacements:
            values = np.asarray(self.displacements, dtype=float)
            score = float(np.percentile(values, SCORE_PERCENTILE))
            moving_pct = float((values > MOVING_FRAME_DISPLACEMENT).mean() * 100.0)
        else:
            score, moving_pct = None, None
        zoom = (max(self.scale_track) / min(self.scale_track)) if len(self.scale_track) > 1 else 1.0
        return {
            'has_cut': bool(self.cut_frames),
            'cut_frames': list(self.cut_frames),
            'camera_motion_score': None if score is None else round(score, 6),
            'camera_zoom_range': round(float(zoom), 4),
            'camera_motion_frames_pct': None if moving_pct is None else round(moving_pct, 2),
            'camera_frames_measured': len(self.displacements),
            'camera_frames_skipped': self.frames_skipped,
        }


def analyze_file(path: str, max_frames: Optional[int] = None) -> dict:
    """Run the check on a video file without pose (whole frame as background).

    For calibration from a shell; the worker uses CameraCheck inside
    extract.py so frames are decoded once.

        python camera_check.py clip.mp4 [clip2.mp4 ...]
    """
    from extract import iter_frames, probe_video

    probe = probe_video(path)
    check = CameraCheck(probe.width, probe.height)
    for n, (_pts, frame) in enumerate(iter_frames(path, probe)):
        if max_frames is not None and n >= max_frames:
            break
        check.feed(frame, None)
    return check.summary()


if __name__ == '__main__':  # pragma: no cover - manual calibration
    import json
    import sys

    logging.basicConfig(level=logging.INFO)
    for clip in sys.argv[1:]:
        print(json.dumps({'clip': clip, **analyze_file(clip)}))
