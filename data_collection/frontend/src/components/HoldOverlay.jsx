/**
 * HoldOverlay — the hold boxes drawn over the video.
 *
 * Two input models on one surface, chosen by pointer kind, not by build.
 *
 * Pointer device (unchanged):
 *   - drag on empty space   → draw a new box
 *   - click an existing box → delete it
 *   - "pick on video" mode  → click a box to assign it to a MoveForm slot
 *
 * Touch:
 *   - tap empty space       → drop a default-size box centred on the tap
 *   - pinch                 → resize the selected box
 *   - press and hold a box  → delete it
 *   - swipe left/right      → step one frame (the video is the scrubber)
 *   - "pick on video" mode  → tap a box to assign it
 *
 * Drawing a rectangle with a thumb, at arm's length, on a box that is under
 * the thumb, does not work — hence tap-to-place. Delete moves to press-and-
 * hold for the same reason a tap cannot mean both "place" and "delete".
 *
 * Boxes are stored normalized 0-1 either way, so they survive any later
 * re-encode or resize and line up whatever size the player is rendered at.
 *
 * `readOnly` (the rating view, or an owner on a locked video) keeps the boxes
 * visible and pickable but removes placing, resizing and deleting entirely:
 * the holds are the canonical set and only the admin changes it.
 */
import { useEffect, useRef, useState } from 'react';
import { boxAtPoint, scaleBox, holdAtPoint, distance } from '../services/touchHolds';
import { swipeToFrameDelta } from '../utils/pointer';

/** Smallest drawn box worth keeping, as a fraction of the frame. */
const MIN_BOX = 0.01;

/** How long a finger must rest on a box before it means "delete". */
const LONG_PRESS_MS = 600;

