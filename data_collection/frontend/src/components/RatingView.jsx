/**
 * RatingView — one assignment, rated by one rater (Dataset A).
 *
 * The existing labeling layout with the structure frozen: the player scrubs
 * and shows the canonical holds; the side column lists the canonical moves;
 * picking one opens RaterMoveForm (Strategy read-only, Environment + Outcome
 * the rater's own); "Tag Frames" is the same TaggingMode, minus export.
 *
 * "Complete" posts to /complete. A 422 comes back with the moves that still
 * lack a lens and is rendered inline; a 200 marks the assignment done and the
 * whole view goes read-only.
 *
 * Everything here is loaded fresh per assignment and dropped on exit
 * (store.resetVideoState), so no labels are ever carried between videos.
 */
import { useCallback, useEffect, useState } from 'react';
import useStore from '../store/useStore';
import {
  getVideo,
  getHolds,
  getMoves,
  getVideoCsvText,
  getVideoPlaybackUrl,
  getEnvironmentForMove,
  getOutcomeForMove,
  startAssignment,
  completeAssignment,
} from '../api/client';
import VideoPlayer from './VideoPlayer';
import MovesList from './MovesList';
import RaterMoveForm from './RaterMoveForm';
import TaggingMode from './TaggingMode';
import { parsePoseCsv } from '../utils/csv';

const STATUS_LABEL = {
  assigned: 'Not started',
  in_progress: 'In progress',
  done: 'Done',
};

