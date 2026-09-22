/**
 * The three lenses as reusable field groups.
 *
 * Extracted from MoveForm so the rating view (Dataset A) renders the very
 * same Environment and Outcome controls a labeler sees when creating a move,
 * without duplicating them. MoveForm keeps owning its state and validation;
 * these components are presentational and take values plus callbacks.
 *
 * `StrategySummary` is the read-only face of Lens 2 for raters: the canonical
 * move's values, displayed, never edited.
 */
import { HOLD_SLOT_KEYS } from '../store/useStore';
import { optionLabel, optionDescription, formatLabel } from '../utils/taxonomy';
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
    <div className="lens-section">
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
    <div className="lens-section">
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
 * Lens 2, read-only: the canonical move as the prepper defined it. Raters
 * see this and never change it — Strategy is what makes three ratings of the
 * same move comparable.
 */
export function StrategySummary({ config, move }) {
  if (!move) return null;
  const tags = (move.move_tags ?? []).map((t) => optionLabel(config, 'move_tags', t));
  return (
    <div className="lens-section strategy-summary" data-testid="strategy-summary">
      <h3 className="lens-title">
        🎯 Strategy <span className="readonly-flag">canonical — read only</span>
      </h3>
      <dl className="strategy-summary-grid">
        <dt>Approach</dt>
        <dd>{optionLabel(config, 'approaches', move.approach) || '—'}</dd>
        <dt>Size</dt>
        <dd>{optionLabel(config, 'sizes', move.size) || '—'}</dd>
        <dt>Move tags</dt>
        <dd>{tags.length ? tags.join(', ') : 'none'}</dd>
        <dt>Form quality</dt>
        <dd>{move.form_quality != null ? `${move.form_quality} / 5` : '—'}</dd>
        <dt>Effort</dt>
        <dd>{move.effort_level != null ? `${move.effort_level} / 10` : '—'}</dd>
        <dt>Prepper confidence</dt>
        <dd>{optionLabel(config, 'confidence_levels', move.confidence) || formatLabel(move.confidence) || '—'}</dd>
        {move.description && (
          <>
            <dt>Notes</dt>
            <dd>{move.description}</dd>
          </>
        )}
      </dl>
    </div>
  );
}
