/**
 * VideoPlayer with skeleton and hold overlays.
 *
 * Plays video with frame-accurate scrubbing, the pose skeleton, and the hold
 * boxes the labeler draws or the detector suggests.
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
import SkeletonOverlay from './SkeletonOverlay';
import HoldOverlay from './HoldOverlay';
import { getVideoCsvText, createHold, deleteHold } from '../api/client';

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

/** Parse the pose CSV into row objects keyed by column name. */
function parseCsv(csvText) {
  const lines = csvText.split('\n');
  const headers = lines[0].split(',').map((h) => h.trim());
  return lines
    .slice(1)
    .map((line) => {
      const values = line.split(',');
      const row = {};
      headers.forEach((header, i) => {
        row[header] = values[i]?.trim();
      });
      return row;
    })
    .filter((row) => row.frame_number);
}

function VideoPlayer() {
  const videoRef = useRef(null);
  // Pose rows fetched from the server, for a video not extracted this session.
  const [fetchedCsv, setFetchedCsv] = useState(null);
  const [showSkeleton, setShowSkeleton] = useState(true);
  const [holdError, setHoldError] = useState(null);

  const {
    currentVideo,
    currentFrame,
    isPlaying,
    moveStart,
    moveEnd,
    videoBlobUrl,
    videoPlaybackUrl,
    csvData: storeCsvData,
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

  // Rating view, or an owner on a locked video: holds and moves are the
  // canonical set. The player still scrubs and picks holds; it just cannot
  // draw, delete, or mark move boundaries.
  const readOnly = Boolean(readOnlyStructure);

  // This session's extraction wins; anything else is fetched. Derived rather
  // than copied into state, so there is no effect that just mirrors the store.
  const hasStoreCsv = Boolean(storeCsvData && storeCsvData.length > 0);
  const csvData = hasStoreCsv ? storeCsvData : fetchedCsv;

  useEffect(() => {
    if (!currentVideo || hasStoreCsv) return;

    let active = true;
    getVideoCsvText(currentVideo.id)
      .then((text) => active && setFetchedCsv(parseCsv(text)))
      .catch((error) => console.error('Failed to load CSV:', error));

    return () => {
      active = false;
    };
  }, [currentVideo, hasStoreCsv]);

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

  // Shortcuts. Live while the labeling panel is open — see isTextEntry.
  useEffect(() => {
    const handleKeyPress = (e) => {
      if (isTextEntry(e.target)) return;

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
        case 's':
        case 'S':
          e.preventDefault();
          setShowSkeleton((prev) => !prev);
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
  ]);

  const handleCreateMove = () => {
    if (moveStart !== null && moveEnd !== null) setShowMoveForm(true);
  };

  const handleCreateHold = async (box) => {
    setHoldError(null);
    try {
      const created = await createHold(currentVideo.id, { ...box, source: 'manual' });
      addHold(created);
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

  if (!currentVideo) return null;

  return (
    <div className="video-player">
      <div className="video-container">
        <div className="video-wrapper">
          <video ref={videoRef} src={videoBlobUrl || videoPlaybackUrl || undefined} />

          {showSkeleton && csvData && (
            <SkeletonOverlay
              videoRef={videoRef}
              currentFrame={currentFrame}
              csvData={csvData}
            />
          )}

          {showHoldOverlay && (
            <HoldOverlay
              holds={holds}
              pickSlot={holdPickSlot}
              onCreate={handleCreateHold}
              onDelete={handleDeleteHold}
              onPick={handlePickHold}
              readOnly={readOnly}
            />
          )}
        </div>
      </div>

      {holdError && <div className="error-message">{holdError}</div>}

      <div className="video-controls">
        <button onClick={() => seekToFrame(currentFrame - 10)}>⏮ -10</button>
        <button onClick={() => seekToFrame(currentFrame - 1)}>◀</button>
        <button onClick={togglePlay} className="play-btn">
          {isPlaying ? '⏸' : '▶'}
        </button>
        <button onClick={() => seekToFrame(currentFrame + 1)}>▶▶</button>
        <button onClick={() => seekToFrame(currentFrame + 10)}>+10 ⏭</button>

        <span className="frame-counter">
          Frame: {currentFrame} / {currentVideo.total_frames} (
          {frameToTime(currentFrame, fps).toFixed(2)}s)
        </span>

        <button
          onClick={() => setShowSkeleton(!showSkeleton)}
          className={`toggle-skeleton ${showSkeleton ? 'active' : ''}`}
          title="Toggle skeleton (S key)"
        >
          {showSkeleton ? '👁️ Hide' : '👁️ Show'} Skeleton
        </button>

        <button
          onClick={() => setShowHoldOverlay(!showHoldOverlay)}
          className={`toggle-holds ${showHoldOverlay ? 'active' : ''}`}
          title="Toggle hold boxes (H key)"
        >
          {showHoldOverlay ? '🪨 Hide' : '🪨 Show'} Holds ({holds.length})
        </button>
      </div>

      {showHoldOverlay && !readOnly && (
        <p className="hold-hint">
          Drag on the video to add a hold; click a hold to delete it.
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
