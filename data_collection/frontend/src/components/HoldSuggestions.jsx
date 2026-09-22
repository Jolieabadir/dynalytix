/**
 * Auto-suggest panel: which holds the climber is on at the current frame.
 *
 * Read-only assistance for the labeller. It proposes body parts and a side for
 * the frame tag being written; it never writes anything on its own, and every
 * suggestion is one click to apply and trivially ignorable.
 *
 * All coordinate handling is delegated to services/holdMatching via
 * holdSuggestions. This component does no geometry.
 */
import { useMemo } from 'react';
import useStore from '../store/useStore';
import { suggestHoldsForFrame, bodyPartsFor, sideFor } from '../services/holdSuggestions';

/** Why no suggestion is available, in the labeller's terms. */
const REASON_TEXT = {
  'waiting-for-pose':
    'Waiting for pose — the server is still extracting the skeleton for this video.',
  'pose-failed':
    'Pose extraction failed, so there is nothing to match against. Retry it from the header.',
  'no-holds':
    'No holds recorded for this video yet, so there is nothing to match against.',
  'no-dimensions':
    'This video was registered before frame dimensions were stored, so landmarks cannot be placed against holds. Re-upload it to enable suggestions.',
  'no-pose': 'No pose was detected on this frame.',
  'no-contact': 'No hand or foot is near a hold on this frame.',
};

function HoldSuggestions({ onApply }) {
  const { currentVideo, csvData, currentFrame, holds, poseStatus } = useStore();

  const poseState =
    poseStatus?.video_id === currentVideo?.id ? poseStatus.pose_status : 'pending';

  const suggestion = useMemo(() => {
    if (poseState === 'failed') {
      return { available: false, reason: 'pose-failed', contacts: [] };
    }
    if (poseState !== 'done' || !csvData) {
      return { available: false, reason: 'waiting-for-pose', contacts: [] };
    }
    // csvData is indexed positionally; the worker's no-gap guarantee is what
    // makes row N frame N.
    const row = csvData[currentFrame];
    return suggestHoldsForFrame(
      row,
      holds,
      currentVideo?.width,
      currentVideo?.height
    );
  }, [poseState, csvData, currentFrame, holds, currentVideo?.width, currentVideo?.height]);

  const { available, reason, contacts } = suggestion;

  return (
    <div className="hold-suggestions">
      <h4 className="hold-suggestions-title">
        Holds in use
        <span className="hold-suggestions-frame">frame {currentFrame}</span>
      </h4>

      {!available ? (
        <p className="hold-suggestions-empty">{REASON_TEXT[reason] || 'No suggestion.'}</p>
      ) : (
        <>
          <ul className="hold-suggestions-list">
            {contacts.map((contact) => (
              <li key={contact.name} className="hold-suggestion">
                <button
                  type="button"
                  className="hold-suggestion-button"
                  onClick={() => onApply?.([contact])}
                  title={`Tag ${contact.label.toLowerCase()} at this frame`}
                >
                  <span className={`hold-suggestion-limb limb-${contact.limb}`}>
                    {contact.limb === 'hand' ? '✋' : '🦶'} {contact.label}
                  </span>
                  <span className="hold-suggestion-hold">
                    hold #{contact.hold.id ?? contact.holdIndex + 1}
                  </span>
                  <span
                    className={
                      contact.inside
                        ? 'hold-suggestion-confidence on'
                        : 'hold-suggestion-confidence near'
                    }
                  >
                    {contact.inside ? 'on' : `${(contact.distance * 100).toFixed(1)}% away`}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          {contacts.length > 1 && (
            <button
              type="button"
              className="hold-suggestions-apply-all"
              onClick={() => onApply?.(contacts)}
            >
              Use all {contacts.length}
            </button>
          )}

          <p className="hold-suggestions-hint">
            Suggested: {bodyPartsFor(contacts).join(', ')}
            {sideFor(contacts) ? ` · ${sideFor(contacts)} side` : ' · mixed sides'}
          </p>
        </>
      )}
    </div>
  );
}

export default HoldSuggestions;
