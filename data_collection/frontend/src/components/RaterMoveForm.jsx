/**
 * RaterMoveForm — the three-lens panel for one canonical move.
 *
 * The canonical move only fixes the boundaries. Strategy, Environment and
 * Outcome are all the rater's own rows: loaded with GET (the API only ever
 * returns the caller's), created with POST the first time, updated with PUT
 * after that. Strategy uses the same field group as the prep MoveForm, minus
 * effort: raters label only what is observable (effort_level is never shown).
 *
 * Hold slots can only point at the video's locked holds — via "Pick on
 * video" or the dropdown, both fed from the same list. Nothing is pre-filled
 * from the pose data: an auto-suggested hold would anchor every rater on the
 * same guess and inflate agreement, so raters pick each hold themselves.
 *
 * `locked` (assignment done, or video closed) shows the saved values with
 * every control disabled: the API answers 403 to writes at that point.
 */
import { useEffect, useState } from 'react';
import useStore, { HOLD_SLOT_KEYS } from '../store/useStore';
import { optionLabel } from '../utils/taxonomy';
import { EnvironmentLens, OutcomeLens, StrategyLens } from './LensFields';
import { toggleMoveTagValue } from '../utils/strategy';
import {
  getStrategyForMove,
  createStrategy,
  updateStrategy,
  getEnvironmentForMove,
  getOutcomeForMove,
  createEnvironment,
  updateEnvironment,
  createOutcome,
  updateOutcome,
} from '../api/client';

const EMPTY_SLOT = { hold_id: null, hold_type: '', hold_quality: [] };
const REQUIRED_SLOTS = ['start_left', 'start_right', 'end'];

function slotsFromEnvironment(env, prefill) {
  return Object.fromEntries(
    HOLD_SLOT_KEYS.map((slot) => {
      const source = env?.[slot] ?? prefill?.[slot] ?? {};
      return [
        slot,
        {
          ...EMPTY_SLOT,
          // A prefill never carries a hold id (different move, different holds).
          hold_id: env ? (source.hold_id ?? null) : null,
          hold_type: source.hold_type || '',
          hold_quality: source.hold_quality || [],
        },
      ];
    })
  );
}

