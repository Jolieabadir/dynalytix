/**
 * HoldOverlay — the hold boxes drawn over the video.
 *
 * Three interactions, all on the same surface:
 *   - drag on empty space  → draw a new box
 *   - click an existing box → delete it
 *   - "pick on video" mode  → click a box to assign it to a MoveForm slot
 *
 * Boxes are stored normalized 0-1, so they survive any later re-encode or
 * resize and line up whatever size the player is rendered at. That means every
 * coordinate here is a fraction, converted to percentages for layout.
 *
 * A drag under a few pixels is treated as a click, so a slightly shaky click on
 * a box deletes it rather than leaving a sliver of a new hold behind.
 *
 * `readOnly` (the rating view, or an owner on a locked video) keeps the boxes
 * visible and pickable but removes drawing and deleting entirely: the holds
 * are the canonical set and only the admin changes it.
 */
import { useRef, useState } from 'react';

/** Smallest box worth keeping, as a fraction of the frame. */
const MIN_BOX = 0.01;

function HoldOverlay({ holds, pickSlot, onCreate, onDelete, onPick, disabled, readOnly = false }) {
  const surfaceRef = useRef(null);
  const [draft, setDraft] = useState(null);
  const dragStart = useRef(null);

  const picking = Boolean(pickSlot);

  const pointFromEvent = (e) => {
    const rect = surfaceRef.current.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    };
  };

  const handlePointerDown = (e) => {
    if (disabled || picking || readOnly) return;
    // Only start a drag on the surface itself, never on top of a box.
    if (e.target !== surfaceRef.current) return;

    e.preventDefault();
    surfaceRef.current.setPointerCapture?.(e.pointerId);
    dragStart.current = pointFromEvent(e);
    setDraft({ ...dragStart.current, w: 0, h: 0 });
  };

  const handlePointerMove = (e) => {
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

  const handlePointerUp = () => {
    if (!dragStart.current) return;
    const box = draft;
    dragStart.current = null;
    setDraft(null);

    if (box && box.w >= MIN_BOX && box.h >= MIN_BOX) {
      onCreate({ bbox_x: box.x, bbox_y: box.y, bbox_w: box.w, bbox_h: box.h });
    }
  };

  const handleBoxClick = (e, hold) => {
    e.stopPropagation();
    if (disabled) return;
    if (picking) {
      onPick(hold);
      return;
    }
    if (readOnly) return;
    onDelete(hold);
  };

  return (
    <div
      ref={surfaceRef}
      className={`hold-overlay ${picking ? 'picking' : ''} ${disabled ? 'disabled' : ''} ${
        readOnly ? 'readonly' : ''
      }`}
      data-testid="hold-overlay"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
    >
      {holds.map((hold) => (
        <button
          key={hold.id}
          type="button"
          className={`hold-box ${hold.source === 'detected' ? 'detected' : 'manual'}`}
          style={{
            left: `${hold.bbox_x * 100}%`,
            top: `${hold.bbox_y * 100}%`,
            width: `${hold.bbox_w * 100}%`,
            height: `${hold.bbox_h * 100}%`,
          }}
          title={
            picking
              ? `Assign hold #${hold.id} to this slot`
              : readOnly
                ? `Hold #${hold.id} (${hold.source})`
                : `Hold #${hold.id} (${hold.source}) — click to delete`
          }
          aria-label={
            picking
              ? `Assign hold ${hold.id}`
              : readOnly
                ? `Hold ${hold.id}`
                : `Delete hold ${hold.id}`
          }
          onClick={(e) => handleBoxClick(e, hold)}
        />
      ))}

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
          Click a hold to assign it — Esc to cancel
        </div>
      )}
    </div>
  );
}

export default HoldOverlay;
