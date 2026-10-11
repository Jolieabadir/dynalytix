/**
 * VideoPlayer with the hold overlay.
 *
 * Plays video with frame-accurate scrubbing and the hold boxes the labeler
 * draws or the detector suggests. (The pose skeleton overlay was removed in
 * the single-dataset change; labelers judge the footage itself.)
 *
 * Keyboard note: the shortcut handler used to bail out on any INPUT, which was
 * fine when the labeling form was a modal that covered the video. Now the form
 * is a side panel and stays open while scrubbing, so bailing on every INPUT
 * would kill [ and ] the moment a radio button took focus. It now bails only on
 * genuine text entry — see isTextEntry.
 */
import { useRef, useEffect, useState, useCallback } from 'react';
import useStore from '../store/useStore';
import { fpsOf, timeToFrame, frameToTime } from '../utils/frames';
import HoldOverlay from './HoldOverlay';
import { createHold, deleteHold, updateHold } from '../api/client';
import { useCoarsePointer } from '../utils/pointer';

/**
 * True only for elements where a keystroke means text, not a shortcut.
 * Radios, checkboxes, ranges and buttons all keep the shortcuts alive.
 */
function isTextEntry(element) {
  if (!element) return false;
  if (element.isContentEditable) return true;
  const tag = element.tagName;
  if (tag === 'TEXTAREA') return true;
  if (tag !== 'INPUT') return false;
  const type = (element.type || 'text').toLowerCase();
  return ['text', 'email', 'password', 'search', 'url', 'tel', 'number'].includes(type);
}

const NO_HISTORY = [];

