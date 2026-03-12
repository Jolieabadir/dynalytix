/**
 * MoveForm component.
 * 
 * Two-step form for creating/editing moves:
 * 1. Select move type
 * 2. Contextual questions + technique modifiers + quality/effort/tags
 */
import { useState, useEffect } from 'react';
import useStore from '../store/useStore';
import { createMove, getConfig } from '../api/client';

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

  const [step, setStep] = useState(1);
  const [config, setConfig] = useState(null);
  
  // Form state
  const [moveType, setMoveType] = useState('');
  const [contextualData, setContextualData] = useState({});
  const [techniqueModifiers, setTechniqueModifiers] = useState([]);
  const [formQuality, setFormQuality] = useState(3);
  const [effortLevel, setEffortLevel] = useState(5);
  const [tags, setTags] = useState([]);
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

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
      setStep(1);
      setMoveType('');
      setContextualData({});
      setTechniqueModifiers([]);
      setFormQuality(3);
      setEffortLevel(5);
      setTags([]);
      setDescription('');
      setError(null);
    }
  }, [showMoveForm]);

  const handleClose = () => {
    setShowMoveForm(false);
  };

  const handleNext = () => {
    if (!moveType) {
      setError('Please select a move type');
      return;
    }
    setStep(2);
    setError(null);
  };

  const handleBack = () => {
    setStep(1);
    setError(null);
  };

  const handleContextualChange = (field, value) => {
    setContextualData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const handleMultiSelectToggle = (field, option) => {
    const current = contextualData[field] || [];
    const updated = current.includes(option)
      ? current.filter(o => o !== option)
      : [...current, option];
    handleContextualChange(field, updated);
  };

  const toggleTechniqueModifier = (modifierId) => {
    setTechniqueModifiers(prev =>
      prev.includes(modifierId)
        ? prev.filter(m => m !== modifierId)
        : [...prev, modifierId]
    );
  };

  const toggleTag = (tag) => {
    setTags(prev =>
      prev.includes(tag)
        ? prev.filter(t => t !== tag)
        : [...prev, tag]
    );
  };

  const handleSubmit = async () => {
    if (!currentVideo || moveStart === null || moveEnd === null) {
      setError('Invalid move boundaries');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const fps = currentVideo.fps;
      const moveData = {
        video_id: currentVideo.id,
        frame_start: moveStart,
        frame_end: moveEnd,
        timestamp_start_ms: (moveStart / fps) * 1000,
        timestamp_end_ms: (moveEnd / fps) * 1000,
        move_type: moveType,
        form_quality: formQuality,
        effort_level: effortLevel,
        contextual_data: contextualData,
        technique_modifiers: techniqueModifiers,
        tags: tags,
        description: description,
      };

      const createdMove = await createMove(moveData);
      addMove(createdMove);
      clearMoveSelection();
      setShowMoveForm(false);
    } catch (err) {
      console.error('Failed to create move:', err);
      setError(err.response?.data?.detail || 'Failed to create move');
    } finally {
      setLoading(false);
    }
  };

  if (!showMoveForm) return null;
  if (!config) return <div className="move-form-loading">Loading...</div>;

  const currentQuestions = moveType ? config.move_type_questions[moveType] : null;

  return (
    <div className="move-form-overlay">
      <div className="move-form-modal">
        <div className="move-form-header">
          <h2>
            {step === 1 ? 'Select Move Type' : `Define ${formatMoveType(moveType)}`}
          </h2>
          <button onClick={handleClose} className="close-btn">✕</button>
        </div>

        <div className="move-form-content">
          {error && (
            <div className="error-message">{error}</div>
          )}

          {step === 1 && (
            <Step1SelectType
              moveTypes={config.move_types}
              moveType={moveType}
              setMoveType={setMoveType}
              moveStart={moveStart}
              moveEnd={moveEnd}
              fps={currentVideo?.fps || 30}
            />
          )}

          {step === 2 && (
            <Step2Details
              moveType={moveType}
              questions={currentQuestions}
              contextualData={contextualData}
              onContextualChange={handleContextualChange}
              onMultiSelectToggle={handleMultiSelectToggle}
              techniqueModifiers={techniqueModifiers}
              availableModifiers={config.technique_modifiers || []}
              toggleTechniqueModifier={toggleTechniqueModifier}
              formQuality={formQuality}
              setFormQuality={setFormQuality}
              effortLevel={effortLevel}
              setEffortLevel={setEffortLevel}
              tags={tags}
              toggleTag={toggleTag}
              description={description}
              setDescription={setDescription}
            />
          )}
        </div>

        <div className="move-form-footer">
          {step === 1 ? (
            <>
              <button onClick={handleClose} className="btn-secondary">
                Cancel
              </button>
              <button onClick={handleNext} className="btn-primary">
                Next →
              </button>
            </>
          ) : (
            <>
              <button onClick={handleBack} className="btn-secondary">
                ← Back
              </button>
              <button 
                onClick={handleSubmit} 
                className="btn-primary"
                disabled={loading}
              >
                {loading ? 'Saving...' : 'Save Move'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// Step 1: Select move type
function Step1SelectType({ moveTypes, moveType, setMoveType, moveStart, moveEnd, fps }) {
  const duration = moveEnd && moveStart ? ((moveEnd - moveStart) / fps).toFixed(2) : 0;
  const frameCount = moveEnd && moveStart ? moveEnd - moveStart : 0;

  return (
    <div className="step-1">
      <div className="move-info">
        <p>Frames: {moveStart} - {moveEnd} ({frameCount} frames, {duration}s)</p>
      </div>

      <label className="form-label">Move Type</label>
      <select
        value={moveType}
        onChange={(e) => setMoveType(e.target.value)}
        className="move-type-select"
      >
        <option value="">Select move type...</option>
        {moveTypes.map(type => (
          <option key={type} value={type}>
            {formatMoveType(type)}
          </option>
        ))}
      </select>
    </div>
  );
}

// Step 2: Contextual questions + technique modifiers + quality/effort/tags
function Step2Details({
  moveType,
  questions,
  contextualData,
  onContextualChange,
  onMultiSelectToggle,
  techniqueModifiers,
  availableModifiers,
  toggleTechniqueModifier,
  formQuality,
  setFormQuality,
  effortLevel,
  setEffortLevel,
  tags,
  toggleTag,
  description,
  setDescription,
}) {
  const commonTags = [
    'tweaky_feeling',
    'flash_pump',
    'good_technique',
    'controlled'
  ];

  return (
    <div className="step-2">
      {/* Contextual Questions */}
      {questions && Object.entries(questions).map(([fieldKey, fieldConfig]) => (
        <div key={fieldKey} className="form-field">
          <label className="form-label">{fieldConfig.question}</label>
          
          {fieldConfig.multi_select ? (
            // Multi-select: checkboxes
            <div className="checkbox-group">
              {fieldConfig.options.map(option => (
                <label key={option} className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={(contextualData[fieldKey] || []).includes(option)}
                    onChange={() => onMultiSelectToggle(fieldKey, option)}
                  />
                  {formatOption(option)}
                </label>
              ))}
            </div>
          ) : (
            // Single select: radio buttons
            <div className="radio-group">
              {fieldConfig.options.map(option => (
                <label key={option} className="radio-label">
                  <input
                    type="radio"
                    name={fieldKey}
                    value={option}
                    checked={contextualData[fieldKey] === option}
                    onChange={() => onContextualChange(fieldKey, option)}
                  />
                  {formatOption(option)}
                </label>
              ))}
            </div>
          )}
        </div>
      ))}

      {/* Technique Modifiers - applicable to ALL move types */}
      {availableModifiers && availableModifiers.length > 0 && (
        <div className="form-field">
          <label className="form-label">Technique Modifiers (optional)</label>
          <div className="tags-group">
            {availableModifiers.map(modifier => (
              <button
                key={modifier.id}
                type="button"
                onClick={() => toggleTechniqueModifier(modifier.id)}
                className={`tag-btn ${techniqueModifiers.includes(modifier.id) ? 'active' : ''}`}
                title={modifier.description}
              >
                {modifier.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Form Quality */}
      <div className="form-field">
        <label className="form-label">Form Quality</label>
        <div className="quality-buttons">
          {[1, 2, 3, 4, 5].map(q => (
            <button
              key={q}
              type="button"
              onClick={() => setFormQuality(q)}
              className={`quality-btn ${formQuality === q ? 'active' : ''}`}
            >
              {q}
            </button>
          ))}
        </div>
        <div className="quality-labels">
          <span>Poor</span>
          <span>Perfect</span>
        </div>
      </div>

      {/* Effort Level */}
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

      {/* Tags */}
      <div className="form-field">
        <label className="form-label">Tags (optional)</label>
        <div className="tags-group">
          {commonTags.map(tag => (
            <button
              key={tag}
              type="button"
              onClick={() => toggleTag(tag)}
              className={`tag-btn ${tags.includes(tag) ? 'active' : ''}`}
            >
              {formatTag(tag)}
            </button>
          ))}
        </div>
      </div>

      {/* Description */}
      <div className="form-field">
        <label className="form-label">Description (optional)</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value.slice(0, 500))}
          placeholder="Add notes about this move..."
          className="description-textarea"
          rows="3"
        />
        <div className="char-count">{description.length}/500</div>
      </div>
    </div>
  );
}

// Helper functions for formatting
function formatMoveType(type) {
  return type
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function formatOption(option) {
  return option
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function formatTag(tag) {
  return tag
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export default MoveForm;
