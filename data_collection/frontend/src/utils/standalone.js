/**
 * Is this page an installed app, and is it on iOS?
 *
 * Separate from the component that uses them so the module exports only
 * components — Fast Refresh cannot handle a file that mixes the two, and
 * these are testable on their own besides.
 */

/** True when the page is already running as an installed app. */
export function isStandalone() {
  if (typeof window === 'undefined') return false;
  try {
    // navigator.standalone is the iOS-only signal; the media query is everyone else.
    if (window.navigator?.standalone === true) return true;
    return Boolean(window.matchMedia?.('(display-mode: standalone)')?.matches);
  } catch {
    return false;
  }
}

/** True on iOS/iPadOS, where installing is a manual Share-sheet step. */
export function isIos() {
  if (typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  // iPadOS 13+ reports as a Mac; the touch point count is what gives it away.
  const iPadOnMac = /Macintosh/.test(ua) && (navigator.maxTouchPoints || 0) > 1;
  return /iPad|iPhone|iPod/.test(ua) || iPadOnMac;
}
