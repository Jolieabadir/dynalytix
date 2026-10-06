/**
 * The three lenses as reusable field groups.
 *
 * Extracted from MoveForm so the rating view renders the very same
 * Environment, Strategy and Outcome controls (with the same definitions and
 * tooltips) a prepper sees when creating a move, without duplicating them.
 * The forms keep owning their state and validation; these components are
 * presentational and take values plus callbacks.
 */
import { HOLD_SLOT_KEYS } from '../store/useStore';
import { optionLabel, optionDescription } from '../utils/taxonomy';
import { FORM_QUALITY_LABELS } from '../utils/strategy';
import InfoTip from './InfoTip';

export const SLOT_ORDER = HOLD_SLOT_KEYS;

/** One radio group, every option with its definition. */
export function RadioGroup({ config, taxonomyKey, name, value, onChange, options, disabled }) {
  return (
    <div className="radio-group">
      {(options ?? config[taxonomyKey] ?? []).map((opt) => (
        <label key={opt} className="radio-label">
          <input
            type="radio"
            name={name}
            value={opt}
            checked={value === opt}
            onChange={() => onChange(opt)}
            disabled={disabled}
          />
          <span>{optionLabel(config, taxonomyKey, opt)}</span>
          <InfoTip text={optionDescription(config, taxonomyKey, opt)} />
        </label>
      ))}
    </div>
  );
}

/**
 * Lens 1: wall angle plus the four hold slots.
 *
 * When `holds` is given, each slot also offers a dropdown of the video's
 * holds — the rating view passes the locked canonical set, so a rater can
 * only ever point a slot at a hold that exists on the video.
 */
export function EnvironmentLens({
  config,
  wallAngle,
  onWallAngle,
  slots,
  holdPickSlot,
  onPickSlot,
  onUpdateSlot,
  onToggleQuality,
  onClearSlot,
  noHands = false,
  holds = null,
  disabled = false,
}) {
  return (
    <div className="lens-section" data-testid="environment-lens">
      <h3 className="lens-title">🏔️ Environment</h3>

      <div className="form-field">
        <label className="form-label">Wall Angle</label>
        <RadioGroup
          config={config}
          taxonomyKey="wall_angles"
          name="wall_angle"
          value={wallAngle}
          onChange={onWallAngle}
          disabled={disabled}
        />
      </div>

      {noHands && (
        <p className="field-disabled-note">
          Hand holds are disabled — “No Hands” is tagged for this move.
        </p>
      )}

      {SLOT_ORDER.map((slot) => {
        const isHandSlot = slot !== 'foot';
        if (noHands && isHandSlot) return null;
        const s = slots[slot];
        const picking = holdPickSlot?.slot === slot;

        return (
          <fieldset key={slot} className="hold-slot" data-testid={`hold-slot-${slot}`} disabled={disabled}>
            <legend className="hold-slot-legend">
              {optionLabel(config, 'hold_slots', slot)}
              {slot === 'foot' && <span className="optional-flag"> (optional)</span>}
              <InfoTip text={optionDescription(config, 'hold_slots', slot)} />
              {s.suggested && (
                <span
                  className="suggested-flag"
                  title="Auto-suggested from the pose data — confirm or change it"
                >
                  suggested
                </span>
              )}
            </legend>

            <div className="hold-slot-pick">
              <button
                type="button"
                className={`pick-on-video-btn ${picking ? 'active' : ''}`}
                onClick={() => onPickSlot(picking ? null : { slot, assignedHoldId: null })}
              >
                {picking ? 'Click a box on the video…' : 'Pick on video'}
              </button>
              {Array.isArray(holds) && (
                <select
                  className="hold-select"
                  aria-label={`Hold for ${optionLabel(config, 'hold_slots', slot)}`}
                  value={s.hold_id ?? ''}
                  onChange={(e) =>
                    onUpdateSlot(slot, {
                      hold_id: e.target.value === '' ? null : Number(e.target.value),
                    })
                  }
                >
                  <option value="">No hold chosen</option>
                  {holds.map((hold) => (
                    <option key={hold.id} value={hold.id}>
                      Hold #{hold.id}
                    </option>
                  ))}
                </select>
              )}
              {s.hold_id != null && (
                <span className="picked-hold">
                  Hold #{s.hold_id}
                  <button
                    type="button"
                    className="unpick-btn"
                    onClick={() => onUpdateSlot(slot, { hold_id: null })}
                    aria-label={`Unassign the hold from ${slot}`}
                  >
                    ✕
                  </button>
                </span>
              )}
            </div>

            <div className="form-field">
              <label className="form-label">Hold Type</label>
              <div className="radio-group">
                {(config.hold_types ?? []).map((type) => (
                  <label key={type} className="radio-label">
                    <input
                      type="radio"
                      name={`${slot}_hold_type`}
                      value={type}
                      checked={s.hold_type === type}
                      onChange={() => onUpdateSlot(slot, { hold_type: type })}
                    />
                    <span>{optionLabel(config, 'hold_types', type)}</span>
                    <InfoTip text={optionDescription(config, 'hold_types', type)} />
                  </label>
                ))}
              </div>
            </div>

            <div className="form-field">
              <label className="form-label">Hold Quality</label>
              <div className="checkbox-group">
                {(config.hold_qualities ?? []).map((quality) => (
                  <label key={quality} className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={(s.hold_quality || []).includes(quality)}
                      onChange={() => onToggleQuality(slot, quality)}
                    />
                    <span>{optionLabel(config, 'hold_qualities', quality)}</span>
                    <InfoTip text={optionDescription(config, 'hold_qualities', quality)} />
                  </label>
                ))}
              </div>
            </div>

            <button type="button" className="clear-slot-btn" onClick={() => onClearSlot(slot)}>
              Clear this slot
            </button>
          </fieldset>
        );
      })}
    </div>
  );
}

