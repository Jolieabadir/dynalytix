/**
 * Tests for the pose frame/timestamp math and the CSV contract.
 *
 * Run: node --test scripts/test_pose_math.mjs
 *
 * poseMath.js is the CSV contract the server-side worker
 * (data_collection/worker/angles.py) reproduces byte for byte; the golden
 * file here is the shared fixture. The frame-index tests use real frame
 * presentation times recorded from the clips scripts/make_test_video.sh
 * generates, read back with ffprobe — the same quantity the worker reads from
 * ffmpeg's showinfo filter.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  frameIndexFor,
  totalFramesFor,
  buildRows,
  framesToCSV,
  csvHeaders,
  computeResult,
  LANDMARK_MAP,
  ANGLE_DEFINITIONS,
  CSV_LANDMARK_ORDER,
  LEGACY_LANDMARK_ORDER,
} from '../src/services/poseMath.js';
import { normalizeLandmark, normalizeLandmarks } from '../src/services/poseMath.js';
import {
  distanceToBox,
  isInsideBox,
  nearestHold,
  nearestHoldsFor,
  CONTACT_LANDMARKS,
} from '../src/services/holdMatching.js';
import {
  suggestHoldsForFrame,
  landmarkFromRow,
  contactLandmarksFromRow,
  bodyPartsFor,
  sideFor,
  CONTACT_META,
  CONTACT_THRESHOLD,
} from '../src/services/holdSuggestions.js';
import { goldenFrames } from './golden_frames.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const loadFixture = (name) =>
  JSON.parse(readFileSync(join(HERE, 'fixtures', name), 'utf8'));

const fixture30 = loadFixture('frame_times_30fps.json');
const fixture60 = loadFixture('frame_times_60fps.json');

// ==================== FRAME INDEX MATH ====================

test('frameIndexFor rounds to the nearest frame', () => {
  assert.equal(frameIndexFor(0, 30), 0);
  assert.equal(frameIndexFor(1 / 30, 30), 1);
  assert.equal(frameIndexFor(0.99 / 30, 30), 1); // just early, still frame 1
  assert.equal(frameIndexFor(1.01 / 30, 30), 1); // just late, still frame 1
  assert.equal(frameIndexFor(10, 60), 600);
});

test('totalFramesFor rounds rather than truncating', () => {
  assert.equal(totalFramesFor(10, 30), 300);
  assert.equal(totalFramesFor(10, 60), 600);
  // The old Math.floor dropped the final partial frame.
  assert.equal(totalFramesFor(9.99, 30), 300);
  assert.equal(totalFramesFor(120.5, 60), 7230);
});

test('every recorded presentation time maps to its own frame index', () => {
  for (const fx of [fixture30, fixture60]) {
    const indices = fx.mediaTimes.map((t) => frameIndexFor(t, fx.nominalFps));
    const unique = new Set(indices);
    assert.equal(
      unique.size,
      indices.length,
      `${fx.source}: two frames collided on one index`
    );
    for (let i = 0; i < indices.length; i++) {
      assert.equal(indices[i], i, `${fx.source}: frame ${i} indexed as ${indices[i]}`);
    }
  }
});

// ==================== ROW SHAPING ====================

const fakeResult = (n) => ({
  landmarks: Object.fromEntries(
    Object.values(LANDMARK_MAP).map((name) => [
      name,
      { x: n, y: n * 2, z: 0.5, visibility: 0.9 },
    ])
  ),
  angles: Object.fromEntries([
    ...ANGLE_DEFINITIONS.map(([name]) => [name, 90]),
    ['upper_back', 170],
    ['lower_back', 160],
  ]),
  comSpeed: 1.5,
});

const samplesFrom = (times) =>
  times.map((mediaTime, i) => ({ mediaTime, result: fakeResult(i) }));

test('rows are contiguous from 0 with no gaps, for both clips', () => {
  for (const fx of [fixture30, fixture60]) {
    const rows = buildRows(samplesFrom(fx.mediaTimes), fx.nominalFps);

    assert.equal(rows[0].frameNum, 0, `${fx.source}: does not start at 0`);
    for (let i = 0; i < rows.length; i++) {
      assert.equal(rows[i].frameNum, i, `${fx.source}: gap or repeat at row ${i}`);
    }
  }
});

test('row count matches duration x fps for both clips', () => {
  for (const fx of [fixture30, fixture60]) {
    const rows = buildRows(samplesFrom(fx.mediaTimes), fx.nominalFps);
    const expected = totalFramesFor(fx.duration, fx.nominalFps);
    assert.ok(
      Math.abs(rows.length - expected) <= 1,
      `${fx.source}: got ${rows.length} rows, expected ~${expected}`
    );
  }
});

test('timestamp equals frame_index / fps to within 1ms', () => {
  for (const fx of [fixture30, fixture60]) {
    const rows = buildRows(samplesFrom(fx.mediaTimes), fx.nominalFps);
    for (const row of rows) {
      const expectedMs = (row.frameNum / fx.nominalFps) * 1000;
      assert.ok(
        Math.abs(row.timestampMs - expectedMs) < 1,
        `${fx.source}: frame ${row.frameNum} timestamp ${row.timestampMs} vs ${expectedMs}`
      );
    }
  }
});

test('timestamps increase strictly', () => {
  const rows = buildRows(samplesFrom(fixture60.mediaTimes), 60);
  for (let i = 1; i < rows.length; i++) {
    assert.ok(rows[i].timestampMs > rows[i - 1].timestampMs, `not increasing at ${i}`);
  }
});

test('duplicate presentation times collapse to one row', () => {
  // Two callbacks for the same frame must not produce two rows, or every row
  // after it is off by one against the player.
  const times = [0, 1 / 30, 1 / 30 + 0.0001, 2 / 30, 3 / 30];
  const rows = buildRows(samplesFrom(times), 30);
  assert.equal(rows.length, 4);
  rows.forEach((r, i) => assert.equal(r.frameNum, i));
});

test('a missing frame is filled rather than left as a gap', () => {
  // SkeletonOverlay indexes the parsed CSV positionally, so a hole would
  // misalign every later frame instead of just losing one.
  const times = [0, 1 / 30, 3 / 30, 4 / 30]; // frame 2 never arrived
  const rows = buildRows(samplesFrom(times), 30);

  assert.equal(rows.length, 5);
  rows.forEach((r, i) => assert.equal(r.frameNum, i));
  assert.equal(rows[2].result, null, 'the hole should be an empty row');
  assert.notEqual(rows[3].result, null);
});

test('out-of-order samples are sorted before indexing', () => {
  const rows = buildRows(samplesFrom([2 / 30, 0, 1 / 30]), 30);
  assert.deepEqual(rows.map((r) => r.frameNum), [0, 1, 2]);
});

test('buildRows on no samples yields no rows', () => {
  assert.deepEqual(buildRows([], 30), []);
});

// ==================== CSV CONTRACT ====================

const LEGACY_HEADER_75 =
  'frame_number,timestamp_ms,speed_center_of_mass,angle_left_elbow,angle_right_elbow,' +
  'angle_left_shoulder,angle_right_shoulder,angle_left_hip,angle_right_hip,angle_left_knee,' +
  'angle_right_knee,angle_left_ankle,angle_right_ankle,angle_upper_back,angle_lower_back,' +
  'landmark_nose_x,landmark_nose_y,landmark_nose_z,landmark_nose_visibility,' +
  'landmark_left_shoulder_x,landmark_left_shoulder_y,landmark_left_shoulder_z,landmark_left_shoulder_visibility,' +
  'landmark_right_shoulder_x,landmark_right_shoulder_y,landmark_right_shoulder_z,landmark_right_shoulder_visibility,' +
  'landmark_left_elbow_x,landmark_left_elbow_y,landmark_left_elbow_z,landmark_left_elbow_visibility,' +
  'landmark_right_elbow_x,landmark_right_elbow_y,landmark_right_elbow_z,landmark_right_elbow_visibility,' +
  'landmark_left_wrist_x,landmark_left_wrist_y,landmark_left_wrist_z,landmark_left_wrist_visibility,' +
  'landmark_right_wrist_x,landmark_right_wrist_y,landmark_right_wrist_z,landmark_right_wrist_visibility,' +
  'landmark_left_hip_x,landmark_left_hip_y,landmark_left_hip_z,landmark_left_hip_visibility,' +
  'landmark_right_hip_x,landmark_right_hip_y,landmark_right_hip_z,landmark_right_hip_visibility,' +
  'landmark_left_knee_x,landmark_left_knee_y,landmark_left_knee_z,landmark_left_knee_visibility,' +
  'landmark_right_knee_x,landmark_right_knee_y,landmark_right_knee_z,landmark_right_knee_visibility,' +
  'landmark_left_ankle_x,landmark_left_ankle_y,landmark_left_ankle_z,landmark_left_ankle_visibility,' +
  'landmark_right_ankle_x,landmark_right_ankle_y,landmark_right_ankle_z,landmark_right_ankle_visibility,' +
  'landmark_left_heel_x,landmark_left_heel_y,landmark_left_heel_z,landmark_left_heel_visibility,' +
  'landmark_right_heel_x,landmark_right_heel_y,landmark_right_heel_z,landmark_right_heel_visibility';

/** The 18 landmarks added by the widening, appended after the original 15. */
const NEW_LANDMARKS_18 = [
  'left_eye_inner', 'left_eye', 'left_eye_outer',
  'right_eye_inner', 'right_eye', 'right_eye_outer',
  'left_ear', 'right_ear', 'mouth_left', 'mouth_right',
  'left_pinky', 'right_pinky', 'left_index', 'right_index',
  'left_thumb', 'right_thumb', 'left_foot_index', 'right_foot_index',
];