function RaterMoveForm({ move, moveIndex, onClose, onSaved, locked = false }) {
  const {
    config,
    holds,
    holdPickSlot,
    setHoldPickSlot,
    previousEnvironment,
    setPreviousEnvironment,
  } = useStore();

  const [loadingExisting, setLoadingExisting] = useState(true);
  const [existingStrategy, setExistingStrategy] = useState(null);
  const [existingEnv, setExistingEnv] = useState(null);
  const [existingOutcome, setExistingOutcome] = useState(null);

  // Lens 2: the rater's own Strategy. Form quality starts unset (not 3) so
  // no rater is anchored on a default.
  const [approach, setApproach] = useState('');
  const [size, setSize] = useState('');
  const [moveTags, setMoveTags] = useState([]);
  const [formQuality, setFormQuality] = useState(null);
  const [strategyConfidence, setStrategyConfidence] = useState('');

  const [wallAngle, setWallAngle] = useState('');
  const [slots, setSlots] = useState(() => slotsFromEnvironment(null, null));
  const [result, setResult] = useState('');
  const [reachDetail, setReachDetail] = useState('');
  const [confidence, setConfidence] = useState('');

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [savedNote, setSavedNote] = useState(null);

  // The rater's own tags, not the prepper's: No Hands hides the hand slots.
  const noHands = moveTags.includes('no_hands');

  // Load this rater's rows for the move. A 404 is "nothing yet" and the form
  // starts from the previous move's environment, like MoveForm does.
  useEffect(() => {
    let active = true;
    setLoadingExisting(true);
    setError(null);
    setSavedNote(null);
    setHoldPickSlot(null);

    Promise.all([
      getStrategyForMove(move.id),
      getEnvironmentForMove(move.id),
      getOutcomeForMove(move.id),
    ])
      .then(([strategy, env, outcome]) => {
        if (!active) return;
        setExistingStrategy(strategy);
        setExistingEnv(env);
        setExistingOutcome(outcome);
        setApproach(strategy?.approach || '');
        setSize(strategy?.size || '');
        setMoveTags(strategy?.move_tags || []);
        setFormQuality(strategy?.form_quality ?? null);
        setStrategyConfidence(strategy?.confidence || '');
        setWallAngle(env?.wall_angle || previousEnvironment.wall_angle || '');
        // Hold ids are never pre-filled (see the header comment).
        setSlots(slotsFromEnvironment(env, env ? null : previousEnvironment));
        setResult(outcome?.result || '');
        setReachDetail(outcome?.reach_detail || '');
        setConfidence(outcome?.confidence || '');
      })
      .catch((err) => {
        if (!active) return;
        setError(err.response?.data?.detail || err.message || 'Could not load your labels for this move.');
      })
      .finally(() => active && setLoadingExisting(false));

    return () => {
      active = false;
    };
    // Reload only when the move changes; prefill/holds are read at open time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [move.id]);

  // A hold picked on the video lands in whichever slot asked for it.
  useEffect(() => {
    if (!holdPickSlot) return;
    const assignedId = holdPickSlot.assignedHoldId;
    if (assignedId == null) return;
    setSlots((prev) => ({
      ...prev,
      [holdPickSlot.slot]: { ...prev[holdPickSlot.slot], hold_id: assignedId },
    }));
    setHoldPickSlot(null);
  }, [holdPickSlot, setHoldPickSlot]);

  const updateSlot = (slot, patch) =>
    setSlots((prev) => ({ ...prev, [slot]: { ...prev[slot], ...patch } }));

  const toggleSlotQuality = (slot, quality) =>
    setSlots((prev) => {
      const current = prev[slot].hold_quality || [];
      return {
        ...prev,
        [slot]: {
          ...prev[slot],
          hold_quality: current.includes(quality)
            ? current.filter((q) => q !== quality)
            : [...current, quality],
        },
      };
    });

  const clearSlot = (slot) => setSlots((prev) => ({ ...prev, [slot]: { ...EMPTY_SLOT } }));

  const handleClose = () => {
    setHoldPickSlot(null);
    onClose();
  };

  const toggleMoveTag = (tag) => setMoveTags((prev) => toggleMoveTagValue(prev, tag));

  const handleSave = async () => {
    if (locked) return;
    if (!approach || !size) {
      setError('Please select Approach and Size');
      return;
    }
    if (formQuality == null) {
      setError('Please choose a Form Quality (1–5)');
      return;
    }
    if (!wallAngle) {
      setError('Please select Wall Angle');
      return;
    }
    if (!noHands) {
      const missing = REQUIRED_SLOTS.filter((s) => !slots[s].hold_type);
      if (missing.length) {
        setError(
          `Please choose a hold type for: ${missing
            .map((s) => optionLabel(config, 'hold_slots', s))
            .join(', ')}`
        );
        return;
      }
    }
    if (!result || !reachDetail || !confidence) {
      setError('Please complete all Outcome fields');
      return;
    }

    setSaving(true);
    setError(null);
    setSavedNote(null);
    try {
      const slotPayload = Object.fromEntries(
        HOLD_SLOT_KEYS.map((slot) => {
          const s = slots[slot];
          const isHandSlot = slot !== 'foot';
          if (noHands && isHandSlot) return [slot, {}];
          if (!s.hold_type && s.hold_id == null) return [slot, {}];
          return [
            slot,
            { hold_id: s.hold_id ?? null, hold_type: s.hold_type || null, hold_quality: s.hold_quality || [] },
          ];
        })
      );
      const strategyFields = {
        approach,
        size,
        move_tags: moveTags,
        form_quality: formQuality,
        confidence: strategyConfidence || null,
      };
      const envFields = { wall_angle: wallAngle, ...slotPayload };
      const outcomeFields = { result, reach_detail: reachDetail, confidence };

      let strategy;
      if (existingStrategy) {
        strategy = await updateStrategy(existingStrategy.id, strategyFields);
      } else {
        try {
          strategy = await createStrategy({ move_id: move.id, ...strategyFields });
        } catch (err) {
          // Already created (a reload mid-save): fetch it and update instead.
          if (err.response?.status !== 409) throw err;
          const found = await getStrategyForMove(move.id);
          strategy = await updateStrategy(found.id, strategyFields);
        }
      }
      setExistingStrategy(strategy);

      let env;
      if (existingEnv) {
        env = await updateEnvironment(existingEnv.id, envFields);
      } else {
        try {
          env = await createEnvironment({ move_id: move.id, ...envFields });
        } catch (err) {
          // Already created (a reload mid-save): fetch it and update instead.
          if (err.response?.status !== 409) throw err;
          const found = await getEnvironmentForMove(move.id);
          env = await updateEnvironment(found.id, envFields);
        }
      }
      setExistingEnv(env);

      let outcome;
      if (existingOutcome) {
        outcome = await updateOutcome(existingOutcome.id, outcomeFields);
      } else {
        try {
          outcome = await createOutcome({ move_id: move.id, ...outcomeFields });
        } catch (err) {
          if (err.response?.status !== 409) throw err;
          const found = await getOutcomeForMove(move.id);
          outcome = await updateOutcome(found.id, outcomeFields);
        }
      }
      setExistingOutcome(outcome);

      setPreviousEnvironment(envFields);
      setHoldPickSlot(null);
      setSavedNote('Saved.');
      onSaved?.(move.id, { strategy: true, environment: true, outcome: true });
    } catch (err) {
      console.error('Failed to save rating:', err);
      const status = err.response?.status;
      setError(
        status === 403
          ? 'This rating is locked (the assignment is done or the video is closed).'
          : err.response?.data?.detail || 'Failed to save. Please try again.'
      );
    } finally {
      setSaving(false);
    }
  };

  if (!config) {
    return (
      <aside className="move-form-panel">
        <div className="move-form-loading">Loading configuration…</div>
      </aside>
    );
  }

  const disabled = locked || loadingExisting;

  return (
    <aside className="move-form-panel" data-testid="rater-move-form">
      <div className="move-form-header">
        <h2>Rate Move{moveIndex != null ? ` ${moveIndex + 1}` : ''}</h2>
        <button onClick={handleClose} className="close-btn" aria-label="Close rating panel">
          ✕
        </button>
      </div>

      <div className="move-form-content">
        <div className="move-info">
          <p>
            Frames: {move.frame_start} – {move.frame_end} ({move.frame_end - move.frame_start} frames)
          </p>
          {locked && (
            <p className="locked-note" role="note">
              Rating submitted — this move is read-only.
            </p>
          )}
        </div>

        {error && <div className="error-message">{error}</div>}
        {savedNote && (
          <div className="saved-note" role="status">
            {savedNote}
          </div>
        )}
        {loadingExisting && <div className="move-form-loading">Loading your labels…</div>}

        <StrategyLens
          config={config}
          approach={approach}
          onApproach={setApproach}
          size={size}
          onSize={setSize}
          moveTags={moveTags}
          onToggleTag={toggleMoveTag}
          formQuality={formQuality}
          onFormQuality={setFormQuality}
          confidence={strategyConfidence}
          onConfidence={setStrategyConfidence}
          disabled={disabled}
        />

        <EnvironmentLens
          config={config}
          wallAngle={wallAngle}
          onWallAngle={setWallAngle}
          slots={slots}
          holdPickSlot={holdPickSlot}
          onPickSlot={setHoldPickSlot}
          onUpdateSlot={updateSlot}
          onToggleQuality={toggleSlotQuality}
          onClearSlot={clearSlot}
          noHands={noHands}
          holds={holds ?? []}
          disabled={disabled}
        />

        <OutcomeLens
          config={config}
          result={result}
          onResult={setResult}
          reachDetail={reachDetail}
          onReachDetail={setReachDetail}
          confidence={confidence}
          onConfidence={setConfidence}
          disabled={disabled}
        />
      </div>

      <div className="move-form-footer">
        <button onClick={handleClose} className="btn-secondary">
          {locked ? 'Close' : 'Cancel'}
        </button>
        {!locked && (
          <button onClick={handleSave} className="btn-primary" disabled={saving || loadingExisting}>
            {saving ? 'Saving…' : existingStrategy || existingEnv || existingOutcome ? 'Update Rating' : 'Save Rating'}
          </button>
        )}
      </div>
    </aside>
  );
}

export default RaterMoveForm;
