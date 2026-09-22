/**
 * "Add to Home Screen" — the PWA nudge.
 *
 * Two platforms, two mechanisms:
 *
 * - Chrome/Android fires `beforeinstallprompt`, which can be deferred and
 *   replayed from a button. That is a real install dialog.
 * - iOS Safari fires nothing and exposes no API. The only way in is Share →
 *   Add to Home Screen, so on iOS this shows those words and nothing else.
 *   Since iPhone is the primary client, that branch is the point of the
 *   component, not the fallback.
 *
 * Never shown when the app is already running standalone — that is the state
 * the prompt is asking for. Dismissal is remembered across sessions: a
 * labeler who said no does not want to be asked at the top of every session.
 */
import { useEffect, useState } from 'react';
import { useCoarsePointer } from '../utils/pointer';
import { isStandalone, isIos } from '../utils/standalone';

const DISMISSED_KEY = 'dynalytix.install.dismissed';

function readDismissed() {
  try {
    return localStorage.getItem(DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

function InstallPrompt() {
  const touch = useCoarsePointer();
  const [dismissed, setDismissed] = useState(readDismissed);
  const [deferredEvent, setDeferredEvent] = useState(null);

  useEffect(() => {
    const onBeforeInstall = (event) => {
      // Keep the event so the install can happen on the labeler's tap instead
      // of the browser's own moment.
      event.preventDefault();
      setDeferredEvent(event);
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    return () => window.removeEventListener('beforeinstallprompt', onBeforeInstall);
  }, []);

  if (!touch || dismissed || isStandalone()) return null;
  // Nothing to offer: not iOS, and Chrome has not said it is installable.
  if (!isIos() && !deferredEvent) return null;

  const handleDismiss = () => {
    try {
      localStorage.setItem(DISMISSED_KEY, '1');
    } catch {
      // Private mode: it comes back next session.
    }
    setDismissed(true);
  };

  const handleInstall = async () => {
    if (!deferredEvent) return;
    deferredEvent.prompt();
    try {
      await deferredEvent.userChoice;
    } catch {
      // The labeler closed it; nothing to do.
    }
    setDeferredEvent(null);
    handleDismiss();
  };

  return (
    <div className="install-prompt" role="note" data-testid="install-prompt">
      <span className="install-text">
        {isIos() ? (
          <>
            Add Dynalytix to your Home Screen — tap <strong>Share</strong>, then{' '}
            <strong>Add to Home Screen</strong>. It runs fullscreen and holds your session
            better than a Safari tab.
          </>
        ) : (
          <>Install Dynalytix for a fullscreen labeling session.</>
        )}
      </span>
      <span className="install-actions">
        {!isIos() && deferredEvent && (
          <button type="button" className="btn-primary install-btn" onClick={handleInstall}>
            Install
          </button>
        )}
        <button
          type="button"
          className="onboarding-dismiss"
          aria-label="Dismiss the install prompt"
          onClick={handleDismiss}
        >
          ✕
        </button>
      </span>
    </div>
  );
}

export default InstallPrompt;
