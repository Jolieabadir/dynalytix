/**
 * AdminView — every video across all users, the rater roster, and the exports.
 *
 * Only rendered for a profile with `is_admin`; the API answers 403 to anyone
 * else on every route used here, so the guard in App is a courtesy, not the
 * security boundary.
 *
 * Row actions follow the prep_status state machine from API_DATASET_A.md:
 * draft → Mark ready → ready → Close → closed, and Reopen back to draft.
 * Assigning picks a rater from /api/admin/raters and a cohort; the API
 * refuses a duplicate (409) and a rater with no profile (404), both of which
 * are shown as they come back.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  adminListVideos,
  adminListRaters,
  adminListAssignments,
  adminCreateAssignment,
  adminDeleteAssignment,
  adminMarkReady,
  adminCloseVideo,
  adminReopenVideo,
  adminUpdateRater,
  downloadAdminExport,
} from '../api/client';

const COHORTS = ['validated', 'overlap'];
const TIERS = ['open', 'validated'];

function shortId(id) {
  return id ? `${String(id).slice(0, 8)}…` : '—';
}

function errorText(err, fallback) {
  return err?.response?.data?.detail || err?.message || fallback;
}

function AdminView({ onOpenVideo }) {
  const [items, setItems] = useState([]);
  const [raters, setRaters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const raterName = useCallback(
    (userId) => raters.find((r) => r.user_id === userId)?.display_name || shortId(userId),
    [raters]
  );

  const reload = useCallback(async () => {
    setError(null);
    try {
      const [videos, roster] = await Promise.all([adminListVideos(), adminListRaters()]);
      setItems(videos);
      setRaters(roster);
    } catch (err) {
      setError(errorText(err, 'Could not load the admin data.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const replaceVideo = (video) =>
    setItems((prev) => prev.map((item) => (item.video.id === video.id ? { ...item, video } : item)));

  const runVideoAction = async (label, fn) => {
    setError(null);
    setNotice(null);
    try {
      const video = await fn();
      replaceVideo(video);
      setNotice(`${label}: ${video.filename} is now ${video.prep_status}.`);
    } catch (err) {
      setError(errorText(err, `${label} failed.`));
    }
  };

  return (
    <div className="admin-view">
      <div className="view-header">
        <h2>Admin</h2>
        <p className="view-subtitle">
          Every video across all users. Prep a video in My videos, mark it ready here, assign
          three raters, and export when they are done.
        </p>
      </div>

      {error && (
        <div className="error-message" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="saved-note" role="status">
          {notice}
        </div>
      )}

      <ExportPanel onError={setError} onNotice={setNotice} />

      <section className="admin-section">
        <h3>Videos</h3>
        {loading ? (
          <p>Loading…</p>
        ) : items.length === 0 ? (
          <p className="queue-empty">No videos yet.</p>
        ) : (
          <table className="data-table admin-videos-table">
            <thead>
              <tr>
                <th>Video</th>
                <th>Owner</th>
                <th>Dataset</th>
                <th>Prep status</th>
                <th>Assignments</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <VideoRow
                  key={item.video.id}
                  item={item}
                  raters={raters}
                  raterName={raterName}
                  onOpen={onOpenVideo}
                  onReady={() => runVideoAction('Mark ready', () => adminMarkReady(item.video.id))}
                  onClose={() => runVideoAction('Close', () => adminCloseVideo(item.video.id))}
                  onReopen={() => runVideoAction('Reopen', () => adminReopenVideo(item.video.id))}
                  onAssignmentsChanged={reload}
                  onError={setError}
                />
              ))}
            </tbody>
          </table>
        )}
      </section>

      <RatersPanel raters={raters} onSaved={(p) => setRaters((prev) => prev.map((r) => (r.user_id === p.user_id ? p : r)))} onError={setError} />
    </div>
  );
}

function VideoRow({ item, raters, raterName, onOpen, onReady, onClose, onReopen, onAssignmentsChanged, onError }) {
  const { video, assignment_count, done_count } = item;
  const [expanded, setExpanded] = useState(false);
  const [assignments, setAssignments] = useState(null);
  const [raterId, setRaterId] = useState('');
  const [cohort, setCohort] = useState('validated');
  const [busy, setBusy] = useState(false);

  const loadAssignments = useCallback(async () => {
    try {
      setAssignments(await adminListAssignments(video.id));
    } catch (err) {
      onError(errorText(err, 'Could not load assignments.'));
    }
  }, [video.id, onError]);

  useEffect(() => {
    if (expanded) loadAssignments();
  }, [expanded, loadAssignments]);

  const handleAssign = async () => {
    if (!raterId) {
      onError('Pick a rater to assign.');
      return;
    }
    if (!COHORTS.includes(cohort)) {
      onError(`Cohort must be one of: ${COHORTS.join(', ')}`);
      return;
    }
    setBusy(true);
    try {
      await adminCreateAssignment({ video_id: video.id, rater_user_id: raterId, cohort });
      setRaterId('');
      await loadAssignments();
      onAssignmentsChanged();
    } catch (err) {
      onError(
        err.response?.status === 409
          ? 'That rater is already assigned to this video.'
          : errorText(err, 'Could not assign the rater.')
      );
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (assignment) => {
    if (!window.confirm(`Remove ${raterName(assignment.rater_user_id)} from ${video.filename}? Labels they already wrote are kept.`)) {
      return;
    }
    setBusy(true);
    try {
      await adminDeleteAssignment(assignment.id);
      await loadAssignments();
      onAssignmentsChanged();
    } catch (err) {
      onError(errorText(err, 'Could not remove the assignment.'));
    } finally {
      setBusy(false);
    }
  };

  const assignedIds = new Set((assignments ?? []).map((a) => a.rater_user_id));
  const assignable = raters.filter((r) => !assignedIds.has(r.user_id));

  return (
    <>
      <tr data-testid={`admin-video-${video.id}`}>
        <td className="cell-primary">
          {video.filename}
          <div className="cell-sub">#{video.id}{video.route_grade ? ` · ${video.route_grade}` : ''}</div>
        </td>
        <td title={video.owner_user_id}>{raterName(video.owner_user_id)}</td>
        <td>{video.dataset}</td>
        <td>
          <span className={`status-pill prep-${video.prep_status}`}>{video.prep_status}</span>
        </td>
        <td>
          {assignment_count}
          {assignment_count > 0 && <span className="cell-sub"> ({done_count} done)</span>}
        </td>
        <td className="cell-actions">
          {onOpen && (
            <button type="button" className="btn-secondary" onClick={() => onOpen(video)}>
              Open
            </button>
          )}
          {video.prep_status === 'draft' && (
            <button type="button" className="btn-primary" onClick={onReady}>
              Mark ready
            </button>
          )}
          {video.prep_status === 'ready' && (
            <button type="button" className="btn-secondary" onClick={onClose}>
              Close
            </button>
          )}
          {video.prep_status !== 'draft' && (
            <button type="button" className="btn-secondary" onClick={onReopen}>
              Reopen
            </button>
          )}
          <button
            type="button"
            className="btn-secondary"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Hide raters' : 'Assign rater'}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="admin-assignments-row" data-testid={`admin-assignments-${video.id}`}>
          <td colSpan={6}>
            <div className="admin-assignments">
              <div className="assign-form">
                <label>
                  Rater
                  <select
                    value={raterId}
                    onChange={(e) => setRaterId(e.target.value)}
                    disabled={busy}
                    aria-label="Rater"
                  >
                    <option value="">Choose a rater…</option>
                    {assignable.map((r) => (
                      <option key={r.user_id} value={r.user_id}>
                        {r.display_name} ({r.tier})
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Cohort
                  <select
                    value={cohort}
                    onChange={(e) => setCohort(e.target.value)}
                    disabled={busy}
                    aria-label="Cohort"
                  >
                    {COHORTS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="button" className="btn-primary" onClick={handleAssign} disabled={busy || !raterId}>
                  Assign
                </button>
              </div>

              {assignments === null ? (
                <p>Loading assignments…</p>
              ) : assignments.length === 0 ? (
                <p className="queue-empty">No raters assigned yet (aim for 3).</p>
              ) : (
                <ul className="assignment-list">
                  {assignments.map((a) => (
                    <li key={a.id}>
                      <strong>{raterName(a.rater_user_id)}</strong> · {a.cohort} ·{' '}
                      <span className={`status-pill status-${a.status}`}>{a.status}</span>
                      <button
                        type="button"
                        className="btn-delete"
                        title="Remove assignment"
                        aria-label={`Remove ${raterName(a.rater_user_id)}`}
                        onClick={() => handleRemove(a)}
                        disabled={busy}
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function ExportPanel({ onError, onNotice }) {
  const [dataset, setDataset] = useState('A');
  const [busy, setBusy] = useState(null);

  const run = async (kind) => {
    setBusy(kind);
    onError(null);
    try {
      const filename = await downloadAdminExport(kind, { dataset });
      onNotice(`Downloaded ${filename}.`);
    } catch (err) {
      onError(errorText(err, 'Export failed.'));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="admin-section admin-exports">
      <h3>Exports</h3>
      <div className="export-controls">
        <label>
          Dataset
          <select value={dataset} onChange={(e) => setDataset(e.target.value)} aria-label="Export dataset">
            <option value="A">A</option>
            <option value="B">B</option>
            <option value="all">all</option>
          </select>
        </label>
        <button type="button" className="btn-primary" onClick={() => run('long')} disabled={Boolean(busy)}>
          {busy === 'long' ? 'Exporting…' : 'Export long CSV'}
        </button>
        <button type="button" className="btn-secondary" onClick={() => run('full')} disabled={Boolean(busy)}>
          {busy === 'full' ? 'Exporting…' : 'Export full CSV'}
        </button>
      </div>
      <p className="cell-sub">
        Long = one row per (video, move, rater, lens, field) — the Krippendorff input. Full = one
        row per pose frame per rater, large.
      </p>
    </section>
  );
}

function RatersPanel({ raters, onSaved, onError }) {
  return (
    <section className="admin-section">
      <h3>Raters</h3>
      {raters.length === 0 ? (
        <p className="queue-empty">No rater profiles yet.</p>
      ) : (
        <table className="data-table admin-raters-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>User</th>
              <th>Experience</th>
              <th>Tier</th>
              <th>Validation note</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {raters.map((r) => (
              <RaterRow key={r.user_id} rater={r} onSaved={onSaved} onError={onError} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function RaterRow({ rater, onSaved, onError }) {
  const [tier, setTier] = useState(rater.tier);
  const [note, setNote] = useState(rater.validation_note || '');
  const [busy, setBusy] = useState(false);

  const dirty = tier !== rater.tier || note !== (rater.validation_note || '');

  const handleSave = async () => {
    setBusy(true);
    try {
      const saved = await adminUpdateRater(rater.user_id, { tier, validation_note: note });
      onSaved(saved);
    } catch (err) {
      onError(errorText(err, 'Could not update the rater.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr data-testid={`admin-rater-${rater.user_id}`}>
      <td className="cell-primary">
        {rater.display_name}
        {rater.is_admin && <span className="cell-sub"> · admin</span>}
      </td>
      <td title={rater.user_id}>{shortId(rater.user_id)}</td>
      <td>
        {rater.years_climbing != null ? `${rater.years_climbing} yrs` : '—'}
        {rater.highest_grade ? ` · ${rater.highest_grade}` : ''}
        {rater.research_background ? ' · research' : ''}
        {rater.bio && (
          <div className="cell-sub admin-rater-bio" title={rater.bio}>
            {rater.bio}
          </div>
        )}
      </td>
      <td>
        <select value={tier} onChange={(e) => setTier(e.target.value)} aria-label={`Tier for ${rater.display_name}`} disabled={busy}>
          {TIERS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </td>
      <td>
        <input
          className="note-input"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Why this rater counts as validated"
          aria-label={`Validation note for ${rater.display_name}`}
          disabled={busy}
        />
      </td>
      <td>
        <button type="button" className="btn-primary" onClick={handleSave} disabled={busy || !dirty}>
          {busy ? 'Saving…' : 'Save'}
        </button>
      </td>
    </tr>
  );
}

export default AdminView;
