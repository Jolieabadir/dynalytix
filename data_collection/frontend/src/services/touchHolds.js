/**
 * Hold geometry for fingers.
 *
 * On a pointer device a hold is drawn: press, drag a rectangle, release. That
 * gesture does not survive the move to a phone — the box you are drawing is
 * under your thumb, and a 40 px hold on a 390 px-wide screen is not something
 * anyone draws accurately at arm's length.
 *
 * So on touch a hold is TAPPED: one tap drops a box of a sensible default size
 * centred where the finger landed, and pinching resizes it. That is the whole
 * of the difference — the stored shape is identical, normalized 0-1, and the
 * laptop keeps drag-to-draw.
 *
 * Everything here is pure so the arithmetic can be tested without a DOM.
 */

/**
 * Side of a tapped box, as a fraction of the frame.
 *
 * Climbing holds in a phone-shot clip are small. 9% of the frame is roughly a
 * jug at typical framing, big enough to see and to pinch, small enough not to
 * swallow its neighbours.
 */
export const DEFAULT_BOX_SIZE = 0.09;

/** Never let a box get too small to tap again, or larger than the frame. */
export const MIN_BOX_SIZE = 0.02;
export const MAX_BOX_SIZE = 0.9;

const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

/**
 * A default box centred on a tap, kept inside the frame.
 *
 * Clamped rather than shrunk: a tap near the edge should still produce a
 * full-size hold, just nudged inwards.
 *
 * @param {{x: number, y: number}} point normalized tap position
 * @param {number} [size] side length as a fraction of the frame
 */
export function boxAtPoint(point, size = DEFAULT_BOX_SIZE) {
  const side = clamp(size, MIN_BOX_SIZE, MAX_BOX_SIZE);
  return {
    bbox_x: clamp(point.x - side / 2, 0, 1 - side),
    bbox_y: clamp(point.y - side / 2, 0, 1 - side),
    bbox_w: side,
    bbox_h: side,
  };
}

/**
 * Scale a box about its own centre — what a pinch does.
 *
 * Width and height are scaled by the same factor, so a pinch cannot turn a
 * hold into a sliver. The result stays inside the frame.
 *
 * @param {{bbox_x: number, bbox_y: number, bbox_w: number, bbox_h: number}} box
 * @param {number} factor >1 grows, <1 shrinks
 */
export function scaleBox(box, factor) {
  if (!Number.isFinite(factor) || factor <= 0) return box;

  const centerX = box.bbox_x + box.bbox_w / 2;
  const centerY = box.bbox_y + box.bbox_h / 2;
  const w = clamp(box.bbox_w * factor, MIN_BOX_SIZE, MAX_BOX_SIZE);
  const h = clamp(box.bbox_h * factor, MIN_BOX_SIZE, MAX_BOX_SIZE);

  return {
    ...box,
    bbox_x: clamp(centerX - w / 2, 0, 1 - w),
    bbox_y: clamp(centerY - h / 2, 0, 1 - h),
    bbox_w: w,
    bbox_h: h,
  };
}

/** Distance between two points, for pinch tracking. */
export function distance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** Which hold, if any, contains this point. Topmost (last drawn) wins. */
export function holdAtPoint(holds, point) {
  for (let i = holds.length - 1; i >= 0; i--) {
    const h = holds[i];
    if (
      point.x >= h.bbox_x &&
      point.x <= h.bbox_x + h.bbox_w &&
      point.y >= h.bbox_y &&
      point.y <= h.bbox_y + h.bbox_h
    ) {
      return h;
    }
  }
  return null;
}
