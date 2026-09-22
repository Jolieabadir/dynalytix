/**
 * Pure pose math: frame indexing, angle geometry, CSV shaping.
 *
 * Pose extraction now runs server-side (data_collection/worker, a Modal app),
 * and the worker's angles.py is a line-for-line port of this file. This file
 * is therefore the CONTRACT: the golden test (scripts/test_pose_math.mjs +
 * scripts/fixtures/golden_pose.csv) pins its bytes on the JS side, and the
 * worker's tests/test_golden.py pins the same bytes on the Python side. Change
 * one and the other must change with it.
 *
 * Deliberately free of any MediaPipe or DOM import. The browser still uses
 * normalizeLandmark(s) for hold matching against the worker's CSV.
 */

/**
 * All 33 MediaPipe Pose landmarks, index → canonical name.
 *
 * Names are MediaPipe's own, which is why the 15 that were already emitted keep
 * exactly the column names they had: they were canonical to begin with.
 */
export const LANDMARK_MAP = {
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
};

/** The 15 landmarks emitted before the widening, in their original column order. */
export const LEGACY_LANDMARK_ORDER = [
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
];

/**
 * Landmark column order: the original 15 first, then the 18 new ones in
 * MediaPipe index order.
 *
 * Deliberately NOT canonical index order for the whole set. Emitting 0..32 in
 * order would push left_shoulder from column 19 to column 23 and shift every
 * column after it. Appending instead makes the change purely additive: the
 * first 75 columns are byte-for-byte what they were, so a positional reader
 * keeps working and a name-based reader (SkeletonOverlay, the backend
 * exporter's DictReader) is unaffected either way.
 */
export const CSV_LANDMARK_ORDER = [
  ...LEGACY_LANDMARK_ORDER,
  ...Object.values(LANDMARK_MAP).filter((name) => !LEGACY_LANDMARK_ORDER.includes(name)),
];

// Angle definitions: [name, pointA, pointB (vertex), pointC]
export const ANGLE_DEFINITIONS = [
  ['left_elbow', 'left_shoulder', 'left_elbow', 'left_wrist'],
  ['right_elbow', 'right_shoulder', 'right_elbow', 'right_wrist'],
  ['left_shoulder', 'left_hip', 'left_shoulder', 'left_elbow'],
  ['right_shoulder', 'right_hip', 'right_shoulder', 'right_elbow'],
  ['left_hip', 'left_shoulder', 'left_hip', 'left_knee'],
  ['right_hip', 'right_shoulder', 'right_hip', 'right_knee'],
  ['left_knee', 'left_hip', 'left_knee', 'left_ankle'],
  ['right_knee', 'right_hip', 'right_knee', 'right_ankle'],
  ['left_ankle', 'left_knee', 'left_ankle', 'left_heel'],
  ['right_ankle', 'right_knee', 'right_ankle', 'right_heel'],
];

// ==================== GEOMETRY ====================

export function angleBetween(a, b, c) {
  // Calculate angle at point b given three landmarks
  const ab = { x: a.x - b.x, y: a.y - b.y };
  const cb = { x: c.x - b.x, y: c.y - b.y };
  const dot = ab.x * cb.x + ab.y * cb.y;
  const magAB = Math.sqrt(ab.x ** 2 + ab.y ** 2);
  const magCB = Math.sqrt(cb.x ** 2 + cb.y ** 2);
  if (magAB === 0 || magCB === 0) return null;
  const cosAngle = Math.max(-1, Math.min(1, dot / (magAB * magCB)));
  return Math.acos(cosAngle) * (180 / Math.PI);
}

export function midpoint(a, b) {
  return {
    x: (a.x + b.x) / 2,
    y: (a.y + b.y) / 2,
    z: (a.z + b.z) / 2,
  };
}

function calculateUpperBack(landmarks) {
  const ls = landmarks['left_shoulder'];
  const rs = landmarks['right_shoulder'];
  if (!ls || !rs) return null;
  const mid = midpoint(ls, rs);
  return angleBetween(ls, mid, rs);
}

function calculateLowerBack(landmarks) {
  const ls = landmarks['left_shoulder'];
  const rs = landmarks['right_shoulder'];
  const lh = landmarks['left_hip'];
  const rh = landmarks['right_hip'];
  const lk = landmarks['left_knee'];
  const rk = landmarks['right_knee'];
  if (!ls || !rs || !lh || !rh || !lk || !rk) return null;
  const shoulderMid = midpoint(ls, rs);
  const hipMid = midpoint(lh, rh);
  const kneeMid = midpoint(lk, rk);
  return angleBetween(shoulderMid, hipMid, kneeMid);
}

