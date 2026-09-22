/**
 * Follow the server-side pose job for the current video.
 *
 * Polls GET /api/videos/{id}/status every POLL_INTERVAL_MS while the job is
 * pending or processing, and stops on done/failed. On done it:
 *
 *   1. copies the worker's MEASURED metadata (fps, total_frames, duration_ms,
 *      width, height) onto currentVideo — the values register sent were
 *      provisional, fps in particular defaulted to 30;
 *   2. if fps actually changed, rescales frame numbers that were computed
 *      against the provisional rate: the moves already saved (their
 *      timestamp_ms is authoritative, so frame = round(ms / 1000 * fps)), the
 *      current [ ] selection, and the play head;
 *   3. fetches the pose CSV from its presigned URL and parses it into the
 *      store, which is what turns the skeleton overlay and hold suggestions on.
 *
 * Everything is keyed by video id, so switching videos restarts cleanly, and
 * a stale response for a previous video is dropped.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import useStore from '../store/useStore';
import { getPoseStatus, retryPose, fetchPoseCsvText, updateMove } from '../api/client';
import { parseCsv } from '../utils/csv';
import { timeToFrame } from '../utils/frames';

export const POLL_INTERVAL_MS = 5000;

/** States the poll keeps running for. */
const ACTIVE = new Set(['pending', 'processing']);

/** The worker's measured columns, copied onto the video when it finishes. */
const MEASURED = ['fps', 'total_frames', 'duration_ms', 'width', 'height'];

/**
 * Rescale a frame number from one fps to another via its time.
 * @param {number} frame
 * @param {number} fromFps
 * @param {number} toFps
 */
export function rescaleFrame(frame, fromFps, toFps) {
  if (!(fromFps > 0) || !(toFps > 0) || fromFps === toFps) return frame;
  return Math.round((frame / fromFps) * toFps);
}

/**
 * Moves whose frame numbers disagree with their timestamps at `fps`, with the
 * corrected fields. Pure, so it is testable without the store.
 * @param {Array<object>} moves
 * @param {number} fps
 */
export function movesToRescale(moves, fps) {
  if (!(fps > 0)) return [];
  const out = [];
  for (const move of moves || []) {
    const frame_start = timeToFrame(move.timestamp_start_ms / 1000, fps);
    const frame_end = timeToFrame(move.timestamp_end_ms / 1000, fps);
    if (frame_start !== move.frame_start || frame_end !== move.frame_end) {
      out.push({ move, fields: { frame_start, frame_end } });
    }
  }
  return out;
}

export default function usePoseStatus() {
  const currentVideo = useStore((s) => s.currentVideo);
  const poseStatus = useStore((s) => s.poseStatus);
  const setPoseStatus = useStore((s) => s.setPoseStatus);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState(null);
  // Bumped by retry() so the poll loop below restarts after a failed job.
  const [pollGeneration, setPollGeneration] = useState(0);

  const videoId = currentVideo?.id ?? null;
  const status = poseStatus?.video_id === videoId ? poseStatus : null;
  const state = status?.pose_status ?? (videoId ? 'pending' : null);

  // The id whose 'done' we have already applied, so a re-render never
  // re-fetches the CSV or rescales twice.
  const appliedDoneFor = useRef(null);

  const applyDone = useCallback(
    async (result) => {
      if (appliedDoneFor.current === result.video_id) return;
      appliedDoneFor.current = result.video_id;

      const store = useStore.getState();
      const video = store.currentVideo;
      if (!video || video.id !== result.video_id) return;

      const previousFps = video.fps;
      const patch = { pose_status: 'done', r2_pose_csv_key: result.r2_pose_csv_key };
      for (const key of MEASURED) {
        if (result[key] !== null && result[key] !== undefined) patch[key] = result[key];
      }
      store.patchCurrentVideo(patch);

      const fps = patch.fps ?? previousFps;
      if (fps !== previousFps) {
        // Provisional-rate frame numbers are wrong by the ratio; fix them.
        const { moveStart, moveEnd, currentFrame } = useStore.getState();
        useStore.setState({
          moveStart: moveStart === null ? null : rescaleFrame(moveStart, previousFps, fps),
          moveEnd: moveEnd === null ? null : rescaleFrame(moveEnd, previousFps, fps),
          currentFrame: rescaleFrame(currentFrame, previousFps, fps),
        });
        for (const { move, fields } of movesToRescale(useStore.getState().moves, fps)) {
          try {
            const updated = await updateMove(move.id, fields);
            useStore.getState().updateMoveInList(move.id, { ...move, ...updated });
          } catch (err) {
            console.warn(`[usePoseStatus] could not rescale move ${move.id}:`, err);
          }
        }
      }

      try {
        const text = await fetchPoseCsvText(result.video_id);
        if (useStore.getState().currentVideo?.id === result.video_id) {
          store.setCsvData(parseCsv(text));
        }
      } catch (err) {
        console.error('[usePoseStatus] pose CSV load failed:', err);
        setError(err?.message || 'Could not load the pose data.');
      }
    },
    []
  );

  useEffect(() => {
    if (!videoId) return undefined;
    let active = true;
    let timer = null;

    const tick = async () => {
      try {
        const result = await getPoseStatus(videoId);
        if (!active) return;
        setError(null);
        setPoseStatus(result);
        if (result.pose_status === 'done') {
          await applyDone(result);
          return;
        }
        if (ACTIVE.has(result.pose_status)) {
          timer = setTimeout(tick, POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (!active) return;
        // A transient failure is not a failed job; keep polling.
        setError(err?.response?.data?.detail || err?.message || 'Status check failed.');
        timer = setTimeout(tick, POLL_INTERVAL_MS);
      }
    };

    // Only poll while there is something to wait for. A video that arrives
    // already done (a reload) still needs its CSV loaded, which the first tick
    // handles too.
    if (state === 'done' && appliedDoneFor.current === videoId) return undefined;
    tick();

    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
    // `state` is deliberately not a dependency: the tick loop reads the
    // server's answer directly, and re-running on every poll would double up.
    // It restarts when the video changes or after a retry bumps pollGeneration.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId, pollGeneration, applyDone, setPoseStatus]);

  const retry = useCallback(async () => {
    if (!videoId) return;
    setRetrying(true);
    setError(null);
    try {
      const result = await retryPose(videoId);
      setPoseStatus(result);
      setPollGeneration((n) => n + 1);
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Retry failed.');
    } finally {
      setRetrying(false);
    }
  }, [videoId, setPoseStatus]);

  return {
    /** 'pending' | 'processing' | 'done' | 'failed' | null (no video) */
    state,
    /** The last /status payload for this video, or null. */
    status,
    /** pose_error from the server, when failed. */
    poseError: status?.pose_error ?? null,
    /** A client-side problem (poll or CSV load), or null. */
    error,
    isDone: state === 'done',
    retry,
    retrying,
  };
}