const EXPECTED_HEADER =
  LEGACY_HEADER_75 +
  ',' +
  NEW_LANDMARKS_18.flatMap((n) => [
    `landmark_${n}_x`, `landmark_${n}_y`, `landmark_${n}_z`, `landmark_${n}_visibility`,
  ]).join(',');

test('the header is byte-identical to the contract', () => {
  assert.equal(csvHeaders().join(','), EXPECTED_HEADER);
  assert.equal(csvHeaders().length, 147);
});

test('the first 75 columns are exactly the pre-widening contract', () => {
  // The widening must be purely additive. If this fails, a positional reader
  // of the old format silently starts reading the wrong column.
  assert.equal(csvHeaders().slice(0, 75).join(','), LEGACY_HEADER_75);
});

test('all 33 MediaPipe landmarks are present, under canonical names', () => {
  assert.equal(Object.keys(LANDMARK_MAP).length, 33);
  assert.equal(CSV_LANDMARK_ORDER.length, 33);
  assert.equal(new Set(CSV_LANDMARK_ORDER).size, 33, 'duplicate landmark name');

  // MediaPipe's own ordering, index 0..32.
  const canonical = [
    'nose', 'left_eye_inner', 'left_eye', 'left_eye_outer',
    'right_eye_inner', 'right_eye', 'right_eye_outer',
    'left_ear', 'right_ear', 'mouth_left', 'mouth_right',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_pinky', 'right_pinky',
    'left_index', 'right_index', 'left_thumb', 'right_thumb',
    'left_hip', 'right_hip', 'left_knee', 'right_knee',
    'left_ankle', 'right_ankle', 'left_heel', 'right_heel',
    'left_foot_index', 'right_foot_index',
  ];
  for (let i = 0; i < 33; i++) {
    assert.equal(LANDMARK_MAP[i], canonical[i], `index ${i} has the wrong name`);
  }
  // Every canonical name has a column.
  assert.deepEqual([...CSV_LANDMARK_ORDER].sort(), [...canonical].sort());
});