export function distance(a, b) {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
}

// ==================== FRAME INDEX MATH ====================

/** frame_index for a presentation time at the video's fps (the worker does the same). */
export function frameIndexFor(mediaTimeSeconds, fps) {
  return Math.round(mediaTimeSeconds * fps);
}

/** Total frames in a clip of this duration. Rounds, so the last partial frame survives. */
export function totalFramesFor(durationSeconds, fps) {
  return Math.round(durationSeconds * fps);
}

// ==================== FRAME RESULT ====================

/**
 * Turn one frame's raw MediaPipe landmarks into the row payload.
 *
 * `videoWidth`/`videoHeight` must be the ORIGINAL video dimensions, not the
 * downscaled inference canvas's. MediaPipe returns normalized coordinates and
 * the CSV stores pixels at source resolution, so denormalizing against the
 * smaller canvas would silently shrink every coordinate.
 *
 * @param {Array<{x:number,y:number,z:number,visibility?:number}>} rawLandmarks
 * @param {{prevCom: object|null, prevTimestampMs: number|null}} prev
 */
export function computeResult(rawLandmarks, videoWidth, videoHeight, timestampMs, prev = {}) {
  if (!rawLandmarks) return null;

  const landmarks = {};
  for (const [index, name] of Object.entries(LANDMARK_MAP)) {
    const lm = rawLandmarks[parseInt(index)];
    if (lm) {
      landmarks[name] = {
        x: lm.x * videoWidth,
        y: lm.y * videoHeight,
        z: lm.z,
        visibility: lm.visibility || 0,
      };
    }
  }

  // Calculate 10 standard angles
  const angles = {};
  for (const [angleName, ptA, ptB, ptC] of ANGLE_DEFINITIONS) {
    if (landmarks[ptA] && landmarks[ptB] && landmarks[ptC]) {
      angles[angleName] = angleBetween(landmarks[ptA], landmarks[ptB], landmarks[ptC]);
    } else {
      angles[angleName] = null;
    }
  }
  // 2 back angles
  angles['upper_back'] = calculateUpperBack(landmarks);
  angles['lower_back'] = calculateLowerBack(landmarks);

  // Center of mass speed
  let comSpeed = 0;
  let com = null;
  if (landmarks['left_hip'] && landmarks['right_hip']) {
    com = midpoint(landmarks['left_hip'], landmarks['right_hip']);
    const { prevCom, prevTimestampMs } = prev;
    if (prevCom && prevTimestampMs !== null && prevTimestampMs !== undefined) {
      const dt = (timestampMs - prevTimestampMs) / 1000; // seconds
      if (dt > 0) {
        comSpeed = distance(com, prevCom) / dt;
      }
    }
    landmarks._com = com;
  }

  return { landmarks, angles, comSpeed, com };
}

// ==================== ROW / CSV SHAPING ====================

/**
 * Turn captured samples into contiguous CSV rows.
 *
 * Two invariants matter downstream: SkeletonOverlay indexes the parsed CSV by
 * position, so row N must be frame N; and frame numbers must line up with what
 * the player computes from currentTime. So frame_number comes from the
 * presentation time, duplicates are dropped, and any hole is filled with an
 * empty (pose-less) row rather than left as a gap.
 *
 * @param {Array<{mediaTime: number, result: object|null}>} samples
 * @param {number} fps
 */
export function buildRows(samples, fps) {
  const ordered = [...samples].sort((a, b) => a.mediaTime - b.mediaTime);

  const byIndex = new Map();
  for (const sample of ordered) {
    const frameNum = frameIndexFor(sample.mediaTime, fps);
    // First writer wins: the earliest presentation time for this index.
    if (!byIndex.has(frameNum)) {
      byIndex.set(frameNum, sample.result);
    }
  }

  if (byIndex.size === 0) return [];

  let maxIndex = 0;
  for (const key of byIndex.keys()) {
    if (key > maxIndex) maxIndex = key;
  }

  const rows = [];
  for (let frameNum = 0; frameNum <= maxIndex; frameNum++) {
    rows.push({
      frameNum,
      // Derived from the index, so timestamp_ms === frame_number / fps exactly.
      timestampMs: (frameNum / fps) * 1000,
      result: byIndex.has(frameNum) ? byIndex.get(frameNum) : null,
    });
  }
  return rows;
}

