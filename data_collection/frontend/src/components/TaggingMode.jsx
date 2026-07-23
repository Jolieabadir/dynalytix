/**
 * TaggingMode component.
 *
 * Frame tagging interface for adding sensation tags within a move.
 * All taxonomy (tag types, body parts, sides, traction sources) comes from /api/config.
 * Supports multiple tags on the same frame.
 */
import { useRef, useEffect, useState } from 'react';
import useStore from '../store/useStore';
import {
  getFrameTags,
  createFrameTag,
  deleteFrameTag,
  getConfig,
} from '../api/client';
import { exportVideo } from '../api/ExportService';
import ThankYouModal from './ThankYouModal';
import DoneButton from './DoneButton';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Colors for tag types (visual distinction only, not taxonomy)
const TAG_COLORS = {
  sharp_pain: '#ef4444',
  dull_pain: '#f97316',
  audible_pop: '#a855f7',
  unstable: '#eab308',
  stretch: '#ec4899',
  strong: '#22c55e',
  weak: '#6b7280',
  pumped: '#3b82f6',
  fatigue: '#92400e',
};

const TAG_EMOJIS = {
  sharp_pain: '🔴',
  dull_pain: '🟠',
  audible_pop: '🟣',
  unstable: '🟡',
  stretch: '🩷',
  strong: '🟢',
  weak: '⚫',
  pumped: '🔵',
  fatigue: '🟤',
};