test('the original 15 landmarks keep their exact column names', () => {
  for (const name of LEGACY_LANDMARK_ORDER) {
    for (const axis of ['x', 'y', 'z', 'visibility']) {
      assert.ok(
        csvHeaders().includes(`landmark_${name}_${axis}`),
        `lost column landmark_${name}_${axis}`
      );
    }
  }
  assert.deepEqual(CSV_LANDMARK_ORDER.slice(0, 15), LEGACY_LANDMARK_ORDER);
});

test('every row carries exactly 147 fields', () => {
  const rows = buildRows(samplesFrom(fixture30.mediaTimes.slice(0, 20)), 30);
  const lines = framesToCSV(rows).split('\n');
  for (const [i, line] of lines.entries()) {
    assert.equal(line.split(',').length, 147, `line ${i} has the wrong field count`);
  }
});

test('a pose-less frame is encoded as zero speed and empty columns', () => {
  const rows = [{ frameNum: 7, timestampMs: 233.33, result: null }];
  const fields = framesToCSV(rows).split('\n')[1].split(',');

  assert.equal(fields[0], '7');
  assert.equal(fields[1], '233.33');
  assert.equal(fields[2], '0', 'speed should be 0, not empty');
  for (let i = 3; i < 147; i++) {
    assert.equal(fields[i], '', `column ${i} should be empty`);
  }
});

test('the CSV has no trailing newline and one header line', () => {
  const csv = framesToCSV(buildRows(samplesFrom([0, 1 / 30, 2 / 30]), 30));
  assert.ok(!csv.endsWith('\n'));
  assert.equal(csv.split('\n').length, 4); // header + 3 rows
});

test('no field can contain a comma, so unquoted CSV stays parseable', () => {
  const rows = buildRows(samplesFrom(fixture30.mediaTimes.slice(0, 30)), 30);
  for (const line of framesToCSV(rows).split('\n')) {
    for (const field of line.split(',')) {
      assert.ok(!/["\n\r]/.test(field), `field needs quoting: ${field}`);
    }
  }
});

// ==================== LANDMARK DENORMALIZATION ====================

test('landmarks denormalize against the source resolution, not the canvas', () => {
  // The regression this guards: inference runs on a <=512px canvas, but the CSV
  // stores pixels at the original resolution. Using the canvas size here would
  // shrink every coordinate and misalign the skeleton overlay.
  const raw = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.25, z: 0.1, visibility: 0.8 }));
  const result = computeResult(raw, 1920, 1080, 0, {});

  assert.equal(result.landmarks.nose.x, 960);
  assert.equal(result.landmarks.nose.y, 270);
  assert.equal(result.landmarks.nose.z, 0.1);
  assert.equal(result.landmarks.nose.visibility, 0.8);
});

