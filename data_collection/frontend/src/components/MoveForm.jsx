/**
 * AssessmentForm component.
 *
 * Form for creating FMS (Functional Movement Screen) assessments.
 * Simplified single-step form for deep squat assessment with FMS 0-3 scoring.
 *
 * Supports Quick Mode (default) for rapid scoring with just score + pain + notes,
 * or Full Mode for detailed criteria and compensation pattern documentation.
 */
import { useState, useEffect } from 'react';
import useStore from '../store/useStore';
import { createAssessment, getConfig } from '../api/client';

// FMS Score definitions
const FMS_SCORE_OPTIONS = [
  { value: 3, label: 'Perfect', description: 'Performs movement correctly without compensation', color: '#22c55e' },
  { value: 2, label: 'Compensation', description: 'Completes movement with compensation patterns', color: '#eab308' },
  { value: 1, label: 'Cannot Complete', description: 'Unable to complete the movement pattern', color: '#f97316' },
  { value: 0, label: 'Pain', description: 'Pain reported during any part of the movement', color: '#ef4444' },
];

// localStorage key for Quick Mode preference
const QUICK_MODE_KEY = 'fms_quick_mode';

function MoveForm() {
  const {
    currentVideo,
    moveStart,
    moveEnd,
    showMoveForm,
    setShowMoveForm,
    clearMoveSelection,
    addMove,
  } = useStore();

  const [config, setConfig] = useState(null);

  // Quick Mode state - default to true, load from localStorage
  const [quickMode, setQuickMode] = useState(() => {
    const saved = localStorage.getItem(QUICK_MODE_KEY);
    return saved !== null ? JSON.parse(saved) : true;
  });

  // Form state
  const [score, setScore] = useState(2);
  const [painReported, setPainReported] = useState(false);
  const [criteriaData, setCriteriaData] = useState({});
  const [compensations, setCompensations] = useState([]);
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Save Quick Mode preference to localStorage
  const handleQuickModeToggle = () => {
    const newValue = !quickMode;
    setQuickMode(newValue);
    localStorage.setItem(QUICK_MODE_KEY, JSON.stringify(newValue));
  };

  // Handle pain checkbox in Quick Mode
  const handlePainToggle = () => {
    const newPainValue = !painReported;
    setPainReported(newPainValue);
    if (newPainValue) {
      setScore(0);
    }
  };

  // Load configuration
  useEffect(() => {
    const loadConfig = async () => {
      try {
        const configData = await getConfig();
        setConfig(configData);
      } catch (err) {
        console.error('Failed to load config:', err);
        setError('Failed to load form configuration');
      }
    };
    if (showMoveForm && !config) {
      loadConfig();
    }
  }, [showMoveForm, config]);

  // Reset form when opened
  useEffect(() => {
    if (showMoveForm) {
      setScore(2);
      setPainReported(false);
      setCriteriaData({});
      setCompensations([]);
      setNotes('');
      setError(null);
    }
  }, [showMoveForm]);

  const handleClose = () => {
    setShowMoveForm(false);
  };

  const handleCriteriaChange = (field, value) => {
    setCriteriaData(prev => ({
      ...prev,
      [field]: value
    }));

    // Auto-set score to 0 if pain is reported
    if (field === 'pain_reported' && value === 'pain') {
      setScore(0);
    }
  };

  const toggleCompensation = (compensationId) => {
    setCompensations(prev =>
      prev.includes(compensationId)
        ? prev.filter(c => c !== compensationId)
        : [...prev, compensationId]
    );
  };

  const handleSubmit = async () => {
    if (!currentVideo || moveStart === null || moveEnd === null) {
      setError('Invalid assessment boundaries');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const fps = currentVideo.fps;
      const assessmentData = {
        video_id: currentVideo.id,
        frame_start: moveStart,
        frame_end: moveEnd,
        timestamp_start_ms: (moveStart / fps) * 1000,
        timestamp_end_ms: (moveEnd / fps) * 1000,
        test_type: 'deep_squat',
        score: score,
        criteria_data: criteriaData,
        compensations: compensations,
        tags: [],
        notes: notes,
      };

      const createdAssessment = await createAssessment(assessmentData);
      addMove(createdAssessment);
      clearMoveSelection();
      setShowMoveForm(false);
    } catch (err) {
      console.error('Failed to create assessment:', err);
      setError(err.response?.data?.detail || 'Failed to create assessment');
    } finally {
      setLoading(false);
    }
  };

  if (!showMoveForm) return null;
  if (!config) return <div className="move-form-loading">Loading...</div>;

  const duration = moveEnd && moveStart ? ((moveEnd - moveStart) / (currentVideo?.fps || 30)).toFixed(2) : 0;
  const frameCount = moveEnd && moveStart ? moveEnd - moveStart : 0;
  const scoringCriteria = config.fms_scoring_criteria?.deep_squat || {};
  const compensationPatterns = config.compensation_patterns || [];

  return (
    <div className="move-form-overlay">
      <div className="move-form-modal">
        <div className="move-form-header">
          <h2>FMS Deep Squat Assessment</h2>
          <button onClick={handleClose} className="close-btn">✕</button>
        </div>

        <div className="move-form-content">
          {error && (
            <div className="error-message">{error}</div>
          )}

          {/* Quick Mode Toggle */}
          <div className="quick-mode-toggle">
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={quickMode}
                onChange={handleQuickModeToggle}
              />
              <span className="toggle-slider"></span>
            </label>
            <span className="toggle-label">
              Quick Mode
              <span className="toggle-hint">
                {quickMode ? '(Score + Pain + Notes only)' : '(Full detailed form)'}
              </span>
            </span>
          </div>

          {/* Assessment Info */}
          <div className="move-info">
            <p>Frames: {moveStart} - {moveEnd} ({frameCount} frames, {duration}s)</p>
          </div>

          {/* FMS Score Selection */}
          <div className="form-field">
            <label className="form-label">FMS Score</label>
            <div className="fms-score-buttons">
              {FMS_SCORE_OPTIONS.map(option => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => {
                    setScore(option.value);
                    if (option.value === 0) {
                      setPainReported(true);
                    } else if (painReported && option.value !== 0) {
                      setPainReported(false);
                    }
                  }}
                  className={`fms-score-btn ${score === option.value ? 'active' : ''}`}
                  style={{
                    '--score-color': option.color,
                    borderColor: score === option.value ? option.color : undefined,
                    backgroundColor: score === option.value ? `${option.color}20` : undefined,
                  }}
                >
                  <span className="score-value">{option.value}</span>
                  <span className="score-label">{option.label}</span>
                </button>
              ))}
            </div>
            <p className="score-description">
              {FMS_SCORE_OPTIONS.find(o => o.value === score)?.description}
            </p>
          </div>

          {/* Quick Mode: Pain Checkbox */}
          {quickMode && (
            <div className="form-field pain-checkbox-field">
              <label className="checkbox-label pain-checkbox">
                <input
                  type="checkbox"
                  checked={painReported}
                  onChange={handlePainToggle}
                />
                <span className="pain-label">Pain reported during movement</span>
              </label>
              {painReported && (
                <p className="pain-warning">Score automatically set to 0 when pain is reported</p>
              )}
            </div>
          )}

          {/* Full Mode: Scoring Criteria */}
          {!quickMode && (
            <div className="form-field">
              <label className="form-label">Scoring Criteria Observations</label>
              {Object.entries(scoringCriteria).map(([fieldKey, fieldConfig]) => (
                <div key={fieldKey} className="criteria-field">
                  <label className="criteria-label">{fieldConfig.question}</label>
                  <div className="radio-group horizontal">
                    {fieldConfig.options.map(option => (
                      <label key={option} className="radio-label compact">
                        <input
                          type="radio"
                          name={fieldKey}
                          value={option}
                          checked={criteriaData[fieldKey] === option}
                          onChange={() => handleCriteriaChange(fieldKey, option)}
                        />
                        {formatOption(option)}
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Full Mode: Compensation Patterns */}
          {!quickMode && (
            <div className="form-field">
              <label className="form-label">Compensation Patterns Observed</label>
              <div className="compensation-group">
                {compensationPatterns.map(pattern => (
                  <label key={pattern.id} className="checkbox-label compensation">
                    <input
                      type="checkbox"
                      checked={compensations.includes(pattern.id)}
                      onChange={() => toggleCompensation(pattern.id)}
                    />
                    <span className="compensation-info">
                      <span className="compensation-name">{pattern.label}</span>
                      <span className="compensation-desc">{pattern.description}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* Notes */}
          <div className="form-field">
            <label className="form-label">{quickMode ? 'Notes (optional)' : 'Clinical Notes (optional)'}</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value.slice(0, 500))}
              placeholder="Add observations about this assessment..."
              className="description-textarea"
              rows={quickMode ? 2 : 3}
            />
            <div className="char-count">{notes.length}/500</div>
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
            {loading ? 'Saving...' : 'Save Assessment'}
          </button>
        </div>
      </div>
    </div>
  );
}

// Helper function for formatting options
function formatOption(option) {
  return option
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export default MoveForm;
