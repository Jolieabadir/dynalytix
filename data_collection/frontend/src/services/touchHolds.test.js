import { describe, it, expect } from 'vitest';
import {
  boxAtPoint,
  scaleBox,
  holdAtPoint,
  distance,
  DEFAULT_BOX_SIZE,
  MIN_BOX_SIZE,
  MAX_BOX_SIZE,
} from './touchHolds';

describe('boxAtPoint', () => {
  it('centres a default box on the tap', () => {
    const box = boxAtPoint({ x: 0.5, y: 0.5 });
    expect(box.bbox_w).toBeCloseTo(DEFAULT_BOX_SIZE);
    expect(box.bbox_h).toBeCloseTo(DEFAULT_BOX_SIZE);
    expect(box.bbox_x + box.bbox_w / 2).toBeCloseTo(0.5);
    expect(box.bbox_y + box.bbox_h / 2).toBeCloseTo(0.5);
  });

  it('nudges a corner tap inside the frame instead of shrinking it', () => {
    const box = boxAtPoint({ x: 0, y: 0 });
    expect(box.bbox_x).toBe(0);
    expect(box.bbox_y).toBe(0);
    expect(box.bbox_w).toBeCloseTo(DEFAULT_BOX_SIZE);
  });

  it('keeps a bottom-right tap fully on screen', () => {
    const box = boxAtPoint({ x: 1, y: 1 });
    expect(box.bbox_x + box.bbox_w).toBeCloseTo(1);
    expect(box.bbox_y + box.bbox_h).toBeCloseTo(1);
  });
});

describe('scaleBox', () => {
  const box = { bbox_x: 0.4, bbox_y: 0.4, bbox_w: 0.1, bbox_h: 0.1 };

  it('grows about the centre', () => {
    const bigger = scaleBox(box, 2);
    expect(bigger.bbox_w).toBeCloseTo(0.2);
    expect(bigger.bbox_x + bigger.bbox_w / 2).toBeCloseTo(0.45);
  });

  it('shrinks about the centre', () => {
    const smaller = scaleBox(box, 0.5);
    expect(smaller.bbox_w).toBeCloseTo(0.05);
    expect(smaller.bbox_x + smaller.bbox_w / 2).toBeCloseTo(0.45);
  });

  it('will not shrink a hold below the tappable minimum', () => {
    expect(scaleBox(box, 0.001).bbox_w).toBe(MIN_BOX_SIZE);
  });

  it('will not grow a hold past the frame', () => {
    expect(scaleBox(box, 100).bbox_w).toBe(MAX_BOX_SIZE);
  });

  it('ignores a nonsense factor rather than corrupting the box', () => {
    expect(scaleBox(box, 0)).toEqual(box);
    expect(scaleBox(box, NaN)).toEqual(box);
  });

  it('keeps a scaled box inside the frame', () => {
    const edge = { bbox_x: 0.95, bbox_y: 0.95, bbox_w: 0.04, bbox_h: 0.04 };
    const grown = scaleBox(edge, 4);
    expect(grown.bbox_x + grown.bbox_w).toBeLessThanOrEqual(1.0001);
    expect(grown.bbox_y + grown.bbox_h).toBeLessThanOrEqual(1.0001);
  });
});

describe('holdAtPoint', () => {
  const a = { id: 1, bbox_x: 0.1, bbox_y: 0.1, bbox_w: 0.2, bbox_h: 0.2 };
  const b = { id: 2, bbox_x: 0.15, bbox_y: 0.15, bbox_w: 0.2, bbox_h: 0.2 };

  it('finds the hold under the finger', () => {
    expect(holdAtPoint([a], { x: 0.15, y: 0.15 })?.id).toBe(1);
  });

  it('returns null on empty space', () => {
    expect(holdAtPoint([a], { x: 0.9, y: 0.9 })).toBeNull();
  });

  it('the topmost overlapping hold wins', () => {
    expect(holdAtPoint([a, b], { x: 0.2, y: 0.2 })?.id).toBe(2);
  });
});

describe('distance', () => {
  it('measures a pinch', () => {
    expect(distance({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
  });
});