test('centre-of-mass speed is zero on the first frame and measured after', () => {
  const at = (hipX) => {
    const raw = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.5, z: 0, visibility: 1 }));
    raw[23] = { x: hipX, y: 0.5, z: 0, visibility: 1 };
    raw[24] = { x: hipX, y: 0.5, z: 0, visibility: 1 };
    return raw;
  };

  const first = computeResult(at(0.5), 1000, 1000, 0, {});
  assert.equal(first.comSpeed, 0, 'no previous frame means no speed');

  // Hip midpoint moves 0.1 * 1000px = 100px over 100ms → 1000 px/s.
  const second = computeResult(at(0.6), 1000, 1000, 100, {
    prevCom: first.com,
    prevTimestampMs: 0,
  });
  assert.ok(Math.abs(second.comSpeed - 1000) < 1e-6, `got ${second.comSpeed}`);
});

test('a 60fps clip read as 30fps loses half the frames — the original bug', () => {
  // Pins the failure mode the branch exists to fix.
  const correct = buildRows(samplesFrom(fixture60.mediaTimes), 60);
  const wrong = buildRows(samplesFrom(fixture60.mediaTimes), 30);

  assert.equal(correct.length, 600);
  assert.equal(wrong.length, 300, 'reading 60fps as 30 should halve the rows');
});

// ==================== GOLDEN FILE ====================

const GOLDEN_PATH = join(HERE, 'fixtures', 'golden_pose.csv');
const golden = readFileSync(GOLDEN_PATH, 'utf8');

test('framesToCSV output is byte-identical to the golden file', () => {
  // The whole contract in one assertion. Any change to column order, column
  // names, number formatting or empty-value encoding breaks this.
  // Regenerate deliberately with `npm run make-golden`, and read the diff.
  const produced = framesToCSV(goldenFrames());
  if (produced !== golden) {
    const a = golden.split('\n');
    const b = produced.split('\n');
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      if (a[i] !== b[i]) {
        assert.fail(
          `golden mismatch at line ${i}\n` +
            `  golden:   ${String(a[i]).slice(0, 160)}\n` +
            `  produced: ${String(b[i]).slice(0, 160)}`
        );
      }
    }
  }
  assert.equal(produced, golden);
});

test('the golden file has the shape the contract describes', () => {
  const lines = golden.split('\n');
  assert.equal(lines[0], EXPECTED_HEADER, 'golden header drifted from the contract');
  assert.equal(lines.length, 41, 'expected 40 rows plus a header');
  for (const [i, line] of lines.entries()) {
    assert.equal(line.split(',').length, 147, `golden line ${i} has the wrong width`);
  }
  assert.ok(!golden.endsWith('\n'), 'golden file should have no trailing newline');
});

test('the golden file covers the awkward cases, not just the happy path', () => {
  const rows = golden.split('\n').slice(1).map((l) => l.split(','));

  const poseless = rows.filter((r) => r.slice(3).every((f) => f === ''));
  assert.ok(poseless.length >= 3, 'expected some frames with no pose at all');

  const partial = rows.filter((r) => {
    const tail = r.slice(3);
    return tail.some((f) => f === '') && tail.some((f) => f !== '');
  });
  assert.ok(partial.length >= 1, 'expected a frame with only some landmarks missing');

  assert.ok(
    rows.some((r) => Number(r[2]) > 0),
    'expected a non-zero centre-of-mass speed somewhere'
  );
  assert.equal(rows[0][2], '0', 'the first frame has no previous frame, so speed is 0');
});

test('the golden file still satisfies the frame and timestamp invariants', () => {
  // The widening must not have disturbed the frame/timestamp math.
  const rows = golden.split('\n').slice(1).map((l) => l.split(','));
  const fps = 60;

  rows.forEach((r, i) => {
    assert.equal(Number(r[0]), i, `frame_number should be ${i}`);
    const expectedMs = (i / fps) * 1000;
    assert.ok(
      Math.abs(Number(r[1]) - expectedMs) < 1,
      `frame ${i}: timestamp ${r[1]} vs ${expectedMs}`
    );
  });
});

test('the golden file preserves the pre-widening columns verbatim', () => {
  // Slicing each golden row to its first 75 fields must reproduce exactly what
  // the 15-landmark format produced for the same frames. This is the promise
  // to anything already consuming the old CSV.
  const legacyOnly = framesToCSV(goldenFrames()).split('\n')
    .map((line) => line.split(',').slice(0, 75).join(','));

  assert.equal(legacyOnly[0], LEGACY_HEADER_75);

  const goldenPrefix = golden.split('\n')
    .map((line) => line.split(',').slice(0, 75).join(','));

  assert.deepEqual(legacyOnly, goldenPrefix);
});

// ==================== OUTPUT ROUNDING ====================

