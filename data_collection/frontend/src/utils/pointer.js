/**
 * Pointer kind: is this a finger or a mouse?
 *
 * The runbook's constraint is one UI, not two builds — the laptop path keeps
 * its keyboard shortcuts, drag-to-draw and hover tooltips, and the same code
 * shows tap targets and a bottom sheet when it is being used with a finger.
 * So this is detected, and detected reactively: an iPad with a trackpad
 * attached changes answer mid-session, and a desktop browser in device-
 * emulation mode changes it on every toggle.
 *
 * `(pointer: coarse)` is the right question. Touch-event sniffing says yes on
 * every touchscreen laptop, where the labeler is still using a mouse.
 */
import { useEffect, useState } from 'react';

export const COARSE_QUERY = '(pointer: coarse)';

/** True when the primary pointer is a finger. Safe before mount and in jsdom. */
export function isCoarsePointer() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  try {
    return window.matchMedia(COARSE_QUERY).matches;
  } catch {
    return false;
  }
}

/**
 * Reactive `isCoarsePointer()`.
 * @returns {boolean}
 */
export function useCoarsePointer() {
  const [coarse, setCoarse] = useState(isCoarsePointer);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    let mql;
    try {
      mql = window.matchMedia(COARSE_QUERY);
    } catch {
      return;
    }
    const onChange = (event) => setCoarse(event.matches);
    setCoarse(mql.matches);

    // Safari only grew addEventListener on MediaQueryList in 14; the phones
    // this is for are newer, but the fallback costs two lines.
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    }
    mql.addListener(onChange);
    return () => mql.removeListener(onChange);
  }, []);

  return coarse;
}

/**
 * Horizontal swipe recognizer for frame stepping.
 *
 * Returns the number of frames a gesture means, or 0 when the gesture was not
 * a horizontal swipe. A drag that is mostly vertical is the page scrolling and
 * must be left alone; one that never travels far enough is a tap.
 *
 * Swiping left moves forward, matching how a film strip would slide.
 *
 * @param {{dx: number, dy: number}} delta pixels travelled
 * @param {{threshold?: number, framesPerSwipe?: number}} [options]
 */
export function swipeToFrameDelta({ dx, dy }, options = {}) {
  const { threshold = 30, framesPerSwipe = 1 } = options;
  if (Math.abs(dx) < threshold) return 0;
  // Mostly vertical: that is a scroll, not a scrub.
  if (Math.abs(dy) > Math.abs(dx)) return 0;
  return dx < 0 ? framesPerSwipe : -framesPerSwipe;
}