function TaggingMode() {
  const videoRef = useRef(null);
  const {
    currentVideo,
    currentMove,
    currentFrame,
    frameTags,
    videoBlobUrl,
    setCurrentFrame,
    setFrameTags,
    addFrameTag,
    removeFrameTag,
    setMode,
    setCurrentMove,
  } = useStore();

  const [config, setConfigState] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [selectedTagType, setSelectedTagType] = useState(null);
  const [selectedLocations, setSelectedLocations] = useState([]);
  const [intensity, setIntensity] = useState(5);
  const [side, setSide] = useState('');
  const [tractionSource, setTractionSource] = useState('');
  const [tractionDirection, setTractionDirection] = useState('');
  const [note, setNote] = useState('');
  const [showTagForm, setShowTagForm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showThankYou, setShowThankYou] = useState(false);
  const [exporting, setExporting] = useState(false);

  const fps = currentVideo?.fps || 30;

  // Load config
  useEffect(() => {
    const loadConfig = async () => {
      try {
        const configData = await getConfig();
        setConfigState(configData);
      } catch (err) {
        console.error('Failed to load config:', err);
      }
    };
    loadConfig();
  }, []);

  // Load existing frame tags when component mounts
  useEffect(() => {
    const loadTags = async () => {
      if (!currentMove) return;

      try {
        const tags = await getFrameTags(currentMove.id);
        setFrameTags(tags);
      } catch (err) {
        console.error('Failed to load frame tags:', err);
      }
    };

    loadTags();
  }, [currentMove, setFrameTags]);

  // Set initial frame to move start
  useEffect(() => {
    if (currentMove && videoRef.current) {
      const startTime = currentMove.frame_start / fps;
      videoRef.current.currentTime = startTime;
      setCurrentFrame(currentMove.frame_start);
    }
  }, [currentMove, fps, setCurrentFrame]);

  // Update frame counter as video plays
  useEffect(() => {
    if (!videoRef.current) return;

    const updateFrame = () => {
      const time = videoRef.current.currentTime;
      const frame = Math.round(time * fps);

      // Clamp to move boundaries
      if (currentMove) {
        const clampedFrame = Math.max(
          currentMove.frame_start,
          Math.min(frame, currentMove.frame_end)
        );

        // If we've gone past the end, loop back
        if (frame > currentMove.frame_end) {
          videoRef.current.currentTime = currentMove.frame_start / fps;
        }

        setCurrentFrame(clampedFrame);
      }
    };

    const video = videoRef.current;
    video.addEventListener('timeupdate', updateFrame);

    return () => {
      video.removeEventListener('timeupdate', updateFrame);
    };
  }, [fps, currentMove, setCurrentFrame]);

  const seekToFrame = (frame) => {
    if (!videoRef.current || !currentMove) return;

    const clampedFrame = Math.max(
      currentMove.frame_start,
      Math.min(frame, currentMove.frame_end)
    );
    const time = clampedFrame / fps;
    videoRef.current.currentTime = time;
    setCurrentFrame(clampedFrame);
  };

  const togglePlay = () => {
    if (!videoRef.current) return;

    if (isPlaying) {
      videoRef.current.pause();
    } else {
      videoRef.current.play();
    }
    setIsPlaying(!isPlaying);
  };

  const handleTagButtonClick = (tagTypeId) => {
    setSelectedTagType(tagTypeId);
    setShowTagForm(true);
    setSelectedLocations([]);
    setIntensity(5);
    setSide('');
    setTractionSource('');
    setTractionDirection('');
    setNote('');
    setError(null);

    // Pause video when tagging
    if (videoRef.current && isPlaying) {
      videoRef.current.pause();
      setIsPlaying(false);
    }
  };

  const toggleLocation = (location) => {
    setSelectedLocations((prev) =>
      prev.includes(location)
        ? prev.filter((l) => l !== location)
        : [...prev, location]
    );
  };

  const handleSaveTag = async () => {
    if (selectedLocations.length === 0) {
      setError('Please select at least one body part');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const tagData = {
        move_id: currentMove.id,
        frame_number: currentFrame,
        timestamp_ms: (currentFrame / fps) * 1000,
        tag_type: selectedTagType,
        level: intensity,
        locations: selectedLocations,
        side: side || null,
        traction_source: tractionSource || null,
        traction_direction: tractionDirection || null,
        note: note.trim(),
      };

      const newTag = await createFrameTag(tagData);
      addFrameTag(newTag);

      // Reset form but keep it open for another tag
      setSelectedTagType(null);
      setShowTagForm(false);
      setSelectedLocations([]);
      setIntensity(5);
      setSide('');
      setTractionSource('');
      setTractionDirection('');
      setNote('');
    } catch (err) {
      console.error('Failed to create tag:', err);
      setError('Failed to save tag. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteTag = async (tagId) => {
    if (!window.confirm('Delete this tag?')) return;

    try {
      await deleteFrameTag(tagId);
      removeFrameTag(tagId);
    } catch (err) {
      console.error('Failed to delete tag:', err);
      alert('Failed to delete tag');
    }
  };

  // Save & Next Move - go back to define mode to create another move
  const handleNextMove = () => {
    setMode('define');
    setCurrentMove(null);
    setFrameTags([]);
  };

  // Done - export then show thank you
  const handleDone = async () => {
    setExporting(true);
    try {
      await exportVideo(currentVideo.id, true); // true = delete video after export
      setShowThankYou(true);
    } catch (err) {
      console.error('Export failed:', err);
      // Still show thank you - data is saved in db
      setShowThankYou(true);
    } finally {
      setExporting(false);
    }
  };

  const formatLabel = (str) => {
    return str
      .split('_')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const getTagColor = (tagType) => {
    return TAG_COLORS[tagType] || '#888';
  };

  const getTagEmoji = (tagType) => {
    return TAG_EMOJIS[tagType] || '⚪';
  };

  const getTagLabel = (tagType) => {
    if (!config?.tag_types) return formatLabel(tagType);
    return config.tag_types[tagType] || formatLabel(tagType);
  };

  // Group body parts for display
  const groupBodyParts = (bodyParts) => {
    if (!bodyParts) return [];

    const groups = {
      'Left Side': [],
      'Right Side': [],
      'Core/Back': [],
    };

    bodyParts.forEach((part) => {
      if (part.startsWith('left_')) {
        groups['Left Side'].push(part);
      } else if (part.startsWith('right_')) {
        groups['Right Side'].push(part);
      } else {
        groups['Core/Back'].push(part);
      }
    });

    return Object.entries(groups).filter(([, parts]) => parts.length > 0);
  };

  if (!currentMove || !currentVideo) {
    return (
      <div className="tagging-mode">
        <p>No move selected.</p>
        <button onClick={handleNextMove}>Back to Define Mode</button>
      </div>
    );
  }

  if (!config) {
    return <div className="tagging-mode">Loading configuration...</div>;
  }

  const moveFrameCount = currentMove.frame_end - currentMove.frame_start;
  const currentMoveFrame = currentFrame - currentMove.frame_start;

  // Get tags for current frame (may be multiple)
  const tagsOnCurrentFrame = frameTags.filter(
    (t) => t.frame_number === currentFrame
  );

  return (
    <div className="tagging-mode">
      {/* Header */}
      <div className="tagging-header">
        <div className="header-buttons">
          <button onClick={handleNextMove} className="back-btn save-next-btn">
            Save & Next Move →
          </button>
          <DoneButton onClick={handleDone} disabled={exporting} />
          {exporting && <span className="exporting-text">Exporting...</span>}
        </div>
        <div className="move-info">
          <h2>
            Tagging: {formatLabel(currentMove.approach)} ·{' '}
            {formatLabel(currentMove.size)}
            {currentMove.move_tags?.length > 0 &&
              ` · ${currentMove.move_tags.map(formatLabel).join(', ')}`}
          </h2>
          <span className="frame-range">
            Frames {currentMove.frame_start} - {currentMove.frame_end}
          </span>
        </div>
      </div>

      <div className="tagging-content">
        {/* Video Section */}
        <div className="tagging-video-section">
          <div className="video-container">
            <video
              ref={videoRef}
              src={
                videoBlobUrl || `${API_BASE_URL}/videos/${currentVideo.filename}`
              }
              loop
            />
          </div>

          {/* Video Controls */}
          <div className="video-controls">
            <button onClick={() => seekToFrame(currentFrame - 10)}>⏮ -10</button>
            <button onClick={() => seekToFrame(currentFrame - 1)}>◀</button>
            <button onClick={togglePlay} className="play-btn">
              {isPlaying ? '⏸' : '▶'}
            </button>
            <button onClick={() => seekToFrame(currentFrame + 1)}>▶</button>
            <button onClick={() => seekToFrame(currentFrame + 10)}>+10 ⏭</button>
          </div>

          {/* Frame Info */}
          <div className="frame-info">
            <span>Frame: {currentFrame}</span>
            <span>
              Move Frame: {currentMoveFrame} / {moveFrameCount}
            </span>
            <span>({(currentFrame / fps).toFixed(2)}s)</span>
            {tagsOnCurrentFrame.length > 0 && (
              <span className="tags-on-frame">
                {tagsOnCurrentFrame.length} tag
                {tagsOnCurrentFrame.length !== 1 ? 's' : ''} on this frame
              </span>
            )}
          </div>

          {/* Timeline with tag markers */}
          <div className="tagging-timeline">
            <input
              type="range"
              min={currentMove.frame_start}
              max={currentMove.frame_end}
              value={currentFrame}
              onChange={(e) => seekToFrame(parseInt(e.target.value))}
              className="timeline-slider"
            />
            {/* Tag markers */}
            {frameTags.map((tag) => {
              const position =
                ((tag.frame_number - currentMove.frame_start) / moveFrameCount) *
                100;
              return (
                <div
                  key={tag.id}
                  className="tag-marker"
                  style={{
                    left: `${position}%`,
                    backgroundColor: getTagColor(tag.tag_type),
                  }}
                  title={`${getTagLabel(tag.tag_type)} @ frame ${tag.frame_number}`}
                />
              );
            })}
          </div>
        </div>

        {/* Tag Controls Section */}
        <div className="tagging-controls-section">
          <h3>Add Tag at Frame {currentFrame}</h3>

          {/* Tag Type Buttons - from config */}
          <div className="tag-buttons-grid">
            {Object.entries(config.tag_types).map(([id, label]) => (
              <button
                key={id}
                className={`tag-button ${selectedTagType === id ? 'selected' : ''}`}
                style={{ '--tag-color': getTagColor(id) }}
                onClick={() => handleTagButtonClick(id)}
              >
                <span className="tag-emoji">{getTagEmoji(id)}</span>
                <span className="tag-label">{label}</span>
              </button>
            ))}
          </div>

          {/* Tag Form (appears when tag type selected) */}
          {showTagForm && selectedTagType && (
            <div className="tag-form">
              <div className="tag-form-header">
                <span
                  className="selected-tag-badge"
                  style={{ backgroundColor: getTagColor(selectedTagType) }}
                >
                  {getTagEmoji(selectedTagType)} {getTagLabel(selectedTagType)}
                </span>
                <span className="at-frame">at Frame {currentFrame}</span>
              </div>

              {/* Body Part Multi-Select - from config */}
              <div className="form-group">
                <label>Body Parts (select all that apply)</label>
                <div className="body-parts-grid">
                  {groupBodyParts(config.body_parts).map(([group, parts]) => (
                    <div key={group} className="body-part-group">
                      <div className="group-label">{group}</div>
                      {parts.map((part) => (
                        <label key={part} className="body-part-checkbox">
                          <input
                            type="checkbox"
                            checked={selectedLocations.includes(part)}
                            onChange={() => toggleLocation(part)}
                          />
                          {formatLabel(part)}
                        </label>
                      ))}
                    </div>
                  ))}
                </div>
              </div>

              {/* Side - from config */}
              <div className="form-group">
                <label>Side (optional)</label>
                <div className="radio-group-inline">
                  <label className="radio-label">
                    <input
                      type="radio"
                      name="side"
                      value=""
                      checked={side === ''}
                      onChange={() => setSide('')}
                    />
                    None
                  </label>
                  {config.sides.map((s) => (
                    <label key={s} className="radio-label">
                      <input
                        type="radio"
                        name="side"
                        value={s}
                        checked={side === s}
                        onChange={() => setSide(s)}
                      />
                      {formatLabel(s)}
                    </label>
                  ))}
                </div>
              </div>

              {/* Traction Source - from config */}
              <div className="form-group">
                <label>Traction Source (optional)</label>
                <div className="radio-group-inline">
                  <label className="radio-label">
                    <input
                      type="radio"
                      name="traction_source"
                      value=""
                      checked={tractionSource === ''}
                      onChange={() => setTractionSource('')}
                    />
                    None
                  </label>
                  {config.traction_sources.map((ts) => (
                    <label key={ts} className="radio-label">
                      <input
                        type="radio"
                        name="traction_source"
                        value={ts}
                        checked={tractionSource === ts}
                        onChange={() => setTractionSource(ts)}
                      />
                      {formatLabel(ts)}
                    </label>
                  ))}
                </div>
              </div>

              {/* Traction Direction - free text */}
              <div className="form-group">
                <label>Traction Direction (optional)</label>
                <input
                  type="text"
                  value={tractionDirection}
                  onChange={(e) => setTractionDirection(e.target.value)}
                  placeholder="e.g., internal rotation, lateral..."
                  className="text-input"
                />
              </div>

              {/* Intensity Slider */}
              <div className="form-group">
                <label>Intensity: {intensity}/10</label>
                <input
                  type="range"
                  min="0"
                  max="10"
                  value={intensity}
                  onChange={(e) => setIntensity(parseInt(e.target.value))}
                  className="intensity-slider"
                />
                <div className="intensity-labels">
                  <span>Mild</span>
                  <span>Moderate</span>
                  <span>Severe</span>
                </div>
              </div>

              {/* Note */}
              <div className="form-group">
                <label>Note (optional)</label>
                <input
                  type="text"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Additional details..."
                  className="note-input"
                />
              </div>

              {error && <div className="error-message">{error}</div>}

              {/* Form Actions */}
              <div className="form-actions">
                <button
                  onClick={() => {
                    setShowTagForm(false);
                    setSelectedTagType(null);
                  }}
                  className="cancel-btn"
                  disabled={loading}
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveTag}
                  className="save-btn"
                  disabled={loading || selectedLocations.length === 0}
                >
                  {loading ? 'Saving...' : 'Save Tag'}
                </button>
              </div>
            </div>
          )}

          {/* Existing Tags List */}
          <div className="existing-tags">
            <h4>Tags on this Move ({frameTags.length})</h4>
            {frameTags.length === 0 ? (
              <p className="no-tags">
                No tags yet. Click a tag button above to add one.
              </p>
            ) : (
              <div className="tags-list">
                {frameTags.map((tag) => (
                  <div
                    key={tag.id}
                    className={`tag-item ${tag.frame_number === currentFrame ? 'current-frame' : ''}`}
                  >
                    <div
                      className="tag-color-dot"
                      style={{ backgroundColor: getTagColor(tag.tag_type) }}
                    />
                    <div className="tag-details">
                      <div className="tag-main">
                        <strong>{getTagLabel(tag.tag_type)}</strong>
                        <span className="tag-frame">Frame {tag.frame_number}</span>
                      </div>
                      <div className="tag-meta">
                        <span>{tag.locations?.map(formatLabel).join(', ')}</span>
                        <span className="tag-level">Level: {tag.level}/10</span>
                        {tag.side && (
                          <span className="tag-side">{formatLabel(tag.side)}</span>
                        )}
                        {tag.traction_source && (
                          <span className="tag-traction">
                            {formatLabel(tag.traction_source)}
                          </span>
                        )}
                      </div>
                      {tag.traction_direction && (
                        <div className="tag-traction-dir">
                          Direction: {tag.traction_direction}
                        </div>
                      )}
                      {tag.note && <div className="tag-note">{tag.note}</div>}
                    </div>
                    <button
                      className="delete-tag-btn"
                      onClick={() => handleDeleteTag(tag.id)}
                      title="Delete tag"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <ThankYouModal show={showThankYou} onClose={() => setShowThankYou(false)} />
    </div>
  );
}

export default TaggingMode;