test('coordinates are written with at most 4 decimals, visibility at most 3', () => {
  const header = csvHeaders();
  const decimalsOf = (s) => (s.includes('.') ? s.split('.')[1].length : 0);

  for (const line of golden.split('\n').slice(1)) {
    const fields = line.split(',');
    for (let i = 0; i < fields.length; i++) {
      const value = fields[i];
      if (value === '') continue;
      const col = header[i];
      if (!col.startsWith('landmark_')) continue;

      const limit = col.endsWith('_visibility') ? 3 : 4;
      assert.ok(
        decimalsOf(value) <= limit,
        `${col} = ${value} exceeds ${limit} decimals`
      );
      assert.ok(!/e/i.test(value), `${col} = ${value} used exponent notation`);
    }
  }
});

test('rounding happens in the writer, not in the computed result', () => {
  // Angles and centre-of-mass speed are derived from full-precision landmarks,
  // so rounding must not reach back into computeResult.
  const raw = Array.from({ length: 33 }, (_, i) => ({
    x: 0.123456789 + i * 1e-7,
    y: 0.987654321,
    z: 0.5555555555,
    visibility: 0.1234567,
  }));
  const result = computeResult(raw, 1920, 1080, 0, {});

  const x = result.landmarks.nose.x;
  assert.ok(
    String(x).split('.')[1]?.length > 4,
    `in-memory x should keep full precision, got ${x}`
  );
  assert.equal(result.landmarks.nose.visibility, 0.1234567);
});

test('rounding does not introduce -0 or exponent notation', () => {
  const raw = Array.from({ length: 33 }, () => ({
    x: -0.000000001, // rounds to zero from below
    y: 0.00001,      // rounds to zero from above
    z: -0.00004,
    visibility: 0.0004,
  }));
  const frames = [{ frameNum: 0, timestampMs: 0, result: computeResult(raw, 1920, 1080, 0, {}) }];
  const fields = framesToCSV(frames).split('\n')[1].split(',');

  for (let i = 15; i < fields.length; i++) {
    assert.ok(!fields[i].startsWith('-0') || Number(fields[i]) !== 0, `got negative zero: ${fields[i]}`);
    assert.ok(!/e/i.test(fields[i]), `got exponent notation: ${fields[i]}`);
  }
});

// ==================== COORDINATE SPACES / HOLD MATCHING ====================

test('normalizeLandmark divides x and y by the frame, and leaves z alone', () => {
  const lm = { x: 960, y: 270, z: 0.42, visibility: 0.9 };
  const n = normalizeLandmark(lm, 1920, 1080);

  assert.equal(n.x, 0.5);
  assert.equal(n.y, 0.25);
  // z is a MediaPipe depth estimate, never multiplied by a pixel dimension.
  assert.equal(n.z, 0.42, 'z must not be divided by anything');
  assert.equal(n.visibility, 0.9);
});

test('normalization round-trips computeResult back to MediaPipe input', () => {
  const raw = Array.from({ length: 33 }, () => ({ x: 0.3, y: 0.7, z: 0.1, visibility: 1 }));
  const result = computeResult(raw, 1920, 1080, 0, {});
  const n = normalizeLandmarks(result.landmarks, 1920, 1080);

  assert.ok(Math.abs(n.nose.x - 0.3) < 1e-12);
  assert.ok(Math.abs(n.nose.y - 0.7) < 1e-12);
});

test('normalization refuses rather than guesses when the frame size is unknown', () => {
  const lm = { x: 960, y: 270 };
  // A guessed resolution would produce a confident, wrong answer.
  assert.equal(normalizeLandmark(lm, 0, 1080), null);
  assert.equal(normalizeLandmark(lm, 1920, 0), null);
  assert.equal(normalizeLandmark(lm, undefined, undefined), null);
  assert.equal(normalizeLandmark(lm, null, null), null);
  assert.equal(normalizeLandmarks({ nose: lm }, 1920, null), null);
});

test('normalizeLandmarks skips internal keys', () => {
  const n = normalizeLandmarks(
    { nose: { x: 960, y: 540 }, _com: { x: 100, y: 100 } },
    1920, 1080
  );
  assert.deepEqual(Object.keys(n), ['nose']);
});

test('distanceToBox is zero inside and shortest-edge outside', () => {
  const box = { bbox_x: 0.4, bbox_y: 0.4, bbox_w: 0.2, bbox_h: 0.2 }; // 0.4-0.6

  assert.equal(distanceToBox({ x: 0.5, y: 0.5 }, box), 0, 'centre');
  assert.equal(distanceToBox({ x: 0.4, y: 0.4 }, box), 0, 'on the corner');

  // Directly left: horizontal gap only.
  assert.ok(Math.abs(distanceToBox({ x: 0.3, y: 0.5 }, box) - 0.1) < 1e-12);
  // Diagonally off the corner: hypotenuse, not the sum.
  assert.ok(Math.abs(distanceToBox({ x: 0.3, y: 0.3 }, box) - Math.hypot(0.1, 0.1)) < 1e-12);
});

