/**
 * AdminView — every video across all users, the rater roster, the athletes
 * table, and the exports.
 *
 * Only rendered for a profile with `is_admin`; the API answers 403 to anyone
 * else on every route used here, so the guard in App is a courtesy, not the
 * security boundary.
 *
 * One dataset. Row actions follow the prep_status state machine:
 * draft → Mark ready → ready → Close → closed, and Reopen back to draft.
 * Mark ready can be refused (422) with a `problems` list — missing
 * provenance, no athlete / birth year, or an athlete who may be under 18 —
 * which is shown as it comes back.
 *
 * Mark ready draws the video into the 3-rater reliability overlap subset at
 * random (~25%); every other video gets 1 rater. The Overlap checkbox is the
 * admin override, allowed only while the video has no assignments (409
 * otherwise, so it is disabled here then). Assigning picks a validated rater;
 * the API refuses (409) a duplicate, an unvalidated rater, a video that is
 * not ready, and one already at its `rater_target`.
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
  adminSetOverlap,
  adminSetCameraOverride,
  adminUpdateRater,
  adminListAthletes,
  adminCreateAthlete,
  adminUpdateAthlete,
  downloadAdminExport,
} from '../api/client';
import { formatLabel } from '../utils/taxonomy';
import { athleteLabel, shortId } from '../utils/prepMetadata';

const ATHLETE_CATEGORIES = ['men', 'women'];

function shortUser(id) {
  return id ? `${shortId(id)}…` : '—';
}

function errorText(err, fallback) {
  return err?.response?.data?.detail || err?.message || fallback;
}

function AdminView({ onOpenVideo }) {
  const [items, setItems] = useState([]);
  const [raters, setRaters] = useState([]);
  const [athletes, setAthletes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [problems, setProblems] = useState(null);
  const [notice, setNotice] = useState(null);

  const raterName = useCallback(
    (userId) => raters.find((r) => r.user_id === userId)?.display_name || shortUser(userId),
    [raters]
  );

  const showError = useCallback((message, list = null) => {
    setError(message);
    setProblems(list);
  }, []);

  const reload = useCallback(async () => {
    setError(null);
    setProblems(null);
    try {
      const [videos, roster, athleteList] = await Promise.all([
        adminListVideos(),
        adminListRaters(),
        adminListAthletes(),
      ]);
      setItems(videos);
      setRaters(roster);
      setAthletes(athleteList);
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
    setProblems(null);
    setNotice(null);
    try {
      const video = await fn();
      replaceVideo(video);
      setNotice(`${label}: ${video.filename} is now ${video.prep_status}.`);
    } catch (err) {
      const list = err?.response?.data?.problems;
      if (Array.isArray(list) && list.length) {
        showError(`${label} refused:`, list);
      } else {
        showError(errorText(err, `${label} failed.`));
      }
    }
  };

  const handleOverlap = async (video, irrOverlap) => {
    setError(null);
    setProblems(null);
    setNotice(null);
    try {
      const updated = await adminSetOverlap(video.id, irrOverlap);
      replaceVideo(updated);
      setNotice(
        `${updated.filename}: overlap ${updated.irr_overlap ? 'on (3 raters)' : 'off (1 rater)'}.`
      );
    } catch (err) {
      showError(
        err?.response?.status === 409
          ? 'Overlap can only be changed before any rater is assigned.'
          : errorText(err, 'Could not change the overlap flag.')
      );
    }
  };

  const handleCameraOverride = async (video, override, note) => {
    setError(null);
    setProblems(null);
    setNotice(null);
    try {
      const updated = await adminSetCameraOverride(video.id, override, note);
      replaceVideo(updated);
      setNotice(
        `${updated.filename}: camera check ${updated.camera_override ? 'overridden' : 'enforced again'}.`
      );
    } catch (err) {
      showError(
        err?.response?.status === 400
          ? 'Add a note saying why this clip is acceptable before overriding.'
          : errorText(err, 'Could not change the camera override.')
      );
    }
  };

  const athleteById = (id) => athletes.find((a) => a.athlete_id === id) ?? null;

  return (
    <div className="admin-view">
      <div className="view-header">
        <h2>Admin</h2>
        <p className="view-subtitle">
          Every video across all users. Prep a video in Upload &amp; prep, mark it ready here
          (a random ~25% are drawn into the 3-rater overlap subset; the rest get 1 rater), assign
          validated raters, and export when they are done.
        </p>
      </div>

      {error && (
        <div className="error-message" role="alert">
          {error}
          {problems && (
            <ul className="missing-list" data-testid="ready-problems">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {notice && (
        <div className="saved-note" role="status">
          {notice}
        </div>
      )}

      <ExportPanel onError={showError} onNotice={setNotice} />

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
                <th>Source</th>
                <th>Camera</th>
                <th>Athlete</th>
                <th>Prep status</th>
                <th>Overlap</th>
                <th>Raters</th>
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
                  athlete={athleteById(item.video.athlete_id)}
                  onOpen={onOpenVideo}
                  onReady={() => runVideoAction('Mark ready', () => adminMarkReady(item.video.id))}
                  onClose={() => runVideoAction('Close', () => adminCloseVideo(item.video.id))}
                  onReopen={() => runVideoAction('Reopen', () => adminReopenVideo(item.video.id))}
                  onOverlap={(value) => handleOverlap(item.video, value)}
                  onCameraOverride={(override, note) => handleCameraOverride(item.video, override, note)}
                  onAssignmentsChanged={reload}
                  onError={showError}
                />
              ))}
            </tbody>
          </table>
        )}
      </section>

      <RatersPanel
        raters={raters}
        onSaved={(p) => setRaters((prev) => prev.map((r) => (r.user_id === p.user_id ? p : r)))}
        onError={showError}
      />

      <AthletesPanel
        athletes={athletes}
        onCreated={(a) => setAthletes((prev) => [...prev, a])}
        onSaved={(a) => setAthletes((prev) => prev.map((x) => (x.athlete_id === a.athlete_id ? a : x)))}
        onError={showError}
        onNotice={setNotice}
      />
    </div>
  );
}

function VideoRow({
  item,
  raters,
  raterName,
  athlete,
  onOpen,
  onReady,
  onClose,
  onReopen,
  onOverlap,
  onCameraOverride,
  onAssignmentsChanged,
  onError,
}) {
  const { video, assignment_count, done_count } = item;
  const [expanded, setExpanded] = useState(false);
  const [assignments, setAssignments] = useState(null);
  const [raterId, setRaterId] = useState('');
  const [busy, setBusy] = useState(false);

  const target = video.rater_target ?? (video.irr_overlap ? 3 : 1);
  // The loaded list is fresher than the row count right after an assign.
  const count = assignments ? assignments.length : assignment_count;
  const atTarget = count >= target;
  const overlapLocked = assignment_count > 0 || (assignments?.length ?? 0) > 0;

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
    setBusy(true);
    try {
      await adminCreateAssignment({ video_id: video.id, rater_user_id: raterId });
      setRaterId('');
      await loadAssignments();
      onAssignmentsChanged();
    } catch (err) {
      onError(
        err.response?.status === 409
          ? err.response?.data?.detail || 'That rater cannot be assigned to this video.'
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
  // The API only assigns validated raters; offering anyone else would just 409.
  const assignable = raters.filter((r) => r.is_validated === true && !assignedIds.has(r.user_id));

  const assignBlockedReason =
    video.prep_status !== 'ready'
      ? `Mark the video ready before assigning (it is ${video.prep_status}).`
      : atTarget
        ? `Rater target reached (${count} / ${target}).`
        : null;

  return (
    <>
      <tr data-testid={`admin-video-${video.id}`}>
        <td className="cell-primary">
          {video.filename}
          <div className="cell-sub">#{video.id}{video.route_grade ? ` · ${video.route_grade}` : ''}</div>
        </td>
        <td title={video.owner_user_id}>{raterName(video.owner_user_id)}</td>
        <td data-testid={`admin-source-${video.id}`}>
          {formatLabel(video.source_type) || '—'}
          {video.event_name && <div className="cell-sub">{video.event_name}</div>}
        </td>
        <td data-testid={`admin-camera-${video.id}`}>
          <CameraCell video={video} onOverride={onCameraOverride} />
        </td>
        <td title={athlete ? athleteLabel(athlete) : video.athlete_id || undefined}>
          {video.athlete_id ? shortId(video.athlete_id) : '—'}
        </td>
        <td>
          <span className={`status-pill prep-${video.prep_status}`}>{video.prep_status}</span>
        </td>
        <td data-testid={`admin-overlap-${video.id}`}>
          <label
            className="checkbox-label"
            title={overlapLocked ? 'Locked: raters are already assigned' : 'Override the random draw'}
          >
            <input
              type="checkbox"
              checked={Boolean(video.irr_overlap)}
              onChange={(e) => onOverlap(e.target.checked)}
              disabled={overlapLocked}
              aria-label={`Overlap for ${video.filename}`}
            />
            <span>{video.irr_overlap ? 'yes' : 'no'}</span>
          </label>
          <div className="cell-sub">
            {video.irr_overlap_set_by ? formatLabel(video.irr_overlap_set_by) : 'not drawn yet'}
          </div>
        </td>
        <td data-testid={`admin-raters-${video.id}`}>
          {assignment_count} / {target}
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
            {expanded ? 'Hide raters' : 'Raters'}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="admin-assignments-row" data-testid={`admin-assignments-${video.id}`}>
          <td colSpan={8}>
            <div className="admin-assignments">
              <div className="assign-form">
                <label>
                  Rater
                  <select
                    value={raterId}
                    onChange={(e) => setRaterId(e.target.value)}
                    disabled={busy || Boolean(assignBlockedReason)}
                    aria-label="Rater"
                  >
                    <option value="">Choose a validated rater…</option>
                    {assignable.map((r) => (
                      <option key={r.user_id} value={r.user_id}>
                        {r.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={handleAssign}
                  disabled={busy || !raterId || Boolean(assignBlockedReason)}
                >
                  Assign
                </button>
                {assignBlockedReason && (
                  <span className="cell-sub" data-testid={`assign-blocked-${video.id}`}>
                    {assignBlockedReason}
                  </span>
                )}
              </div>

              {assignments === null ? (
                <p>Loading assignments…</p>
              ) : assignments.length === 0 ? (
                <p className="queue-empty">
                  No raters assigned yet (target {target}{video.irr_overlap ? ', overlap subset' : ''}).
                </p>
              ) : (
                <ul className="assignment-list">
                  {assignments.map((a) => (
                    <li key={a.id}>
                      <strong>{raterName(a.rater_user_id)}</strong> ·{' '}
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

/**
 * The worker's camera check for one clip (pan / zoom / cut). A failing clip
 * cannot be marked ready unless an admin overrides it with a note; the
 * problems stay listed after an override so it is clear what was accepted.
 */
