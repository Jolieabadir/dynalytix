import { describe, it, expect, vi, afterEach } from 'vitest';
import { isCoarsePointer, swipeToFrameDelta, COARSE_QUERY } from './pointer';

function stubMatchMedia(matches) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: query === COARSE_QUERY ? matches : false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
  }));
}

afterEach(() => {
  delete window.matchMedia;
});

describe('isCoarsePointer', () => {
  it('is true when the primary pointer is a finger', () => {
    stubMatchMedia(true);
    expect(isCoarsePointer()).toBe(true);
  });

  it('is false on a mouse', () => {
    stubMatchMedia(false);
    expect(isCoarsePointer()).toBe(false);
  });

  it('is false, not a crash, where matchMedia is missing', () => {
    delete window.matchMedia;
    expect(isCoarsePointer()).toBe(false);
  });
});

describe('swipeToFrameDelta', () => {
  it('swiping left goes forward one frame', () => {
    expect(swipeToFrameDelta({ dx: -60, dy: 4 })).toBe(1);
  });

  it('swiping right goes back one frame', () => {
    expect(swipeToFrameDelta({ dx: 60, dy: 4 })).toBe(-1);
  });

  it('ignores a short drag — that is a tap', () => {
    expect(swipeToFrameDelta({ dx: -12, dy: 2 })).toBe(0);
  });

  it('ignores a mostly vertical drag — that is the page scrolling', () => {
    expect(swipeToFrameDelta({ dx: -40, dy: 120 })).toBe(0);
  });

  it('honours a custom frames-per-swipe', () => {
    expect(swipeToFrameDelta({ dx: -60, dy: 0 }, { framesPerSwipe: 10 })).toBe(10);
  });
});