test('isInsideBox agrees with a zero distance', () => {
  const box = { bbox_x: 0.4, bbox_y: 0.4, bbox_w: 0.2, bbox_h: 0.2 };
  for (const p of [{ x: 0.5, y: 0.5 }, { x: 0.4, y: 0.6 }, { x: 0.3, y: 0.5 }, { x: 0.7, y: 0.7 }]) {
    assert.equal(isInsideBox(p, box), distanceToBox(p, box) === 0, JSON.stringify(p));
  }
});

test('nearestHold normalizes the landmark before comparing — the whole point', () => {
  // A wrist at pixel (960, 540) on a 1920x1080 frame is the centre of the
  // frame, and should land inside a box covering the centre.
  const wrist = { x: 960, y: 540 };
  const holds = [
    { bbox_x: 0.0, bbox_y: 0.0, bbox_w: 0.1, bbox_h: 0.1 }, // top-left corner
    { bbox_x: 0.45, bbox_y: 0.45, bbox_w: 0.1, bbox_h: 0.1 }, // centre
  ];

  const hit = nearestHold(wrist, holds, 1920, 1080);
  assert.equal(hit.index, 1, 'should match the centre hold');
  assert.equal(hit.inside, true);
  assert.equal(hit.distance, 0);
});

test('skipping normalization would pick the wrong hold — the bug being prevented', () => {
  // Comparing raw pixels against normalized boxes makes every box look ~200+
  // units away, and the ranking collapses to "whichever box extends furthest
  // right and down", since that shrinks the pixel gap fractionally. A hold the
  // hand is literally inside then loses to one on the far side of the wall.
  const hand = { x: 192, y: 108 }; // normalized (0.1, 0.1) on 1920x1080
  const holds = [
    { bbox_x: 0.05, bbox_y: 0.05, bbox_w: 0.1, bbox_h: 0.1 }, // contains the hand
    { bbox_x: 0.8, bbox_y: 0.8, bbox_w: 0.15, bbox_h: 0.15 }, // opposite corner
  ];

  const correct = nearestHold(hand, holds, 1920, 1080);
  assert.equal(correct.index, 0, 'the hand is inside hold 0');
  assert.equal(correct.inside, true);

  const naive = holds
    .map((h, index) => ({ index, distance: distanceToBox(hand, h) }))
    .sort((a, b) => a.distance - b.distance)[0];

  assert.equal(naive.index, 1, 'unnormalized comparison picks the far corner');
  assert.ok(naive.distance > 100, `absurd distance, got ${naive.distance}`);
  assert.notEqual(naive.index, correct.index, 'the two must disagree');
});

test('nearestHold respects maxDistance in normalized units', () => {
  const wrist = { x: 960, y: 540 }; // normalized 0.5, 0.5
  const holds = [{ bbox_x: 0.9, bbox_y: 0.9, bbox_w: 0.05, bbox_h: 0.05 }];

  assert.equal(nearestHold(wrist, holds, 1920, 1080, { maxDistance: 0.1 }), null);
  assert.ok(nearestHold(wrist, holds, 1920, 1080, { maxDistance: 0.9 }));
});

test('nearestHold returns null on unknown frame size or no holds', () => {
  const wrist = { x: 960, y: 540 };
  const holds = [{ bbox_x: 0.4, bbox_y: 0.4, bbox_w: 0.2, bbox_h: 0.2 }];

  assert.equal(nearestHold(wrist, holds, null, null), null, 'unknown frame size');
  assert.equal(nearestHold(wrist, [], 1920, 1080), null, 'no holds');
  assert.equal(nearestHold(null, holds, 1920, 1080), null, 'no landmark');
});

test('nearestHoldsFor matches each contact landmark independently', () => {
  const landmarks = {
    left_index: { x: 192, y: 108 },   // normalized 0.1, 0.1
    right_index: { x: 1728, y: 972 }, // normalized 0.9, 0.9
  };
  const holds = [
    { bbox_x: 0.05, bbox_y: 0.05, bbox_w: 0.1, bbox_h: 0.1 },
    { bbox_x: 0.85, bbox_y: 0.85, bbox_w: 0.1, bbox_h: 0.1 },
  ];

  const matched = nearestHoldsFor(landmarks, CONTACT_LANDMARKS, holds, 1920, 1080);
  assert.equal(matched.left_index.index, 0);
  assert.equal(matched.right_index.index, 1);
  // Absent landmarks yield null rather than throwing.
  assert.equal(matched.left_foot_index, null);
});

test('the contact landmarks exist in the 33-landmark set', () => {
  for (const name of CONTACT_LANDMARKS) {
    assert.ok(CSV_LANDMARK_ORDER.includes(name), `${name} is not a stored landmark`);
    // And none of them existed in the old 15-landmark format.
    assert.ok(!LEGACY_LANDMARK_ORDER.includes(name), `${name} unexpectedly legacy`);
  }
});