function VideoPlayer() {
  const videoRef = useRef(null);
  const [holdError, setHoldError] = useState(null);
  // Hold edits made this session, newest last, so a stray click or tap can be
  // taken back. Tagged with its video so switching videos starts it empty.
  const [history, setHistory] = useState({ videoId: null, entries: [] });

  const {
    currentVideo,
    currentFrame,
    isPlaying,
    moveStart,
    moveEnd,
    videoBlobUrl,
    videoPlaybackUrl,
    holds,
    showHoldOverlay,
    holdPickSlot,
    readOnlyStructure,
    currentMove,
    setCurrentFrame,
    setIsPlaying,
    setMoveStart,
    setMoveEnd,
    setShowMoveForm,
    clearMoveSelection,
    setShowHoldOverlay,
    addHold,
    removeHold,
    setHoldPickSlot,
  } = useStore();

  const fps = fpsOf(currentVideo);

  // One UI, two input models. See utils/pointer — this is the primary
  // pointer, re-read when it changes (an iPad gaining a trackpad mid-session).
  const touch = useCoarsePointer();

  // Rating view, or an owner on a locked video: holds and moves are the
  // canonical set. The player still scrubs and picks holds; it just cannot
  // draw, delete, or mark move boundaries.
  const readOnly = Boolean(readOnlyStructure);

  const videoId = currentVideo?.id ?? null;
  const holdHistory = history.videoId === videoId ? history.entries : NO_HISTORY;
  const setHoldHistory = useCallback(
    (update) =>
      setHistory((h) => ({
        videoId,
        entries: update(h.videoId === videoId ? h.entries : []),
      })),
    [videoId]
  );
  const pushHistory = (entry) => setHoldHistory((h) => [...h.slice(-49), entry]);

  // Frame counter follows playback.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const updateFrame = () => {
      if (!fps) return;
      setCurrentFrame(timeToFrame(video.currentTime, fps));
    };

    video.addEventListener('timeupdate', updateFrame);
    return () => video.removeEventListener('timeupdate', updateFrame);
  }, [fps, setCurrentFrame]);

  const seekToFrame = useCallback(
    (frame) => {
      if (!videoRef.current) return;
      const clamped = Math.max(0, frame);
      videoRef.current.currentTime = frameToTime(clamped, fps);
      setCurrentFrame(clamped);
    },
    [fps, setCurrentFrame]
  );

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      video.play();
      setIsPlaying(true);
    } else {
      video.pause();
      setIsPlaying(false);
    }
  }, [setIsPlaying]);

  /**
   * Take back the last hold edit. A deleted hold comes back as a new row with
   * a new id, so older history entries for it are re-pointed at that id.
   */
  const undoHoldEdit = useCallback(async () => {
    const entry = holdHistory[holdHistory.length - 1];
    if (!entry) return;
    setHoldHistory((h) => h.slice(0, -1));
    setHoldError(null);
    const { bbox_x, bbox_y, bbox_w, bbox_h } = entry.hold;
    try {
      if (entry.type === 'create') {
        removeHold(entry.hold.id);
        await deleteHold(entry.hold.id);
      } else if (entry.type === 'delete') {
        const restored = await createHold(videoId, {
          bbox_x,
          bbox_y,
          bbox_w,
          bbox_h,
          source: entry.hold.source,
        });
        addHold(restored);
        setHoldHistory((h) =>
          h.map((e) =>
            e.hold.id === entry.hold.id ? { ...e, hold: { ...e.hold, id: restored.id } } : e
          )
        );
      } else if (entry.type === 'resize') {
        const saved = await updateHold(entry.hold.id, { bbox_x, bbox_y, bbox_w, bbox_h });
        removeHold(entry.hold.id);
        addHold(saved);
      }
    } catch (err) {
      console.error('Failed to undo hold edit:', err);
      setHoldError(err.response?.data?.detail || 'Could not undo that.');
    }
  }, [holdHistory, setHoldHistory, videoId, addHold, removeHold]);

  // Shortcuts. Live while the labeling panel is open — see isTextEntry.
  useEffect(() => {
    const handleKeyPress = (e) => {
      if (isTextEntry(e.target)) return;

      if ((e.metaKey || e.ctrlKey) && (e.key === 'z' || e.key === 'Z') && !e.shiftKey) {
        if (!readOnly && holdHistory.length) {
          e.preventDefault();
          undoHoldEdit();
        }
        return;
      }

      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault();
          seekToFrame(currentFrame - 1);
          break;
        case 'ArrowRight':
          e.preventDefault();
          seekToFrame(currentFrame + 1);
          break;
        case ' ':
          e.preventDefault();
          togglePlay();
          break;
        case '[':
          e.preventDefault();
          if (!readOnly) setMoveStart(currentFrame);
          break;
        case ']':
          e.preventDefault();
          if (!readOnly) setMoveEnd(currentFrame);
          break;
        case 'h':
        case 'H':
          e.preventDefault();
          setShowHoldOverlay(!showHoldOverlay);
          break;
        case 'Escape':
          if (holdPickSlot) {
            e.preventDefault();
            setHoldPickSlot(null);
          }
          break;
        default:
          break;
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [
    currentFrame,
    seekToFrame,
    togglePlay,
    setMoveStart,
    setMoveEnd,
    showHoldOverlay,
    setShowHoldOverlay,
    holdPickSlot,
    setHoldPickSlot,
    readOnly,
    holdHistory,
    undoHoldEdit,
  ]);

  const handleCreateMove = () => {
    if (moveStart !== null && moveEnd !== null) setShowMoveForm(true);
  };

  const handleCreateHold = async (box) => {
    setHoldError(null);
    try {
      const created = await createHold(currentVideo.id, { ...box, source: 'manual' });
      addHold(created);
      pushHistory({ type: 'create', hold: created });
    } catch (err) {
      console.error('Failed to create hold:', err);
      setHoldError(err.response?.data?.detail || 'Could not save that hold.');
    }
  };

  const handleDeleteHold = async (hold) => {
    setHoldError(null);
    // Drop it locally first so the click feels immediate, and put it back if
    // the server disagrees.
    removeHold(hold.id);
    try {
      await deleteHold(hold.id);
      pushHistory({ type: 'delete', hold });
    } catch (err) {
      console.error('Failed to delete hold:', err);
      addHold(hold);
      setHoldError(err.response?.data?.detail || 'Could not delete that hold.');
    }
  };

  // Hand the picked hold back to whichever MoveForm slot asked for it.
  const handlePickHold = (hold) => {
    if (!holdPickSlot) return;
    setHoldPickSlot({ ...holdPickSlot, assignedHoldId: hold.id });
  };

  /** Pinch-to-resize on touch. Optimistic, and reverted if the server says no. */
  const handleResizeHold = async (hold, box) => {
    setHoldError(null);
    removeHold(hold.id);
    addHold({ ...hold, ...box });
    try {
      const saved = await updateHold(hold.id, box);
      removeHold(hold.id);
      addHold(saved);
      pushHistory({ type: 'resize', hold });
    } catch (err) {
      console.error('Failed to resize hold:', err);
      removeHold(hold.id);
      addHold(hold);
      setHoldError(err.response?.data?.detail || 'Could not resize that hold.');
    }
  };

  /** Swipe on the video steps frames — the phone has no arrow keys. */
  const handleSwipeFrames = (delta) => seekToFrame(currentFrame + delta);

  if (!currentVideo) return null;

  return (
    <div className="video-player">
      <div className="video-container">
        <div className="video-wrapper">
          <video ref={videoRef} src={videoBlobUrl || videoPlaybackUrl || undefined} playsInline />

          {showHoldOverlay && (
            <HoldOverlay
              holds={holds}
              pickSlot={holdPickSlot}
              onCreate={handleCreateHold}
              onDelete={handleDeleteHold}
              onPick={handlePickHold}
              onResize={handleResizeHold}
              onSwipeFrames={handleSwipeFrames}
              readOnly={readOnly}
              touch={touch}
            />
          )}
        </div>
      </div>

      {holdError && <div className="error-message">{holdError}</div>}

      <div className={`video-controls ${touch ? 'touch' : ''}`}>
        <button onClick={() => seekToFrame(currentFrame - 10)} aria-label="Back ten frames">
          ⏮ -10
        </button>
        <button onClick={() => seekToFrame(currentFrame - 1)} aria-label="Back one frame">
          ◀ -1
        </button>
        <button onClick={togglePlay} className="play-btn" aria-label={isPlaying ? 'Pause' : 'Play'}>
          {isPlaying ? '⏸' : '▶'}
        </button>
        <button onClick={() => seekToFrame(currentFrame + 1)} aria-label="Forward one frame">
          +1 ▶
        </button>
        <button onClick={() => seekToFrame(currentFrame + 10)} aria-label="Forward ten frames">
          +10 ⏭
        </button>

        <span className="frame-counter">
          Frame: {currentFrame} / {currentVideo.total_frames} (
          {frameToTime(currentFrame, fps).toFixed(2)}s)
        </span>

        <button
          onClick={() => setShowHoldOverlay(!showHoldOverlay)}
          className={`toggle-holds ${showHoldOverlay ? 'active' : ''}`}
          title="Toggle hold boxes (H key)"
        >
          {showHoldOverlay ? '🪨 Hide' : '🪨 Show'} Holds ({holds.length})
        </button>

        {!readOnly && (
          <button
            onClick={undoHoldEdit}
            disabled={!holdHistory.length}
            className="undo-hold"
            title={touch ? 'Undo last hold edit' : 'Undo last hold edit (⌘Z / Ctrl+Z)'}
            aria-label="Undo last hold edit"
          >
            ↶ Undo
          </button>
        )}
      </div>

      {showHoldOverlay && !readOnly && (
        <p className={`hold-hint ${holds.length === 0 ? 'empty' : ''}`}>
          {holds.length === 0 ? (
            <>
              <strong>First, box the holds.</strong> Mark every hold the climber uses so
              moves can point at them.{' '}
            </>
          ) : (
            <>Box every hold the climber uses — dashed boxes are detector guesses. </>
          )}
          {touch
            ? 'Tap to add · tap a box, then pinch to resize · press and hold to delete · swipe to step a frame.'
            : 'Drag a box around a hold to add it · click a box to delete it · ⌘Z to undo.'}
        </p>
      )}
      {showHoldOverlay && readOnly && (
        <p className="hold-hint">
          Holds are locked for this video. Use “Pick on video” in the form to choose one.
        </p>
      )}

      <div className="timeline">
        <input
          type="range"
          min="0"
          max={currentVideo.total_frames}
          value={currentFrame}
          onChange={(e) => seekToFrame(parseInt(e.target.value, 10))}
          className="timeline-slider"
        />
        {moveStart !== null && (
          <div
            className="move-marker start"
            style={{ left: `${(moveStart / currentVideo.total_frames) * 100}%` }}
          />
        )}
        {moveEnd !== null && (
          <div
            className="move-marker end"
            style={{ left: `${(moveEnd / currentVideo.total_frames) * 100}%` }}
          />
        )}
        {readOnly && currentMove && (
          <>
            <div
              className="move-marker start"
              style={{ left: `${(currentMove.frame_start / currentVideo.total_frames) * 100}%` }}
            />
            <div
              className="move-marker end"
              style={{ left: `${(currentMove.frame_end / currentVideo.total_frames) * 100}%` }}
            />
          </>
        )}
      </div>

      {readOnly ? (
        <div className="move-selection-controls readonly" data-testid="move-selection-readonly">
          {currentMove ? (
            <span className="selection-info">
              Move: frames {currentMove.frame_start} – {currentMove.frame_end}
            </span>
          ) : (
            <span className="selection-info">Select a move from the list to rate it.</span>
          )}
        </div>
      ) : (
      <div className="move-selection-controls">
        <button
          onClick={() => setMoveStart(currentFrame)}
          className={moveStart !== null ? 'active' : ''}
        >
          [ Mark Start
        </button>
        <button onClick={() => setMoveEnd(currentFrame)} disabled={moveStart === null}>
          ] Mark End
        </button>

        {moveStart !== null && moveEnd !== null && (
          <>
            <span className="selection-info">
              Selected: {moveStart} – {moveEnd} ({moveEnd - moveStart} frames)
            </span>
            <button onClick={handleCreateMove} className="create-move-btn">
              Create Move
            </button>
            <button onClick={clearMoveSelection} className="clear-selection-btn">
              Clear Selection
            </button>
          </>
        )}
      </div>
      )}
    </div>
  );
}

export default VideoPlayer;
