/**
 * ProgressStrip — the persistent "how far am I" header.
 *
 * Answers the question the old UI never did: how much is left? Three counts,
 * then the two actions that move a session forward.
 *
 * The counts, precisely:
 * - defined: moves that exist at all.
 * - labeled: moves carrying their three lenses. Every move created through
 *   MoveForm is fully labeled on creation, so in practice this tracks defined —
 *   it is separate because a move can be created and its environment/outcome
 *   POST can fail, and because moves loaded from the server may predate them.
 * - tagged: moves with at least one sensation frame tag.
 */
import useStore from '../store/useStore';
import { progressCounts } from '../utils/progress';

function ProgressStrip({
  onSaveAndNext,
  onFinish,
  busy = false,
  canSaveNext = true,
  // Export needs the worker's pose CSV; until then the button is disabled and
  // says why on hover.
  canExport = true,
  exportBlockedReason = '',
}) {
  const moves = useStore((s) => s.moves);
  const frameTags = useStore((s) => s.frameTags);
  const currentMove = useStore((s) => s.currentMove);

  const { defined, labeled, tagged } = progressCounts(moves, frameTags, currentMove);

  return (
    <div className="progress-strip">
      <span className="progress-counts" data-testid="progress-counts">
        {defined} {defined === 1 ? 'move' : 'moves'} defined
        {' · '}
        {labeled} labeled
        {' · '}
        {tagged} tagged
      </span>

      <div className="progress-actions">
        <button
          type="button"
          className="btn-secondary"
          onClick={onSaveAndNext}
          disabled={busy || !canSaveNext}
        >
          Save &amp; Next Move
        </button>
        <button
          type="button"
          className="btn-primary"
          onClick={onFinish}
          disabled={busy || !canExport}
          title={!canExport ? exportBlockedReason : undefined}
          aria-disabled={busy || !canExport}
        >
          {busy ? 'Exporting…' : 'Finish & Export'}
        </button>
      </div>
    </div>
  );
}

export default ProgressStrip;