// ==================== HOLD SUGGESTIONS ====================

const W = 1920;
const H = 1080;

/** A parsed-CSV-style row: string values, pixel coordinates. */
function rowWith(points) {
  const row = { frame_number: '0', timestamp_ms: '0' };
  for (const name of CSV_LANDMARK_ORDER) {
    const p = points[name];
    row[`landmark_${name}_x`] = p ? String(p.x) : '';
    row[`landmark_${name}_y`] = p ? String(p.y) : '';
    row[`landmark_${name}_z`] = p ? '0' : '';
    row[`landmark_${name}_visibility`] = p ? String(p.visibility ?? 0.9) : '';
  }
  return row;
}

/** Normalized centre of a box, in pixels. */
const centrePx = (box) => ({
  x: (box.bbox_x + box.bbox_w / 2) * W,
  y: (box.bbox_y + box.bbox_h / 2) * H,
});

const HOLD_A = { id: 11, bbox_x: 0.10, bbox_y: 0.20, bbox_w: 0.08, bbox_h: 0.08 };
const HOLD_B = { id: 22, bbox_x: 0.70, bbox_y: 0.25, bbox_w: 0.08, bbox_h: 0.08 };
const HOLD_C = { id: 33, bbox_x: 0.30, bbox_y: 0.80, bbox_w: 0.08, bbox_h: 0.08 };

test('landmarkFromRow parses pixels and rejects empty columns', () => {
  const row = rowWith({ left_index: { x: 123.5, y: 456.25, visibility: 0.8 } });

  const lm = landmarkFromRow(row, 'left_index');
  assert.equal(lm.x, 123.5);
  assert.equal(lm.y, 456.25);
  assert.equal(lm.visibility, 0.8);

  // A pose-less column is empty string, not 0 — Number('') is 0, which would
  // silently place the limb at the frame's top-left corner.
  assert.equal(landmarkFromRow(row, 'right_index'), null);
  assert.equal(landmarkFromRow(null, 'left_index'), null);
});

test('contactLandmarksFromRow returns only the present contact points', () => {
  const row = rowWith({
    left_index: centrePx(HOLD_A),
    right_foot_index: centrePx(HOLD_C),
  });
  assert.deepEqual(
    Object.keys(contactLandmarksFromRow(row)).sort(),
    ['left_index', 'right_foot_index']
  );
});

test('suggests the hold each limb is inside', () => {
  const row = rowWith({
    left_index: centrePx(HOLD_A),
    right_index: centrePx(HOLD_B),
    right_foot_index: centrePx(HOLD_C),
  });

  const { available, contacts } = suggestHoldsForFrame(row, [HOLD_A, HOLD_B, HOLD_C], W, H);
  assert.equal(available, true);
  assert.equal(contacts.length, 3);

  const byName = Object.fromEntries(contacts.map((c) => [c.name, c]));
  assert.equal(byName.left_index.hold.id, 11);
  assert.equal(byName.right_index.hold.id, 22);
  assert.equal(byName.right_foot_index.hold.id, 33);
  for (const c of contacts) {
    assert.equal(c.inside, true, `${c.name} should read as inside`);
    assert.equal(c.distance, 0);
  }
});

test('suggestions map limbs to the backend BODY_PARTS taxonomy', () => {
  // BODY_PARTS has no fingertip or toe, so contacts must degrade to the wrist
  // and ankle a tag can actually carry.
  assert.equal(CONTACT_META.left_index.bodyPart, 'left_wrist');
  assert.equal(CONTACT_META.right_index.bodyPart, 'right_wrist');
  assert.equal(CONTACT_META.left_foot_index.bodyPart, 'left_ankle');
  assert.equal(CONTACT_META.right_foot_index.bodyPart, 'right_ankle');

  const row = rowWith({ left_index: centrePx(HOLD_A), left_foot_index: centrePx(HOLD_C) });
  const { contacts } = suggestHoldsForFrame(row, [HOLD_A, HOLD_C], W, H);

  assert.deepEqual(bodyPartsFor(contacts).sort(), ['left_ankle', 'left_wrist']);
  assert.equal(sideFor(contacts), 'left', 'both contacts are left');
});

test('sideFor refuses to pick when the contacts disagree', () => {
  const row = rowWith({ left_index: centrePx(HOLD_A), right_index: centrePx(HOLD_B) });
  const { contacts } = suggestHoldsForFrame(row, [HOLD_A, HOLD_B], W, H);
  // A frame tag carries one side; mixed contacts must leave it to the labeller.
  assert.equal(sideFor(contacts), null);
});

test('a limb beyond the threshold is not suggested', () => {
  const far = { x: 0.5 * W, y: 0.5 * H }; // middle of the frame, no hold there
  const row = rowWith({ left_index: centrePx(HOLD_A), right_index: far });

  const { contacts } = suggestHoldsForFrame(row, [HOLD_A, HOLD_B, HOLD_C], W, H);
  assert.deepEqual(contacts.map((c) => c.name), ['left_index']);
});

