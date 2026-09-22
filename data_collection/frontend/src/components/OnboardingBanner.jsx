/**
 * OnboardingBanner — the one-line "here is how this screen works" strip.
 *
 * Two kinds of dismissal, for two kinds of tip:
 *
 * - Screen tips (define, tagging) are session-only, in the store. A labeler
 *   who reloads has lost their place anyway, and the reminder costs one tap.
 * - The capture tip is remembered across sessions, in localStorage. The
 *   runbook asks for it once: it is about how to hold and configure the
 *   phone before filming, and a labeler who has read it does not need it at
 *   the top of every session. Shown only on touch, because it is advice about
 *   the device in your hand.
 *
 * The text also depends on the pointer: "[ and ]" is meaningless on a phone.
 */
import useStore from '../store/useStore';
import { useCoarsePointer } from '../utils/pointer';

export const BANNER_DEFINE = 'define';
export const BANNER_TAGGING = 'tagging';
export const BANNER_CAPTURE = 'capture';

/** Tips remembered across sessions, and where. */
const PERSISTENT = new Set([BANNER_CAPTURE]);
const storageKey = (id) => `dynalytix.banner.${id}`;

/** Shown only when the labeler is on a touch device. */
const TOUCH_ONLY = new Set([BANNER_CAPTURE]);

const BANNER_TEXT = {
  [BANNER_DEFINE]: {
    pointer: 'Set the start frame with [, the end frame with ], then Create Move.',
    touch: 'Swipe the video to find the start, tap Mark Start, then the end, then Create Move.',
  },
  [BANNER_TAGGING]: {
    pointer: 'Use the scroll bar to find the frame, then tag it.',
    touch: 'Swipe the video or drag the bar to find the frame, then tag it.',
  },
  [BANNER_CAPTURE]: {
    pointer: '',
    touch:
      'Film at 1080p and 30fps (Settings → Camera → Record Video). It halves the upload and the processing time, and 30fps is the biomechanics standard.',
  },
};

function readDismissed(id) {
  try {
    return localStorage.getItem(storageKey(id)) === '1';
  } catch {
    return false;
  }
}

function writeDismissed(id) {
  try {
    localStorage.setItem(storageKey(id), '1');
  } catch {
    // Private mode or no quota: the tip comes back next session. Harmless.
  }
}

function OnboardingBanner({ id }) {
  const dismissedBanners = useStore((s) => s.dismissedBanners);
  const dismissBanner = useStore((s) => s.dismissBanner);
  const touch = useCoarsePointer();

  if (TOUCH_ONLY.has(id) && !touch) return null;

  const text = BANNER_TEXT[id]?.[touch ? 'touch' : 'pointer'];
  if (!text) return null;

  const persistent = PERSISTENT.has(id);
  if (persistent ? readDismissed(id) : dismissedBanners[id]) return null;

  const handleDismiss = () => {
    if (persistent) writeDismissed(id);
    // Also recorded in the store, so this render goes away immediately.
    dismissBanner(id);
  };

  return (
    <div className={`onboarding-banner ${persistent ? 'capture' : ''}`} role="note">
      <span className="onboarding-text">{text}</span>
      <button
        type="button"
        className="onboarding-dismiss"
        aria-label="Dismiss this tip"
        onClick={handleDismiss}
      >
        ✕
      </button>
    </div>
  );
}

export default OnboardingBanner;
