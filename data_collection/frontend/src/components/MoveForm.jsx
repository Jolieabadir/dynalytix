/**
 * MoveForm component.
 *
 * Three-lens labeling flow:
 * - Lens 1: Environment (wall angle, hold types, hold quality)
 * - Lens 2: Strategy (approach, size, move tags, form quality, effort)
 * - Lens 3: Outcome (result, reach detail, foot cut, confidence)
 *
 * All taxonomy comes from /api/config - no hardcoded values.
 */
import { useState, useEffect } from 'react';
import useStore from '../store/useStore';
import {
  createMove,
  createEnvironment,
  createOutcome,
  getConfig,
  deleteMove,
} from '../api/client';

// Form quality anchor text
const FORM_QUALITY_LABELS = {
  1: 'Failed',
  2: 'Clear compensation',
  3: 'Acceptable',
  4: 'Efficient/repeatable',
  5: 'Excellent, repeatable under greater demand',
};

// Required config keys for this component
const REQUIRED_CONFIG_KEYS = [
  'wall_angles',
  'hold_types',
  'hold_qualities',
  'approaches',
  'sizes',
  'move_tags',
  'results',
  'reach_details',
  'confidence_levels',
];

function MoveForm() {
  const {
    currentVideo,
    moveStart,
    moveEnd,
    showMoveForm,
    setShowMoveForm,
    clearMoveSelection,
    addMove,
    previousEnvironment,
    setPreviousEnvironment,
  } = useStore();

  const [config, setConfigState] = useState(null);
  const [configError, setConfigError] = useState(null);

  // Lens 1: Environment
  const [wallAngle, setWallAngle] = useState('');
  const [holdTypeReaching, setHoldTypeReaching] = useState('');
  const [holdTypeNonReaching, setHoldTypeNonReaching] = useState('');
  const [holdQuality, setHoldQuality] = useState([]);

  // Lens 2: Strategy
  const [approach, setApproach] = useState('');
  const [size, setSize] = useState('');
  const [moveTags, setMoveTags] = useState([]);
  const [formQuality, setFormQuality] = useState(3);
  const [effortLevel, setEffortLevel] = useState(5);
  const [description, setDescription] = useState('');

  // Lens 3: Outcome
  const [result, setResult] = useState('');
  const [reachDetail, setReachDetail] = useState('');
  const [footCut, setFootCut] = useState(false);
  const [confidence, setConfidence] = useState('');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Validate config has all required keys
  const validateConfig = (configData) => {
    if (!configData || typeof configData !== 'object') {
      return { valid: false, missing: ['Config is null or not an object'] };
    }
    const missing = REQUIRED_CONFIG_KEYS.filter(
      (key) => !configData[key] || !Array.isArray(configData[key])
    );
    return { valid: missing.length === 0, missing };
  };

  // Load configuration
  useEffect(() => {
    const loadConfig = async () => {
      try {
        setConfigError(null);
        const configData = await getConfig();
        const validation = validateConfig(configData);
        if (!validation.valid) {
          setConfigError(`Missing config keys: ${validation.missing.join(', ')}`);
          return;
        }
        setConfigState(configData);
      } catch (err) {
        console.error('Failed to load config:', err);
        setConfigError(`Failed to load configuration: ${err.message}`);
      }
    };
    if (showMoveForm && !config) {
      loadConfig();
    }
  }, [showMoveForm, config]);

  // Reset form when opened, prefill environment from previous move
  useEffect(() => {
    if (showMoveForm) {
      // Lens 1: Prefill from previous move's environment
      setWallAngle(previousEnvironment.wall_angle || '');
      setHoldTypeReaching(previousEnvironment.hold_type_reaching || '');
      setHoldTypeNonReaching(previousEnvironment.hold_type_non_reaching || '');
      setHoldQuality(previousEnvironment.hold_quality || []);

      // Lens 2: Reset to defaults
      setApproach('');
      setSize('');
      setMoveTags([]);
      setFormQuality(3);
      setEffortLevel(5);
      setDescription('');

      // Lens 3: Reset to defaults
      setResult('');
      setReachDetail('');
      setFootCut(false);
      setConfidence('');

      setError(null);
    }
  }, [showMoveForm, previousEnvironment]);

  const handleClose = () => {
    setShowMoveForm(false);
  };

  const toggleMoveTag = (tag) => {
    setMoveTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  };

  const toggleHoldQuality = (quality) => {
    setHoldQuality((prev) =>
      prev.includes(quality)
        ? prev.filter((q) => q !== quality)
        : [...prev, quality]
    );
  };

  const handleSubmit = async () => {
    // Validation
    if (!currentVideo || moveStart === null || moveEnd === null) {
      setError('Invalid move boundaries');
      return;
    }

    // Lens 1 validation
    if (!wallAngle || !holdTypeReaching || !holdTypeNonReaching) {
      setError('Please complete all Environment fields');
      return;
    }

    // Lens 2 validation
    if (!approach || !size) {
      setError('Please select Approach and Size');
      return;
    }

    // Lens 3 validation
    if (!result || !reachDetail || !confidence) {
      setError('Please complete all Outcome fields');
      return;
    }

    setLoading(true);
    setError(null);

    let createdMove = null;

    try {
      const fps = currentVideo.fps;

      // Step 1: Create the move (Lens 2: Strategy)
      const moveData = {
        video_id: currentVideo.id,
        frame_start: moveStart,
        frame_end: moveEnd,
        timestamp_start_ms: (moveStart / fps) * 1000,
        timestamp_end_ms: (moveEnd / fps) * 1000,
        approach: approach,
        size: size,
        move_tags: moveTags,
        form_quality: formQuality,
        effort_level: effortLevel,
        tags: [],
        description: description,
      };

      createdMove = await createMove(moveData);

      // Step 2: Create the environment (Lens 1)
      const envData = {
        move_id: createdMove.id,
        wall_angle: wallAngle,
        hold_type_reaching: holdTypeReaching,
        hold_type_non_reaching: holdTypeNonReaching,
        hold_quality: holdQuality,
      };

      await createEnvironment(envData);

      // Step 3: Create the outcome (Lens 3)
      const outcomeData = {
        move_id: createdMove.id,
        result: result,
        reach_detail: reachDetail,
        foot_cut: footCut,
        confidence: confidence,
      };

      await createOutcome(outcomeData);

      // Save environment for prefilling next move
      setPreviousEnvironment(envData);

      // Success - add to list and close
      addMove(createdMove);
      clearMoveSelection();
      setShowMoveForm(false);
    } catch (err) {
      console.error('Failed to create move:', err);

      // Rollback: if move was created but env/outcome failed, delete the move
      if (createdMove) {
        try {
          await deleteMove(createdMove.id);
        } catch (rollbackErr) {
          console.error('Rollback failed:', rollbackErr);
        }
      }

      setError(
        err.response?.data?.detail || 'Failed to create move. Please try again.'
      );
    } finally {
      setLoading(false);
    }
  };

  if (!showMoveForm) return null;

  // Show loading state while config loads
  if (!config && !configError) {
    return (
      <div className="move-form-overlay">
        <div className="move-form-modal">
          <div className="move-form-loading">Loading configuration...</div>
        </div>
      </div>
    );
  }

  // Show error state if config failed to load
  if (configError) {
    return (
      <div className="move-form-overlay">
        <div className="move-form-modal">
          <div className="move-form-header">
            <h2>Configuration Error</h2>
            <button onClick={handleClose} className="close-btn">
              ✕
            </button>
          </div>
          <div className="move-form-content">
            <div className="error-message config-error">
              <p><strong>Failed to load form configuration.</strong></p>
              <p>{configError}</p>
              <p>Please ensure the backend API is running and accessible.</p>
            </div>
          </div>
          <div className="move-form-footer">
            <button onClick={handleClose} className="btn-secondary">
              Close
            </button>
          </div>
        </div>
      </div>
    );
  }

  const fps = currentVideo?.fps || 30;
  const duration =
    moveEnd && moveStart ? ((moveEnd - moveStart) / fps).toFixed(2) : 0;
  const frameCount = moveEnd && moveStart ? moveEnd - moveStart : 0;

  return (
    <div className="move-form-overlay">
      <div className="move-form-modal move-form-three-lens">
        <div className="move-form-header">
          <h2>Label Move</h2>
          <button onClick={handleClose} className="close-btn">
            ✕
          </button>
        </div>

        <div className="move-form-content">
          {/* Move Info */}
          <div className="move-info">
            <p>
              Frames: {moveStart} - {moveEnd} ({frameCount} frames, {duration}s)
            </p>
          </div>

          {error && <div className="error-message">{error}</div>}

          {/* Lens 1: Environment */}
          <div className="lens-section">
            <h3 className="lens-title">🏔️ Environment</h3>

            <div className="form-field">
              <label className="form-label">Wall Angle</label>
              <div className="radio-group">
                {(config.wall_angles ?? []).map((angle) => (
                  <label key={angle} className="radio-label">
                    <input
                      type="radio"
                      name="wall_angle"
                      value={angle}
                      checked={wallAngle === angle}
                      onChange={() => setWallAngle(angle)}
                    />
                    {formatLabel(angle)}
                  </label>
                ))}
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Hold Type (Reaching Hand)</label>
              <div className="radio-group">
                {(config.hold_types ?? []).map((type) => (
                  <label key={type} className="radio-label">
                    <input
                      type="radio"
                      name="hold_type_reaching"
                      value={type}
                      checked={holdTypeReaching === type}
                      onChange={() => setHoldTypeReaching(type)}
                    />
                    {formatLabel(type)}
                  </label>
                ))}
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Hold Type (Non-Reaching Hand)</label>
              <div className="radio-group">
                {(config.hold_types ?? []).map((type) => (
                  <label key={type} className="radio-label">
                    <input
                      type="radio"
                      name="hold_type_non_reaching"
                      value={type}
                      checked={holdTypeNonReaching === type}
                      onChange={() => setHoldTypeNonReaching(type)}
                    />
                    {formatLabel(type)}
                  </label>
                ))}
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Hold Quality (multi-select)</label>
              <div className="checkbox-group">
                {(config.hold_qualities ?? []).map((quality) => (
                  <label key={quality} className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={holdQuality.includes(quality)}
                      onChange={() => toggleHoldQuality(quality)}
                    />
                    {formatLabel(quality)}
                  </label>
                ))}
              </div>
            </div>
          </div>

          {/* Lens 2: Strategy */}
          <div className="lens-section">
            <h3 className="lens-title">🎯 Strategy</h3>

            <div className="form-field">
              <label className="form-label">Approach</label>
              <div className="radio-group">
                {(config.approaches ?? []).map((a) => (
                  <label key={a} className="radio-label">
                    <input
                      type="radio"
                      name="approach"
                      value={a}
                      checked={approach === a}
                      onChange={() => setApproach(a)}
                    />
                    {formatLabel(a)}
                  </label>
                ))}
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Size</label>
              <div className="radio-group">
                {(config.sizes ?? []).map((s) => (
                  <label key={s} className="radio-label">
                    <input
                      type="radio"
                      name="size"
                      value={s}
                      checked={size === s}
                      onChange={() => setSize(s)}
                    />
                    {formatLabel(s)}
                  </label>
                ))}
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Move Tags (multi-select)</label>
              <div className="tags-group">
                {(config.move_tags ?? []).map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => toggleMoveTag(tag)}
                    className={`tag-btn ${moveTags.includes(tag) ? 'active' : ''}`}
                  >
                    {formatLabel(tag)}
                  </button>
                ))}
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Form Quality</label>
              <div className="quality-buttons">
                {[1, 2, 3, 4, 5].map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => setFormQuality(q)}
                    className={`quality-btn ${formQuality === q ? 'active' : ''}`}
                    title={FORM_QUALITY_LABELS[q]}
                  >
                    {q}
                  </button>
                ))}
              </div>
              <div className="quality-description">
                {FORM_QUALITY_LABELS[formQuality]}
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Effort Level: {effortLevel}/10</label>
              <input
                type="range"
                min="0"
                max="10"
                value={effortLevel}
                onChange={(e) => setEffortLevel(Number(e.target.value))}
                className="effort-slider"
              />
              <div className="effort-labels">
                <span>Easy</span>
                <span>Max Effort</span>
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Description (optional)</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value.slice(0, 500))}
                placeholder="Add notes about this move..."
                className="description-textarea"
                rows="2"
              />
            </div>
          </div>

          {/* Lens 3: Outcome */}
          <div className="lens-section">
            <h3 className="lens-title">📊 Outcome</h3>

            <div className="form-field">
              <label className="form-label">Result</label>
              <div className="radio-group">
                {(config.results ?? []).map((r) => (
                  <label key={r} className="radio-label">
                    <input
                      type="radio"
                      name="result"
                      value={r}
                      checked={result === r}
                      onChange={() => setResult(r)}
                    />
                    {formatLabel(r)}
                  </label>
                ))}
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Reach Detail</label>
              <div className="radio-group">
                {(config.reach_details ?? []).map((rd) => (
                  <label key={rd} className="radio-label">
                    <input
                      type="radio"
                      name="reach_detail"
                      value={rd}
                      checked={reachDetail === rd}
                      onChange={() => setReachDetail(rd)}
                    />
                    {formatLabel(rd)}
                  </label>
                ))}
              </div>
            </div>

            <div className="form-field">
              <label className="checkbox-label foot-cut-label">
                <input
                  type="checkbox"
                  checked={footCut}
                  onChange={(e) => setFootCut(e.target.checked)}
                />
                Foot Cut (feet came off during move)
              </label>
            </div>

            <div className="form-field">
              <label className="form-label">Confidence</label>
              <div className="radio-group">
                {(config.confidence_levels ?? []).map((c) => (
                  <label key={c} className="radio-label">
                    <input
                      type="radio"
                      name="confidence"
                      value={c}
                      checked={confidence === c}
                      onChange={() => setConfidence(c)}
                    />
                    {formatLabel(c)}
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="move-form-footer">
          <button onClick={handleClose} className="btn-secondary">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            className="btn-primary"
            disabled={loading}
          >
            {loading ? 'Saving...' : 'Save Move'}
          </button>
        </div>
      </div>
    </div>
  );
}

// Helper function for formatting labels
function formatLabel(str) {
  return str
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export default MoveForm;