test('a limb just outside a hold is suggested as near, not inside', () => {
  // Half the threshold beyond the box's left edge.
  const justOutside = {
    x: (HOLD_A.bbox_x - CONTACT_THRESHOLD / 2) * W,
    y: (HOLD_A.bbox_y + HOLD_A.bbox_h / 2) * H,
  };
  const row = rowWith({ left_index: justOutside });

  const { contacts } = suggestHoldsForFrame(row, [HOLD_A], W, H);
  assert.equal(contacts.length, 1);
  assert.equal(contacts[0].inside, false);
  assert.ok(contacts[0].distance > 0 && contacts[0].distance <= CONTACT_THRESHOLD);
});

test('low-visibility limbs are ignored', () => {
  // An occluded hand sitting exactly on a hold should not produce a confident
  // suggestion.
  const row = rowWith({
    left_index: { ...centrePx(HOLD_A), visibility: 0.1 },
    right_index: { ...centrePx(HOLD_B), visibility: 0.95 },
  });

  const { contacts } = suggestHoldsForFrame(row, [HOLD_A, HOLD_B], W, H);
  assert.deepEqual(contacts.map((c) => c.name), ['right_index']);
});

test('contacts are ordered surest first', () => {
  const nearB = {
    x: (HOLD_B.bbox_x - CONTACT_THRESHOLD / 2) * W,
    y: (HOLD_B.bbox_y + HOLD_B.bbox_h / 2) * H,
  };
  const row = rowWith({ right_index: nearB, left_index: centrePx(HOLD_A) });

  const { contacts } = suggestHoldsForFrame(row, [HOLD_A, HOLD_B], W, H);
  assert.equal(contacts[0].name, 'left_index', 'the inside match should lead');
  assert.ok(contacts[0].distance <= contacts[1].distance);
});

test('every unavailable case reports a distinguishable reason', () => {
  const row = rowWith({ left_index: centrePx(HOLD_A) });
  const empty = rowWith({});

  assert.equal(suggestHoldsForFrame(row, [], W, H).reason, 'no-holds');
  assert.equal(suggestHoldsForFrame(row, [HOLD_A], null, null).reason, 'no-dimensions');
  assert.equal(suggestHoldsForFrame(empty, [HOLD_A], W, H).reason, 'no-pose');

  const far = rowWith({ left_index: { x: 0.5 * W, y: 0.5 * H } });
  assert.equal(suggestHoldsForFrame(far, [HOLD_A], W, H).reason, 'no-contact');

  for (const r of [[], [HOLD_A]]) {
    assert.equal(suggestHoldsForFrame(row, r, W, H).contacts.length >= 0, true);
  }
});

test('unknown frame size never guesses a suggestion', () => {
  // The video record predates the dimensions migration. Guessing 1920x1080
  // would produce confident, unverifiable matches.
  const row = rowWith({ left_index: centrePx(HOLD_A) });
  const result = suggestHoldsForFrame(row, [HOLD_A], undefined, undefined);

  assert.equal(result.available, false);
  assert.equal(result.reason, 'no-dimensions');
  assert.deepEqual(result.contacts, []);
});

test('suggestions scale with resolution rather than assuming one', () => {
  // The same climber on the same wall, filmed at two resolutions, must yield
  // the same hold. This only works because the landmarks are normalized.
  for (const [w, h] of [[1920, 1080], [3840, 2160], [720, 1280]]) {
    const row = rowWith({
      left_index: { x: (HOLD_A.bbox_x + HOLD_A.bbox_w / 2) * w, y: (HOLD_A.bbox_y + HOLD_A.bbox_h / 2) * h },
    });
    const { contacts } = suggestHoldsForFrame(row, [HOLD_A, HOLD_B, HOLD_C], w, h);
    assert.equal(contacts[0]?.hold.id, 11, `failed at ${w}x${h}`);
    assert.equal(contacts[0].inside, true);
  }
});

test('a pose-less frame produces no phantom limb at the origin', () => {
  // Regression: Number('') is 0 and Number.isFinite(0) is true, so parsing an
  // empty column directly put every limb at (0,0) — which then matched any
  // hold near the frame's top-left corner with full confidence.
  const originHold = { id: 99, bbox_x: 0, bbox_y: 0, bbox_w: 0.1, bbox_h: 0.1 };
  const poseless = rowWith({});

  assert.equal(landmarkFromRow(poseless, 'left_index'), null);
  assert.deepEqual(contactLandmarksFromRow(poseless), {});

  const result = suggestHoldsForFrame(poseless, [originHold], W, H);
  assert.equal(result.available, false);
  assert.equal(result.reason, 'no-pose');
  assert.deepEqual(result.contacts, []);
});