function HoldOverlay({
  holds,
  pickSlot,
  onCreate,
  onDelete,
  onPick,
  onResize,
  onSwipeFrames,
  disabled,
  readOnly = false,
  touch = false,
}) {
  const surfaceRef = useRef(null);
  const [draft, setDraft] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [pinchPreview, setPinchPreview] = useState(null);
  const dragStart = useRef(null);

  // Touch bookkeeping: live pointers, the gesture's origin in client pixels,
  // the long-press timer, and the pinch baseline.
  const pointers = useRef(new Map());
  const gesture = useRef(null);
  const longPressTimer = useRef(null);
  const pinch = useRef(null);

  const picking = Boolean(pickSlot);
  const canEdit = !disabled && !readOnly && !picking;

  // A selected hold that has since been deleted must not keep a pinch alive.
  // Derived rather than corrected in an effect, so there is never a render
  // where the highlight points at a hold that is gone.
  const selected = holds.some((h) => h.id === selectedId) ? selectedId : null;

  useEffect(() => () => clearTimeout(longPressTimer.current), []);

  const pointFromEvent = (e) => {
    const rect = surfaceRef.current.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    };
  };

  const cancelLongPress = () => {
    clearTimeout(longPressTimer.current);
    longPressTimer.current = null;
  };

  // ==================== TOUCH ====================

  const handleTouchDown = (e) => {
    if (disabled) return;
    surfaceRef.current.setPointerCapture?.(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (pointers.current.size === 2) {
      // Second finger: this is a pinch, not a tap or a swipe.
      cancelLongPress();
      gesture.current = null;
      const [a, b] = [...pointers.current.values()];
      const target = holds.find((h) => h.id === selected);
      if (target && canEdit) {
        pinch.current = { startDistance: distance(a, b), box: target };
      }
      return;
    }

    const point = pointFromEvent(e);
    const hit = holdAtPoint(holds, point);
    gesture.current = { startX: e.clientX, startY: e.clientY, point, hit, moved: false };

    // Press-and-hold on a box deletes it. Armed here, disarmed by any travel.
    if (hit && canEdit) {
      longPressTimer.current = setTimeout(() => {
        longPressTimer.current = null;
        if (gesture.current && !gesture.current.moved) {
          gesture.current = null;
          setSelectedId(null);
          onDelete(hit);
        }
      }, LONG_PRESS_MS);
    }
  };

  const handleTouchMove = (e) => {
    if (!pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (pinch.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      const factor = distance(a, b) / (pinch.current.startDistance || 1);
      setPinchPreview(scaleBox(pinch.current.box, factor));
      return;
    }

    const g = gesture.current;
    if (!g) return;
    if (Math.abs(e.clientX - g.startX) > 8 || Math.abs(e.clientY - g.startY) > 8) {
      g.moved = true;
      cancelLongPress();
    }
  };

  const handleTouchUp = (e) => {
    pointers.current.delete(e.pointerId);

    if (pinch.current) {
      if (pointers.current.size < 2) {
        const resized = pinchPreview;
        const original = pinch.current.box;
        pinch.current = null;
        setPinchPreview(null);
        if (resized && onResize && resized.bbox_w !== original.bbox_w) {
          onResize(original, {
            bbox_x: resized.bbox_x,
            bbox_y: resized.bbox_y,
            bbox_w: resized.bbox_w,
            bbox_h: resized.bbox_h,
          });
        }
      }
      return;
    }

    const g = gesture.current;
    gesture.current = null;
    cancelLongPress();
    if (!g) return;

    // A horizontal drag is a scrub, whatever it started on.
    const frames = swipeToFrameDelta({ dx: e.clientX - g.startX, dy: e.clientY - g.startY });
    if (frames !== 0) {
      if (onSwipeFrames) onSwipeFrames(frames);
      return;
    }
    if (g.moved) return; // travelled, but not a swipe: no tap either

    if (g.hit) {
      if (picking) {
        onPick(g.hit);
        return;
      }
      // Select it, so a pinch has something to resize.
      setSelectedId((current) => (current === g.hit.id ? null : g.hit.id));
      return;
    }

    if (canEdit) onCreate(boxAtPoint(g.point));
  };

  // ==================== POINTER (drag to draw) ====================

  const handlePointerDown = (e) => {
    if (touch) {
      handleTouchDown(e);
      return;
    }
    if (disabled || picking || readOnly) return;
    // Only start a drag on the surface itself, never on top of a box.
    if (e.target !== surfaceRef.current) return;

    e.preventDefault();
    surfaceRef.current.setPointerCapture?.(e.pointerId);
    dragStart.current = pointFromEvent(e);
    setDraft({ ...dragStart.current, w: 0, h: 0 });
  };

  const handlePointerMove = (e) => {
    if (touch) {
      handleTouchMove(e);
      return;
    }
    if (!dragStart.current) return;
    const p = pointFromEvent(e);
    const start = dragStart.current;
    setDraft({
      x: Math.min(start.x, p.x),
      y: Math.min(start.y, p.y),
      w: Math.abs(p.x - start.x),
      h: Math.abs(p.y - start.y),
    });
  };

  const handlePointerUp = (e) => {
    if (touch) {
      handleTouchUp(e);
      return;
    }
    if (!dragStart.current) return;
    const box = draft;
    dragStart.current = null;
    setDraft(null);

    if (box && box.w >= MIN_BOX && box.h >= MIN_BOX) {
      onCreate({ bbox_x: box.x, bbox_y: box.y, bbox_w: box.w, bbox_h: box.h });
    }
  };

  const handleBoxClick = (e, hold) => {
    // On touch the gesture handlers own this surface entirely; a synthesized
    // click after a tap would place or delete a second time.
    if (touch) {
      e.stopPropagation();
      return;
    }
    e.stopPropagation();
    if (disabled) return;
    if (picking) {
      onPick(hold);
      return;
    }
    if (readOnly) return;
    onDelete(hold);
  };

  const boxTitle = (hold) => {
    if (picking) return `Assign hold #${hold.id} to this slot`;
    if (readOnly) return `Hold #${hold.id} (${hold.source})`;
    return touch
      ? `Hold #${hold.id} (${hold.source}) — press and hold to delete`
      : `Hold #${hold.id} (${hold.source}) — click to delete`;
  };

  return (
    <div
      ref={surfaceRef}
      className={`hold-overlay ${picking ? 'picking' : ''} ${disabled ? 'disabled' : ''} ${
        readOnly ? 'readonly' : ''
      } ${touch ? 'touch' : ''}`}
      data-testid="hold-overlay"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
    >
      {holds.map((hold) => {
        const previewing = pinchPreview && hold.id === selected;
        const shown = previewing ? pinchPreview : hold;
        return (
          <button
            key={hold.id}
            type="button"
            className={`hold-box ${hold.source === 'detected' ? 'detected' : 'manual'} ${
              hold.id === selected ? 'selected' : ''
            }`}
            style={{
              left: `${shown.bbox_x * 100}%`,
              top: `${shown.bbox_y * 100}%`,
              width: `${shown.bbox_w * 100}%`,
              height: `${shown.bbox_h * 100}%`,
            }}
            title={boxTitle(hold)}
            aria-label={
              picking
                ? `Assign hold ${hold.id}`
                : readOnly
                  ? `Hold ${hold.id}`
                  : `Delete hold ${hold.id}`
            }
            onClick={(e) => handleBoxClick(e, hold)}
          />
        );
      })}

      {draft && (
        <div
          className="hold-box draft"
          style={{
            left: `${draft.x * 100}%`,
            top: `${draft.y * 100}%`,
            width: `${draft.w * 100}%`,
            height: `${draft.h * 100}%`,
          }}
        />
      )}

      {picking && (
        <div className="hold-pick-hint">
          {touch ? 'Tap a hold to assign it' : 'Click a hold to assign it — Esc to cancel'}
        </div>
      )}

      {touch && !picking && selected != null && !readOnly && (
        <div className="hold-pick-hint">Pinch to resize — press and hold to delete</div>
      )}
    </div>
  );
}

export default HoldOverlay;