function CameraCell({ video, onOverride }) {
  const [note, setNote] = useState('');
  if (video.source_type === 'community') return <span className="cell-sub">not checked</span>;
  if (video.pose_status !== 'done') return <span className="cell-sub">waiting for pose</span>;

  const problems = video.camera_problems ?? [];
  const metrics =
    video.camera_motion_score != null
      ? `motion ${Number(video.camera_motion_score).toFixed(4)}` +
        (video.camera_drift != null ? ` · drift ${Number(video.camera_drift).toFixed(3)}` : '') +
        ` · zoom ${Number(video.camera_zoom_range).toFixed(2)}`
      : null;

  if (problems.length === 0) {
    return (
      <>
        <span className="status-pill camera-ok">steady</span>
        {metrics && <div className="cell-sub">{metrics}</div>}
      </>
    );
  }

  return (
    <div className="camera-cell">
      <span className={`status-pill ${video.camera_override ? 'camera-overridden' : 'camera-fail'}`}>
        {video.camera_override ? 'overridden' : 'fails'}
      </span>
      <ul className="missing-list" data-testid={`camera-problems-${video.id}`}>
        {problems.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
      {metrics && <div className="cell-sub">{metrics}</div>}
      {video.camera_override ? (
        <>
          <div className="cell-sub">Note: {video.camera_override_note}</div>
          <button type="button" className="btn-secondary" onClick={() => onOverride(false, '')}>
            Undo override
          </button>
        </>
      ) : (
        <div className="camera-override-form">
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Why is this clip OK?"
            aria-label={`Camera override note for ${video.filename}`}
          />
          <button
            type="button"
            className="btn-secondary"
            disabled={!note.trim()}
            onClick={() => onOverride(true, note.trim())}
          >
            Override
          </button>
        </div>
      )}
    </div>
  );
}

function ExportPanel({ onError, onNotice }) {
  const [includeCommunity, setIncludeCommunity] = useState(false);
  const [overlapOnly, setOverlapOnly] = useState(false);
  const [busy, setBusy] = useState(null);

  const run = async (kind) => {
    setBusy(kind);
    onError(null);
    try {
      const params = { include_community: includeCommunity };
      if (kind === 'long') params.overlap_only = overlapOnly;
      const filename = await downloadAdminExport(kind, params);
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
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={includeCommunity}
            onChange={(e) => setIncludeCommunity(e.target.checked)}
          />
          <span>Include community videos</span>
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={overlapOnly}
            onChange={(e) => setOverlapOnly(e.target.checked)}
          />
          <span>Overlap subset only (long)</span>
        </label>
        <button type="button" className="btn-primary" onClick={() => run('long')} disabled={Boolean(busy)}>
          {busy === 'long' ? 'Exporting…' : 'Long (IRR input)'}
        </button>
        <button type="button" className="btn-secondary" onClick={() => run('full')} disabled={Boolean(busy)}>
          {busy === 'full' ? 'Exporting…' : 'Full'}
        </button>
      </div>
      <p className="cell-sub">
        Long = one row per (video, move, rater, lens, field) — the Krippendorff input; with
        &quot;Overlap subset only&quot; it keeps just the 3-rater videos. Full = one row per pose
        frame per rater, large. Community (self-upload) videos are left out unless included.
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
              <th>Validated</th>
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
  const [validated, setValidated] = useState(rater.is_validated === true);
  const [note, setNote] = useState(rater.validation_note || '');
  const [busy, setBusy] = useState(false);

  const dirty = validated !== (rater.is_validated === true) || note !== (rater.validation_note || '');

  const handleSave = async () => {
    setBusy(true);
    try {
      const saved = await adminUpdateRater(rater.user_id, { is_validated: validated, validation_note: note });
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
      <td title={rater.user_id}>{shortUser(rater.user_id)}</td>
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
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={validated}
            onChange={(e) => setValidated(e.target.checked)}
            aria-label={`Validated: ${rater.display_name}`}
            disabled={busy}
          />
          <span>{validated ? 'yes' : 'no'}</span>
        </label>
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

/** Form strings → the athlete payload. Empty numbers are omitted (no clear). */
function athletePayload(form, { clearText }) {
  const payload = {};
  const url = form.ifsc_profile_url.trim();
  if (url || clearText) payload.ifsc_profile_url = url;
  for (const key of ['height_cm', 'birth_year']) {
    if (form[key] === '') continue;
    const n = Number(form[key]);
    if (!Number.isInteger(n)) throw new Error(`${key === 'height_cm' ? 'Height' : 'Birth year'} must be a whole number.`);
    payload[key] = n;
  }
  if (form.category || clearText) payload.category = form.category;
  return payload;
}

const EMPTY_ATHLETE_FORM = { ifsc_profile_url: '', height_cm: '', birth_year: '', category: '' };

function athleteToForm(a) {
  return {
    ifsc_profile_url: a.ifsc_profile_url ?? '',
    height_cm: a.height_cm != null ? String(a.height_cm) : '',
    birth_year: a.birth_year != null ? String(a.birth_year) : '',
    category: a.category ?? '',
  };
}

function AthleteFields({ form, onChange, disabled, idPrefix }) {
  const set = (key) => (e) => onChange({ ...form, [key]: e.target.value });
  return (
    <>
      <label>
        IFSC profile URL
        <input
          className="note-input"
          type="url"
          value={form.ifsc_profile_url}
          onChange={set('ifsc_profile_url')}
          placeholder="https://ifsc.results.info/athlete/…"
          aria-label={`${idPrefix} IFSC profile URL`}
          disabled={disabled}
        />
      </label>
      <label>
        Height (cm)
        <input
          className="note-input"
          type="number"
          min="100"
          max="250"
          value={form.height_cm}
          onChange={set('height_cm')}
          aria-label={`${idPrefix} height (cm)`}
          disabled={disabled}
        />
      </label>
      <label>
        Birth year
        <input
          className="note-input"
          type="number"
          min="1900"
          max="2100"
          value={form.birth_year}
          onChange={set('birth_year')}
          aria-label={`${idPrefix} birth year`}
          disabled={disabled}
        />
      </label>
      <label>
        Category
        <select
          value={form.category}
          onChange={set('category')}
          aria-label={`${idPrefix} category`}
          disabled={disabled}
        >
          <option value="">—</option>
          {ATHLETE_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}

function AthletesPanel({ athletes, onCreated, onSaved, onError, onNotice }) {
  const [form, setForm] = useState(EMPTY_ATHLETE_FORM);
  const [busy, setBusy] = useState(false);

  const handleCreate = async () => {
    let payload;
    try {
      payload = athletePayload(form, { clearText: false });
    } catch (err) {
      onError(err.message);
      return;
    }
    if (!payload.ifsc_profile_url) {
      onError('Add the athlete’s IFSC profile URL — it is how athletes are told apart (there is no name field).');
      return;
    }
    setBusy(true);
    onError(null);
    try {
      const created = await adminCreateAthlete(payload);
      onCreated(created);
      setForm(EMPTY_ATHLETE_FORM);
      onNotice(`Athlete ${shortId(created.athlete_id)} added.`);
    } catch (err) {
      onError(
        err?.response?.status === 409
          ? 'An athlete with that IFSC profile URL already exists.'
          : errorText(err, 'Could not add the athlete.')
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="admin-section admin-athletes" data-testid="admin-athletes">
      <h3>Athletes</h3>
      <p className="cell-sub">
        Pseudonymous: no names. The IFSC profile URL is admin-only and never exported; height
        and birth year are (birth year drives the 18+ check at Mark ready).
      </p>

      <div className="assign-form athlete-create-form" data-testid="athlete-create-form">
        <AthleteFields form={form} onChange={setForm} disabled={busy} idPrefix="New athlete" />
        <button type="button" className="btn-primary" onClick={handleCreate} disabled={busy}>
          {busy ? 'Adding…' : 'Add athlete'}
        </button>
      </div>

      {athletes.length === 0 ? (
        <p className="queue-empty">No athletes yet.</p>
      ) : (
        <table className="data-table admin-athletes-table">
          <thead>
            <tr>
              <th>Id</th>
              <th>IFSC profile</th>
              <th>Height</th>
              <th>Birth year</th>
              <th>Category</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {athletes.map((a) => (
              <AthleteRow key={a.athlete_id} athlete={a} onSaved={onSaved} onError={onError} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function AthleteRow({ athlete, onSaved, onError }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(() => athleteToForm(athlete));
  const [busy, setBusy] = useState(false);
  const label = shortId(athlete.athlete_id);

  const handleSave = async () => {
    let payload;
    try {
      payload = athletePayload(form, { clearText: true });
    } catch (err) {
      onError(err.message);
      return;
    }
    setBusy(true);
    try {
      const saved = await adminUpdateAthlete(athlete.athlete_id, payload);
      onSaved(saved);
      setEditing(false);
    } catch (err) {
      onError(
        err?.response?.status === 409
          ? 'An athlete with that IFSC profile URL already exists.'
          : errorText(err, 'Could not update the athlete.')
      );
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    return (
      <tr data-testid={`admin-athlete-${athlete.athlete_id}`}>
        <td title={athlete.athlete_id}>{label}</td>
        <td colSpan={4}>
          <div className="assign-form">
            <AthleteFields form={form} onChange={setForm} disabled={busy} idPrefix={`Athlete ${label}`} />
          </div>
        </td>
        <td className="cell-actions">
          <button type="button" className="btn-primary" onClick={handleSave} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              setForm(athleteToForm(athlete));
              setEditing(false);
            }}
            disabled={busy}
          >
            Cancel
          </button>
        </td>
      </tr>
    );
  }

  return (
    <tr data-testid={`admin-athlete-${athlete.athlete_id}`}>
      <td title={athlete.athlete_id}>{label}</td>
      <td>
        {athlete.ifsc_profile_url ? (
          <a href={athlete.ifsc_profile_url} target="_blank" rel="noreferrer noopener">
            {athlete.ifsc_profile_url.replace(/^https?:\/\//, '')}
          </a>
        ) : (
          '—'
        )}
      </td>
      <td>
        {athlete.height_cm != null ? `${athlete.height_cm} cm` : '—'}
        <div className="cell-sub">{formatLabel(athlete.height_source)}</div>
      </td>
      <td>{athlete.birth_year ?? '—'}</td>
      <td>{athlete.category ?? '—'}</td>
      <td>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => {
            setForm(athleteToForm(athlete));
            setEditing(true);
          }}
          aria-label={`Edit athlete ${label}`}
        >
          Edit
        </button>
      </td>
    </tr>
  );
}

export default AdminView;
