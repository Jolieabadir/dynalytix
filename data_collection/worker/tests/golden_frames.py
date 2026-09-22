"""
Python port of the frontend's scripts/golden_frames.mjs.

Same seeded LCG, same synthetic landmarks, same dropped landmarks on the same
frames, so the frames — and therefore the bytes — are identical to what the
frontend feeds framesToCSV when it produces scripts/fixtures/golden_pose.csv.
Any drift between this file and golden_frames.mjs shows up as a golden mismatch.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from angles import LANDMARK_COUNT, compute_result, timestamp_for_frame  # noqa: E402

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 60
FRAME_COUNT = 40


def make_rng(seed: int = 20260913):
    """Seeded LCG, bit-for-bit the JS one: (Math.imul(s, 1103515245) + 12345) >>> 0."""
    state = seed & 0xFFFFFFFF

    def rng() -> float:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        return state / 4294967296

    return rng


def golden_frames() -> list:
    rng = make_rng()
    frames = []
    prev_com = None
    prev_timestamp_ms = None

    for frame_num in range(FRAME_COUNT):
        timestamp_ms = timestamp_for_frame(frame_num, FPS)

        # Every 7th frame: no pose detected at all.
        if frame_num % 7 == 3:
            frames.append({'frame_num': frame_num, 'timestamp_ms': timestamp_ms, 'result': None})
            continue

        raw = []
        for _ in range(LANDMARK_COUNT):
            # Same call order as the JS object literal: x, y, z, visibility.
            x = rng()
            y = rng()
            z = rng() - 0.5
            visibility = rng()
            raw.append({'x': x, 'y': y, 'z': z, 'visibility': visibility})

        # Every 11th frame: drop a wrist and an ankle.
        if frame_num % 11 == 5:
            raw[15] = None  # left_wrist
            raw[27] = None  # left_ankle

        # Every 13th frame: drop both hips.
        if frame_num % 13 == 8:
            raw[23] = None
            raw[24] = None

        result = compute_result(
            raw, VIDEO_WIDTH, VIDEO_HEIGHT, timestamp_ms,
            prev_com=prev_com, prev_timestamp_ms=prev_timestamp_ms,
        )
        if result and result['com']:
            prev_com = result['com']
            prev_timestamp_ms = timestamp_ms

        frames.append({'frame_num': frame_num, 'timestamp_ms': timestamp_ms, 'result': result})

    return frames