/** The 147-column header. Order is a fixed contract. */
export function csvHeaders() {
  const landmarkNames = CSV_LANDMARK_ORDER;
  const headers = [
    'frame_number', 'timestamp_ms', 'speed_center_of_mass',
    ...ANGLE_DEFINITIONS.map(([name]) => `angle_${name}`),
    'angle_upper_back', 'angle_lower_back',
  ];
  for (const name of landmarkNames) {
    headers.push(`landmark_${name}_x`, `landmark_${name}_y`, `landmark_${name}_z`, `landmark_${name}_visibility`);
  }
  return headers;
}

/** Decimal places kept for landmark coordinates in the CSV. */
export const COORD_DECIMALS = 4;

/** Decimal places kept for landmark visibility in the CSV. */
export const VISIBILITY_DECIMALS = 3;

/**
 * Round for output only.
 *
 * Applied in the writer, never to the in-memory result, so angles and
 * centre-of-mass speed are still computed at full precision and only the stored
 * text is shortened. Uses round-and-divide rather than toFixed so that values
 * stringify without padding: 0 stays "0", not "0.0000".
 *
 * x and y are pixels at source resolution, so 4 decimals is 1/10000 of a pixel
 * — far below anything measurable. z and visibility are roughly normalized.
 */
function round(value, decimals) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return value;
  const factor = 10 ** decimals;
  // + 0 collapses -0 to 0, which would otherwise stringify inconsistently.
  return Math.round(value * factor) / factor + 0;
}

/** Build the CSV string. Column order and value formatting are a fixed contract. */
export function framesToCSV(frames) {
  const landmarkNames = CSV_LANDMARK_ORDER;
  const rows = [csvHeaders().join(',')];

  for (const frame of frames) {
    const row = [
      frame.frameNum,
      frame.timestampMs,
      frame.result ? frame.result.comSpeed : 0,
    ];

    // Angles
    for (const [angleName] of ANGLE_DEFINITIONS) {
      row.push(frame.result?.angles?.[angleName] ?? '');
    }
    row.push(frame.result?.angles?.['upper_back'] ?? '');
    row.push(frame.result?.angles?.['lower_back'] ?? '');

    // Landmarks
    for (const name of landmarkNames) {
      const lm = frame.result?.landmarks?.[name];
      if (lm) {
        row.push(
          round(lm.x, COORD_DECIMALS),
          round(lm.y, COORD_DECIMALS),
          round(lm.z, COORD_DECIMALS),
          round(lm.visibility, VISIBILITY_DECIMALS)
        );
      } else {
        row.push('', '', '', '');
      }
    }

    rows.push(row.join(','));
  }

  return rows.join('\n');
}

// ==================== COORDINATE SPACES ====================

/**
 * Landmarks are stored as PIXELS; hold boxes are stored NORMALIZED 0-1.
 *
 * `computeResult` multiplies MediaPipe's normalized output by the source
 * `videoWidth`/`videoHeight`, so `landmark_*_x` / `landmark_*_y` in the CSV are
 * pixels at the original resolution. `public.holds` stores `bbox_*` as
 * fractions of the frame. The two cannot be compared without dividing the
 * landmarks back down by the frame size first — a 1920x1080 wrist at x=960 and
 * a hold at bbox_x=0.5 are the same place, and comparing 960 against 0.5
 * silently makes every hold look infinitely far away.
 *
 * Note `z` is NOT divided. MediaPipe's z is a depth estimate on roughly the
 * same scale as normalized x, never multiplied by a pixel dimension, so
 * dividing it here would corrupt it.
 *
 * @param {{x: number, y: number, z?: number, visibility?: number}} landmark
 * @param {number} width intrinsic video width in pixels
 * @param {number} height intrinsic video height in pixels
 * @returns {{x: number, y: number, z?: number, visibility?: number}|null}
 *   null when the frame size is unknown — callers must skip the comparison
 *   rather than assume a resolution.
 */
export function normalizeLandmark(landmark, width, height) {
  if (!landmark) return null;
  if (!(width > 0) || !(height > 0)) return null;
  return {
    ...landmark,
    x: landmark.x / width,
    y: landmark.y / height,
  };
}

/**
 * Normalize a whole landmark map (the shape `computeResult` returns, or a row
 * parsed out of the CSV).
 *
 * Returns null when the frame size is unknown, so a missing width/height fails
 * loudly at the call site instead of producing plausible-looking nonsense.
 */
export function normalizeLandmarks(landmarks, width, height) {
  if (!landmarks) return null;
  if (!(width > 0) || !(height > 0)) return null;

  const out = {};
  for (const [name, lm] of Object.entries(landmarks)) {
    if (name.startsWith('_')) continue; // internal, e.g. _com
    const n = normalizeLandmark(lm, width, height);
    if (n) out[name] = n;
  }
  return out;
}
