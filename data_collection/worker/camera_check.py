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
    camera_drift             largest displacement of the frame centre from
                             where it started, as a fraction of the diagonal
                             (catches slow pans that per-frame motion misses;
                             this is what moves hold boxes off their holds)
    camera_zoom_range        max / min scale of each frame relative to the
                             first (1.0 = no zoom)
    camera_motion_frames_pct share of measured frame pairs whose background
                             moved more than MOVING_FRAME_DISPLACEMENT

Background motion: features are tracked frame to frame with Lucas-Kanade
optical flow, outside the climber's bounding box (from the pose landmarks,
dilated PERSON_BOX_MARGIN on each side; the whole frame when no pose), and a
similarity transform is fit with RANSAC. Its translation and scale are the
camera's motion. A frame pair with too few trackable features is skipped
(counted in frames_skipped), not treated as still. Drift and zoom register
each frame against an anchor frame (the first frame of the shot) rather than
multiplying per-frame steps, so estimation noise cannot compound into a fake
zoom and a slow pan cannot hide under a per-frame threshold; the anchor moves
forward only when it stops overlapping enough to track.

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

#: Once the current frame has moved this far from the anchor frame (fraction
#: of the diagonal), registration re-anchors on it: Lucas-Kanade is only
#: reliable for moderate displacements, and a far anchor shares little view.
ANCHOR_MAX_SHIFT = 0.10

#: Which percentile of the per-frame displacement is the score.
SCORE_PERCENTILE = 95



def _cv2():
    import cv2  # local: keeps `import camera_check` cheap and testable
    return cv2


class CameraCheck:
    """Accumulates camera motion, drift, zoom and cuts for one clip."""

    def __init__(self, width: int, height: int):
        if width <= 0 or height <= 0:
            raise ValueError('frame size must be positive')
        scale = min(1.0, ANALYSIS_WIDTH / float(width))
        self.width = max(16, int(round(width * scale)))
        self.height = max(16, int(round(height * scale)))
        self.diagonal = math.hypot(self.width, self.height)
        self._centre = np.array([self.width / 2.0, self.height / 2.0, 1.0])

        self._prev_gray: Optional[np.ndarray] = None
        self._prev_hist: Optional[np.ndarray] = None
        self._prev_mask: Optional[np.ndarray] = None
        self._prev_world: Optional[np.ndarray] = None
        self._index = -1
        self._start_shot(None, None, None)

        self.cut_frames: List[int] = []
        self.displacements: List[float] = []
        self.drifts: List[float] = [0.0]
        self.scale_track: List[float] = [1.0]
        self.frames_seen = 0
        self.frames_skipped = 0
        self.reanchors = 0

    # ---------- helpers ----------

    def _start_shot(self, gray, mask, world):
        """Anchor registration on this frame (start of the clip or a shot)."""
        self._ref_gray, self._ref_mask = gray, mask
        self._ref_world = np.eye(3) if world is None else world

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

    def _register(self, src_gray, dst_gray, src_mask) -> Optional[np.ndarray]:
        """3x3 similarity transform taking src pixel coords to dst, from
        background features of src, or None when too few track."""
        cv2 = _cv2()
        points = cv2.goodFeaturesToTrack(src_gray, maxCorners=200, qualityLevel=0.01,
                                         minDistance=6, mask=src_mask)
        if points is None or len(points) < MIN_TRACKED_POINTS:
            return None
        moved, status, _err = cv2.calcOpticalFlowPyrLK(src_gray, dst_gray, points, None,
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
        scale = math.hypot(float(matrix[0, 0]), float(matrix[1, 0]))
        if not math.isfinite(scale) or scale <= 0:
            return None
        return np.vstack([matrix, [0.0, 0.0, 1.0]])

    def _centre_shift(self, transform: np.ndarray) -> float:
        """Where the frame centre moves under `transform`, as a fraction of the
        diagonal. A zoom about the centre reads as ~0 here and as scale."""
        moved = transform @ self._centre
        return math.hypot(moved[0] - self._centre[0], moved[1] - self._centre[1]) / self.diagonal

    @staticmethod
    def _scale_of(transform: np.ndarray) -> float:
        return math.sqrt(abs(float(np.linalg.det(transform[:2, :2]))))

    # ---------- per frame ----------

    def feed(self, frame_rgb: np.ndarray, landmarks=None) -> None:
        """Add the next frame (RGB uint8) and the pose found on it, if any."""
        cv2 = _cv2()
        self._index += 1
        self.frames_seen += 1
        small = cv2.resize(frame_rgb, (self.width, self.height), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        hist = self._histogram(small)
        mask = self._mask_for(landmarks)

        if self._prev_gray is None:
            self._start_shot(gray, mask, None)
            world = np.eye(3)
        else:
            distance = cv2.compareHist(self._prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
            if distance > CUT_DISTANCE:
                # A new shot: motion across a cut is meaningless. Registration
                # restarts in the new shot's own frame; the cut fails the
                # check by itself.
                self.cut_frames.append(self._index)
                self._start_shot(gray, mask, None)
                world = np.eye(3)
            else:
                # 1) Frame-to-frame motion (the per-frame score). The climber
                #    is excluded through the previous frame's box, which is
                #    where features are picked.
                step = self._register(self._prev_gray, gray, self._prev_mask)
                if step is None:
                    self.frames_skipped += 1
                else:
                    self.displacements.append(self._centre_shift(step))

                # 2) Drift and zoom since the start of the shot: register
                #    against the anchor frame directly, so per-frame noise does
                #    not compound and a slow pan or zoom still adds up. When
                #    the anchor no longer overlaps enough, chain through the
                #    frame-to-frame step and re-anchor here.
                to_ref = self._register(self._ref_gray, gray, self._ref_mask)
                if to_ref is not None:
                    world = to_ref @ self._ref_world
                    if (self._centre_shift(to_ref) > ANCHOR_MAX_SHIFT
                            or abs(self._scale_of(to_ref) - 1.0) > ANCHOR_MAX_SHIFT):
                        self._start_shot(gray, mask, world)
                        self.reanchors += 1
                elif step is not None and self._prev_world is not None:
                    world = step @ self._prev_world
                    self._start_shot(gray, mask, world)
                    self.reanchors += 1
                else:
                    world = None  # lost this frame; keep the last good position
                if world is not None:
                    self.drifts.append(self._centre_shift(world))
                    self.scale_track.append(self._scale_of(world))

        if world is not None:
            self._prev_world = world
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
        zoom = max(self.scale_track) / min(self.scale_track) if self.scale_track else 1.0
        return {
            'has_cut': bool(self.cut_frames),
            'cut_frames': list(self.cut_frames),
            'camera_motion_score': None if score is None else round(score, 6),
            'camera_drift': round(float(max(self.drifts)), 6),
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
