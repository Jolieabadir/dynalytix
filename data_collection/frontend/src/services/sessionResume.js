/**
 * Rebuilding a labeling session from the server after the page dies.
 *
 * iOS Safari evicts backgrounded pages. When it does, React state, the
 * Zustand store and the object URL of the picked file all go with it — so the
 * store cannot be the source of truth for anything a labeler would be upset
 * to lose. It isn't: every move, environment, outcome, frame tag and hold is
 * POSTed the instant it is made, and lives in Postgres.
 *
 * What the browser still has to remember across an eviction is only which
 * video was open. That is one small pointer, kept in localStorage, and
 * everything else is re-fetched from the API on the next load.
 *
 * What cannot come back is the local `File`: a browser may not hold one
 * across a page load. The video therefore returns as its presigned R2 URL,
 * which is also why confirm-upload matters — an evicted session before the
 * upload finishes resumes the upload instead (see services/resumableUpload).
 */
import { getVideo, getHolds, getMoves, getVideoPlaybackUrl } from '../api/client';

const KEY = 'dynalytix.session';

/**
 * Remember what is open. Called whenever the open video or view changes.
 * @param {{videoId: number, view: string, assignmentId?: number|null}|null} snapshot
 */
export function rememberSession(snapshot) {
  try {
    if (!snapshot || !snapshot.videoId) {
      localStorage.removeItem(KEY);
      return;
    }
    localStorage.setItem(
      KEY,
      JSON.stringify({
        videoId: snapshot.videoId,
        view: snapshot.view,
        assignmentId: snapshot.assignmentId ?? null,
        savedAt: Date.now(),
      })
    );
  } catch {
    // Private mode: the labeler loses only the auto-reopen, not any labels.
  }
}

/** Anything remembered? Null when there is nothing to resume. */
export function readSession() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && parsed.videoId ? parsed : null;
  } catch {
    return null;
  }
}

export function forgetSession() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // Nothing to do.
  }
}

/**
 * Re-fetch everything the open video needs.
 *
 * Each piece is best-effort in the same way App's admin "open for prep" path
 * is: a missing original still leaves the moves and labels usable, and a
 * video that has since been closed or unassigned simply fails to load, which
 * is the correct outcome — the server decides what this user may see, not the
 * remembered pointer.
 *
 * @returns {Promise<{video: object, holds: Array, moves: Array, playbackUrl: string|null}|null>}
 */
export async function restoreSession(session) {
  if (!session?.videoId) return null;

  let video;
  try {
    video = await getVideo(session.videoId);
  } catch {
    // 404/403: it is not ours any more. Stop offering to resume it.
    forgetSession();
    return null;
  }
  if (!video) {
    forgetSession();
    return null;
  }

  const [holds, moves, playbackUrl] = await Promise.all([
    getHolds(session.videoId).catch(() => []),
    getMoves(session.videoId).catch(() => []),
    getVideoPlaybackUrl(session.videoId).catch(() => null),
  ]);

  return { video, holds: holds ?? [], moves: moves ?? [], playbackUrl: playbackUrl ?? null };
}