function RatingView({ onExit }) {
  const {
    currentVideo,
    setCurrentVideo,
    currentAssignment,
    setCurrentAssignment,
    assignments,
    setAssignments,
    moves,
    setMoves,
    setHolds,
    setCsvData,
    setVideoPlaybackUrl,
    setReadOnlyStructure,
    mode,
    setMode,
    setCurrentMove,
    setHoldPickSlot,
    config,
  } = useStore();

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [selectedMoveId, setSelectedMoveId] = useState(null);
  const [labelStatus, setLabelStatus] = useState({});
  const [completing, setCompleting] = useState(false);
  const [completeError, setCompleteError] = useState(null);
  const [missing, setMissing] = useState(null);

  const assignmentId = currentAssignment?.id;
  const videoId = currentAssignment?.video_id;

  const locked =
    currentAssignment?.status === 'done' || currentVideo?.prep_status === 'closed';

  /** This rater's environment/outcome presence per move. */
  const refreshLabelStatus = useCallback(async (moveList) => {
    const entries = await Promise.all(
      moveList.map(async (m) => {
        const [env, outcome] = await Promise.all([
          getEnvironmentForMove(m.id),
          getOutcomeForMove(m.id),
        ]);
        return [m.id, { environment: Boolean(env), outcome: Boolean(outcome) }];
      })
    );
    setLabelStatus(Object.fromEntries(entries));
  }, []);

  // Load everything for this assignment. Holds and moves are the canonical
  // set the API returns to a rater; labels are the rater's own.
  useEffect(() => {
    if (!assignmentId || !videoId) return;
    let active = true;
    setLoading(true);
    setLoadError(null);
    setReadOnlyStructure(true);
    setMode('define');
    setSelectedMoveId(null);

    (async () => {
      try {
        const [video, holds, moveList, playbackUrl] = await Promise.all([
          getVideo(videoId),
          getHolds(videoId),
          getMoves(videoId),
          getVideoPlaybackUrl(videoId).catch((err) => {
            console.warn('[RatingView] No playback URL:', err);
            return null;
          }),
        ]);
        if (!active) return;
        setCurrentVideo(video);
        setHolds(holds);
        setMoves(moveList);
        setVideoPlaybackUrl(playbackUrl);

        // Pose rows: needed by the hold suggestions. Best-effort.
        try {
          const text = await getVideoCsvText(videoId);
          if (active) setCsvData(parsePoseCsv(text));
        } catch (err) {
          console.warn('[RatingView] Pose CSV unavailable; suggestions disabled.', err);
          if (active) setCsvData([]);
        }

        await refreshLabelStatus(moveList);

        // Opening the assignment starts it (idempotent; 403 once done, which
        // is fine — the status is already what we show).
        if (currentAssignment?.status === 'assigned') {
          try {
            const started = await startAssignment(assignmentId);
            if (active) setCurrentAssignment(started);
          } catch (err) {
            console.warn('[RatingView] Could not mark the assignment started:', err);
          }
        }
      } catch (err) {
        console.error('[RatingView] Load failed:', err);
        if (active) {
          setLoadError(
            err.response?.status === 404
              ? 'This video is no longer assigned to you.'
              : err.response?.data?.detail || err.message || 'Could not load this assignment.'
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
    // Intentionally keyed on the assignment/video only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignmentId, videoId]);

  const handleSelectMove = (move) => {
    setHoldPickSlot(null);
    setSelectedMoveId(move.id);
    setCurrentMove(move);
  };

  const handleCloseForm = () => {
    setSelectedMoveId(null);
    setHoldPickSlot(null);
  };

  const handleSaved = (moveId, status) => {
    setLabelStatus((prev) => ({ ...prev, [moveId]: status }));
    // A saved lens may clear an entry from the last 422 list.
    setMissing((prev) => (prev ? prev.filter((m) => m.move_id !== moveId) : prev));
  };

  const handleComplete = async () => {
    setCompleting(true);
    setCompleteError(null);
    setMissing(null);
    try {
      const outcome = await completeAssignment(assignmentId);
      if (outcome.incomplete) {
        setMissing(outcome.missing);
        setCompleteError(outcome.detail || 'Some moves are incomplete.');
        return;
      }
      setCurrentAssignment(outcome.assignment);
      setAssignments(
        assignments.map((item) =>
          item.assignment?.id === outcome.assignment.id
            ? { ...item, assignment: outcome.assignment }
            : item
        )
      );
      setSelectedMoveId(null);
      setHoldPickSlot(null);
    } catch (err) {
      console.error('[RatingView] Complete failed:', err);
      setCompleteError(err.response?.data?.detail || err.message || 'Could not complete the assignment.');
    } finally {
      setCompleting(false);
    }
  };

  if (!currentAssignment) {
    return (
      <div className="rating-view">
        <p>No assignment selected.</p>
        <button type="button" className="btn-secondary" onClick={onExit}>
          Back to My queue
        </button>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="rating-view">
        <div className="error-message">{loadError}</div>
        <button type="button" className="btn-secondary" onClick={onExit}>
          Back to My queue
        </button>
      </div>
    );
  }

  if (loading || !currentVideo || !config) {
    return (
      <div className="rating-view loading">
        <h2>Loading assignment…</h2>
      </div>
    );
  }

  if (mode === 'tagging') {
    return <TaggingMode />;
  }

  const selectedMove = moves.find((m) => m.id === selectedMoveId) ?? null;
  const selectedIndex = selectedMove ? moves.indexOf(selectedMove) : null;
  const ratedCount = moves.filter((m) => labelStatus[m.id]?.environment && labelStatus[m.id]?.outcome).length;
  const lensLabel = (lens) => (lens === 'environment' ? 'Environment' : lens === 'outcome' ? 'Outcome' : lens);

  return (
    <div className="define-mode rating-view">
      <div className="progress-strip rating-strip">
        <span className="progress-counts" data-testid="rating-counts">
          <strong>{currentVideo.filename}</strong>
          {' · '}
          {ratedCount} of {moves.length} {moves.length === 1 ? 'move' : 'moves'} rated
          {' · '}
          <span className={`status-pill status-${currentAssignment.status}`}>
            {STATUS_LABEL[currentAssignment.status] || currentAssignment.status}
          </span>
        </span>
        <div className="progress-actions">
          <button type="button" className="btn-secondary" onClick={onExit}>
            ← My queue
          </button>
          {locked ? (
            <span className="locked-note" role="status">
              {currentAssignment.status === 'done'
                ? 'Rating submitted — read-only.'
                : 'This video is closed to rating.'}
            </span>
          ) : (
            <button
              type="button"
              className="btn-primary"
              onClick={handleComplete}
              disabled={completing}
            >
              {completing ? 'Checking…' : 'Complete'}
            </button>
          )}
        </div>
      </div>

      {completeError && (
        <div className="error-message complete-error" role="alert" data-testid="complete-error">
          <p>
            <strong>{completeError}</strong>
          </p>
          {missing && missing.length > 0 && (
            <ul className="missing-list">
              {missing.map((m) => (
                <li key={m.move_id}>
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => {
                      const move = moves.find((x) => x.id === m.move_id);
                      if (move) handleSelectMove(move);
                    }}
                  >
                    Move {m.move_index + 1}
                  </button>
                  {': missing '}
                  {m.missing.map(lensLabel).join(' and ')}
                </li>
              ))}
            </ul>
          )}
          {missing && missing.length === 0 && (
            <p>This video has no canonical moves to rate — ask the admin to check the prep.</p>
          )}
        </div>
      )}

      {!locked && (
        <div className="onboarding-banner" role="note">
          <span className="onboarding-text">
            Holds and moves are fixed for this video. Pick a move, fill in Environment and
            Outcome, tag frames if you want, then press Complete.
          </span>
        </div>
      )}

      <div className={`main-area ${selectedMove ? 'with-panel' : ''}`}>
        <VideoPlayer />
        <div className="side-column">
          {selectedMove ? (
            <RaterMoveForm
              key={selectedMove.id}
              move={selectedMove}
              moveIndex={selectedIndex}
              onClose={handleCloseForm}
              onSaved={handleSaved}
              locked={locked}
            />
          ) : (
            <MovesList readOnly onSelect={handleSelectMove} labelStatus={labelStatus} />
          )}
        </div>
      </div>
    </div>
  );
}

export default RatingView;
