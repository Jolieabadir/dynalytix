/**
 * Tests for the detect-timestamp clock that feeds MediaPipe.
 *
 * Run: node --test scripts/test_pose_extractor.mjs
 *
 * Background: PoseLandmarker in VIDEO mode requires strictly increasing
 * timestamps per instance, for that instance's whole lifetime, and ours is a
 * module singleton shared by every extraction on the page. The clock therefore
 * has to outlive any one PoseExtractor. It previously did not — it was a field
 * on the instance, reset to -1 at the top of every run — so the second upload
 * of a session replayed timestamps from 0 and MediaPipe rejected the packet:
 *
 *   Packet timestamp mismatch on stream norm_rect ... received 0
 *
 * The other half of the contract is that this clock stays internal. The CSV's
 * timestamp_ms is frame_number / fps and must restart at 0 for every video, so
 * the tests below assert both halves together: internal timestamps that never
 * repeat, over exported timestamps that do.
 *
 * What this canNOT cover: MediaPipe itself, the capture loop, and the
 * recreate-and-retry path, all of which need a real browser.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  beginDetectRun,
  nextDetectTimestamp,
  _resetDetectClock,
  _detectClockValue,
  isInvalidArgumentError,
} from '../src/services/PoseExtractor.js';
import { buildRows } from '../src/services/poseMath.js';

/** Presentation times for `count` frames at `fps`, in seconds, starting at 0. */
const mediaTimes = (fps, count) =>
  Array.from({ length: count }, (_, i) => i / fps);

/** Walk one extraction's worth of frames through the clock. */
const runExtraction = (times) => {
  const base = beginDetectRun();
  return times.map((t) => nextDetectTimestamp(base, t * 1000));
};

const strictlyIncreasing = (values) =>
  values.every((v, i) => i === 0 || v > values[i - 1]);

test('a single run issues strictly increasing timestamps', () => {
  _resetDetectClock();
  const issued = runExtraction(mediaTimes(30, 90));

  assert.equal(issued.length, 90);
  assert.ok(strictlyIncreasing(issued), 'timestamps must strictly increase');
  assert.ok(issued.every(Number.isInteger), 'MediaPipe wants whole milliseconds');
});

test('a second run starting at mediaTime 0 never replays a timestamp', () => {
  // The exact regression. Both clips start at mediaTime 0; the singleton
  // landmarker sees one continuous stream and must never be handed 0 twice.
  _resetDetectClock();

  const first = runExtraction(mediaTimes(30, 60));
  const second = runExtraction(mediaTimes(30, 60));

  assert.equal(second[0] > first[first.length - 1], true,
    'the second run must open above the first run\'s last timestamp');
  assert.ok(strictlyIncreasing([...first, ...second]),
    'the singleton sees one stream: it must increase across the run boundary');
  assert.equal(new Set([...first, ...second]).size, 120, 'no timestamp repeats');

  // And a third, to be sure the base is not merely "one run's worth" ahead.
  const third = runExtraction(mediaTimes(60, 120));
  assert.ok(strictlyIncreasing([...first, ...second, ...third]));
});

test('the internal clock does not leak into the exported timestamps', () => {
  _resetDetectClock();

  const fps = 30;
  const times = mediaTimes(fps, 60);

  runExtraction(times);                      // first video of the session
  const internal = runExtraction(times);     // second video, same media times

  // Internal: well past zero, because a previous clip already ran.
  assert.ok(internal[0] > 0, 'internal clock carries over between runs');
  assert.ok(_detectClockValue() > 0);

  // Exported: derived from frame_number / fps, so it restarts at 0 every time.
  const rows = buildRows(times.map((mediaTime) => ({ mediaTime, result: null })), fps);
  assert.equal(rows[0].timestampMs, 0, 'CSV timestamps restart at 0 per video');
  assert.equal(rows[1].timestampMs, 1000 / fps);
  assert.equal(rows[rows.length - 1].timestampMs, ((rows.length - 1) / fps) * 1000);

  // The two must not be the same numbers.
  assert.notEqual(rows[0].timestampMs, internal[0]);
});

test('a duplicate frame callback is bumped rather than repeated', () => {
  // requestVideoFrameCallback re-presents the same mediaTime after a
  // pause/resume. base + mediaTime alone would hand MediaPipe that timestamp
  // twice, which it rejects.
  _resetDetectClock();
  const base = beginDetectRun();

  const first = nextDetectTimestamp(base, 1000);
  const duplicate = nextDetectTimestamp(base, 1000);
  const triplicate = nextDetectTimestamp(base, 1000);

  assert.equal(duplicate, first + 1);
  assert.equal(triplicate, first + 2);
  assert.ok(strictlyIncreasing([first, duplicate, triplicate]));
});

test('a backwards seek still moves the clock forwards', () => {
  // Rewinding media time must not rewind the packet stream.
  _resetDetectClock();
  const base = beginDetectRun();

  const ahead = nextDetectTimestamp(base, 5000);
  const behind = nextDetectTimestamp(base, 2000);

  assert.ok(behind > ahead, 'a backwards mediaTime must still increase the clock');
  assert.equal(behind, ahead + 1);
});

test('sub-millisecond frame spacing never collides', () => {
  // 120fps is 8.33ms apart, but rounding two near-identical times could still
  // collide; the clamp has to catch it.
  _resetDetectClock();
  const base = beginDetectRun();

  const issued = [0, 0.0004, 0.0009, 0.001, 0.0012].map((t) =>
    nextDetectTimestamp(base, t * 1000)
  );

  assert.ok(strictlyIncreasing(issued), issued.join(','));
});

test('only packet-rejection errors trigger a landmarker rebuild', () => {
  // This predicate is the gate on the recreate-and-retry path. Too narrow and
  // one bad packet still kills the run; too wide and a genuine inference
  // failure costs a full model reload on every frame.
  const rebuilds = [
    new Error('INVALID_ARGUMENT: Packet timestamp mismatch on stream norm_rect'),
    new Error('Packet timestamp mismatch on stream norm_rect. Timestamp: 0, received 0'),
    new Error('timestamp mismatch'),
    'INVALID_ARGUMENT',
  ];
  for (const error of rebuilds) {
    assert.equal(isInvalidArgumentError(error), true, String(error));
  }

  const rethrows = [
    new Error('Failed to fetch model'),
    new Error('RuntimeError: memory access out of bounds'),
    new TypeError('canvas is not a valid image source'),
    null,
    undefined,
  ];
  for (const error of rethrows) {
    assert.equal(isInvalidArgumentError(error), false, String(error));
  }
});