/** Lens 3: result, reach detail, and the labeler's confidence. */
export function OutcomeLens({
  config,
  result,
  onResult,
  reachDetail,
  onReachDetail,
  confidence,
  onConfidence,
  disabled = false,
}) {
  return (
    <div className="lens-section" data-testid="outcome-lens">
      <h3 className="lens-title">📊 Outcome</h3>

      <div className="form-field">
        <label className="form-label">Result</label>
        <RadioGroup
          config={config}
          taxonomyKey="results"
          name="result"
          value={result}
          onChange={onResult}
          disabled={disabled}
        />
      </div>

      <div className="form-field">
        <label className="form-label">Reach Detail</label>
        <RadioGroup
          config={config}
          taxonomyKey="reach_details"
          name="reach_detail"
          value={reachDetail}
          onChange={onReachDetail}
          disabled={disabled}
        />
      </div>

      <div className="form-field">
        <label className="form-label">
          Confidence
          <InfoTip text="How confident you are in the labels you just gave — not how confident the climber looked." />
        </label>
        <RadioGroup
          config={config}
          taxonomyKey="confidence_levels"
          name="confidence"
          value={confidence}
          onChange={onConfidence}
          disabled={disabled}
        />
      </div>
    </div>
  );
}

/**
 * Lens 2: approach, size, move tags, form quality — and, only where the
 * caller passes them, effort, a strategy confidence and a free-text note.
 *
 * MoveForm (prep) passes effort + description; the rating view passes a
 * confidence and no effort: raters label only what is observable, so
 * effort_level is never shown to them.
 */
export function StrategyLens({
  config,
  approach,
  onApproach,
  size,
  onSize,
  moveTags,
  onToggleTag,
  formQuality,
  onFormQuality,
  effortLevel,
  onEffortLevel = null,
  confidence,
  onConfidence = null,
  description,
  onDescription = null,
  disabled = false,
}) {
  return (
    <div className="lens-section" data-testid="strategy-lens">
      <h3 className="lens-title">🎯 Strategy</h3>

      <div className="form-field">
        <label className="form-label">Approach</label>
        <RadioGroup
          config={config}
          taxonomyKey="approaches"
          name="approach"
          value={approach}
          onChange={onApproach}
          disabled={disabled}
        />
      </div>

      <div className="form-field">
        <label className="form-label">
          Size
          <InfoTip text="How big the movement is — not the size of the hold." />
        </label>
        <RadioGroup
          config={config}
          taxonomyKey="sizes"
          name="size"
          value={size}
          onChange={onSize}
          disabled={disabled}
        />
      </div>

      <div className="form-field">
        <label className="form-label">Move Tags (multi-select)</label>
        <div className="tags-group">
          {(config.move_tags ?? []).map((tag) => {
            const blocked =
              (tag === 'no_feet_on' && moveTags.includes('no_hands')) ||
              (tag === 'no_hands' && moveTags.includes('no_feet_on'));
            const active = moveTags.includes(tag);
            return (
              <span key={tag} className="tag-with-info">
                <button
                  type="button"
                  onClick={() => onToggleTag(tag)}
                  className={`tag-btn ${active ? 'active' : ''} ${blocked ? 'disabled-mutual' : ''}`}
                  aria-pressed={active}
                  disabled={disabled || blocked}
                >
                  {optionLabel(config, 'move_tags', tag)}
                </button>
                <InfoTip text={optionDescription(config, 'move_tags', tag)} />
              </span>
            );
          })}
        </div>
      </div>

      <div className="form-field">
        <label className="form-label">Form Quality</label>
        <div className="quality-buttons" role="group" aria-label="Form quality">
          {[1, 2, 3, 4, 5].map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => onFormQuality(q)}
              className={`quality-btn ${formQuality === q ? 'active' : ''}`}
              title={FORM_QUALITY_LABELS[q]}
              aria-pressed={formQuality === q}
              disabled={disabled}
            >
              {q}
            </button>
          ))}
        </div>
        <div className="quality-description">
          {formQuality != null ? FORM_QUALITY_LABELS[formQuality] : 'Pick 1–5'}
        </div>
      </div>

      {onEffortLevel && (
        <div className="form-field">
          <label className="form-label">Effort Level: {effortLevel}/10</label>
          <input
            type="range"
            min="0"
            max="10"
            value={effortLevel}
            onChange={(e) => onEffortLevel(Number(e.target.value))}
            className="effort-slider"
            disabled={disabled}
          />
          <div className="effort-labels">
            <span>Easy</span>
            <span>Max Effort</span>
          </div>
        </div>
      )}

      {onConfidence && (
        <div className="form-field">
          <label className="form-label">
            Strategy confidence (optional)
            <InfoTip text="How confident you are in the Strategy labels above — not how confident the climber looked." />
          </label>
          <RadioGroup
            config={config}
            taxonomyKey="confidence_levels"
            name="strategy_confidence"
            value={confidence}
            onChange={onConfidence}
            disabled={disabled}
          />
        </div>
      )}

      {onDescription && (
        <div className="form-field">
          <label className="form-label">Description (optional)</label>
          <textarea
            value={description}
            onChange={(e) => onDescription(e.target.value.slice(0, 500))}
            placeholder="Add notes about this move…"
            className="description-textarea"
            rows="2"
            disabled={disabled}
          />
        </div>
      )}
    </div>
  );
}
