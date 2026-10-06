/**
 * VideoMetadataPanel — the prep-pass strip above the labeling area.
 *
 * Shows the video's prep_status and its reliability-overlap flag. For an
 * admin it is also the provenance form (source, clip window, license, event,
 * athlete, plus route grade / wall type / camera angle / notes → PUT
 * /api/admin/videos/{id}/metadata), the "Import metadata JSON" button for the
 * sidecar scripts/prepare_clip.py writes, and the "Mark ready to rate"
 * button. All of that is admin-only on the API, so a non-admin owner (the
 * dormant community self-upload flow) sees the badge and the metadata
 * read-only.
 *
 * Mark ready can be refused with 422 + `problems` (missing provenance, no
 * athlete / birth year, or an athlete who may be under 18 on the event date);
 * the list is shown as-is.
 *
 * Once a video is ready or closed its holds and moves are locked for anyone
 * but an admin. The API would answer 403; this says so before the click.
 */
import { useEffect, useRef, useState } from 'react';
import useStore from '../store/useStore';
import {
  adminUpdateVideoMetadata,
  adminMarkReady,
  adminReopenVideo,
  adminListAthletes,
} from '../api/client';
import { formatLabel } from '../utils/taxonomy';
import { IMPORTABLE_KEYS, parseMetadataJson, athleteLabel, shortId } from '../utils/prepMetadata';

/** The three source types a paper clip can have; /api/config is the source of truth. */
const FALLBACK_SOURCE_TYPES = ['public_broadcast', 'cc_license', 'research_dataset'];

/**
 * Form fields in display order. `kind`: text (default) | number | date |
 * textarea | source_type | athlete. Integers have no "clear" on the API, so
 * an empty number field is omitted; text, date and athlete send "" to clear.
 */
const FIELDS = [
  { key: 'source_type', label: 'Source type', kind: 'source_type' },
  { key: 'source_url', label: 'Source URL', placeholder: 'https://…' },
  { key: 'clip_start_ms', label: 'Clip start (ms)', kind: 'number' },
  { key: 'clip_end_ms', label: 'Clip end (ms)', kind: 'number' },
  { key: 'license', label: 'License', placeholder: 'CC BY 4.0, broadcast fair use, dataset license…' },
  { key: 'event_name', label: 'Event name', placeholder: 'IFSC World Cup Innsbruck 2025 — semi-final' },
  { key: 'event_date', label: 'Event date', kind: 'date' },
  { key: 'athlete_id', label: 'Athlete', kind: 'athlete' },
  { key: 'route_grade', label: 'Route grade', placeholder: 'V4, 6b+' },
  { key: 'wall_type', label: 'Wall type', placeholder: 'competition wall, board, set boulder' },
  { key: 'camera_angle', label: 'Camera angle', placeholder: 'side, front, 45°' },
  { key: 'notes', label: 'Notes', kind: 'textarea' },
];

function toFormValue(value) {
  return value === null || value === undefined ? '' : String(value);
}

function fromVideo(video) {
  return Object.fromEntries(FIELDS.map((f) => [f.key, toFormValue(video?.[f.key])]));
}

function readFileText(file) {
  if (typeof file.text === 'function') return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(reader.error || new Error('Could not read the file.'));
    reader.readAsText(file);
  });
}

function errorText(err, fallback) {
  return err?.response?.data?.detail || err?.message || fallback;
}

function VideoMetadataPanel() {
  const currentVideo = useStore((s) => s.currentVideo);
  const setCurrentVideo = useStore((s) => s.setCurrentVideo);
  const profile = useStore((s) => s.profile);
  const config = useStore((s) => s.config);
  const setReadOnlyStructure = useStore((s) => s.setReadOnlyStructure);

  const isAdmin = Boolean(profile?.is_admin);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(() => fromVideo(currentVideo));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [problems, setProblems] = useState(null);
  const [notice, setNotice] = useState(null);
  const [athletes, setAthletes] = useState(null);
  const fileInputRef = useRef(null);

  const videoId = currentVideo?.id;
  const prepStatus = currentVideo?.prep_status ?? 'draft';
  const locked = prepStatus !== 'draft';

  const sourceTypes = config?.source_types?.length ? config.source_types : FALLBACK_SOURCE_TYPES;

  // A locked video freezes holds/moves for a non-admin owner. Admins keep
  // editing (the API lets them), so the flag follows both.
  useEffect(() => {
    setReadOnlyStructure(locked && !isAdmin);
    return () => setReadOnlyStructure(false);
  }, [locked, isAdmin, setReadOnlyStructure]);

  // Re-seed the form when a different video is opened.
  useEffect(() => {
    setForm(fromVideo(currentVideo));
    setError(null);
    setProblems(null);
    setNotice(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  // The athlete picker's options: admin only, loaded the first time the form opens.
  useEffect(() => {
    if (!open || !isAdmin || athletes !== null) return;
    let active = true;
    adminListAthletes()
      .then((list) => active && setAthletes(list))
      .catch((err) => {
        if (!active) return;
        setAthletes([]);
        setError(errorText(err, 'Could not load the athletes list.'));
      });
    return () => {
      active = false;
    };
  }, [open, isAdmin, athletes]);

  if (!currentVideo) return null;

  const update = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSave = async () => {
    setBusy(true);
    setError(null);
    setProblems(null);
    setNotice(null);
    try {
      const payload = {};
      for (const f of FIELDS) {
        const raw = form[f.key];
        if (f.kind === 'number') {
          if (raw === '' || raw === null) continue; // the API has no "clear" for ints
          const n = Number(raw);
          if (!Number.isInteger(n) || n < 0) {
            setError(`${f.label} must be a whole number of milliseconds.`);
            setBusy(false);
            return;
          }
          payload[f.key] = n;
        } else if (f.kind === 'source_type') {
          if (raw) payload[f.key] = raw; // not nullable; empty means unchanged
        } else {
          payload[f.key] = raw ?? ''; // '' clears a text/date/athlete field
        }
      }
      const video = await adminUpdateVideoMetadata(videoId, payload);
      setCurrentVideo({ ...currentVideo, ...video });
      setForm(fromVideo({ ...currentVideo, ...video }));
      setNotice('Video details saved.');
    } catch (err) {
      setError(errorText(err, 'Could not save the video details.'));
    } finally {
      setBusy(false);
    }
  };

  const handleImportFile = async (event) => {
    const file = event.target.files?.[0];
    // Reset so picking the same file again still fires onChange.
    event.target.value = '';
    if (!file) return;
    setError(null);
    setProblems(null);
    setNotice(null);
    try {
      const { values, ignored } = parseMetadataJson(await readFileText(file));
      const count = Object.keys(values).length;
      if (count === 0) {
        setError(`${file.name} has none of the metadata keys (${IMPORTABLE_KEYS.join(', ')}).`);
        return;
      }
      setForm((prev) => ({ ...prev, ...values }));
      setOpen(true);
      setNotice(
        `Filled ${count} field${count === 1 ? '' : 's'} from ${file.name} — review, then Save details.` +
          (ignored.length ? ` Ignored: ${ignored.join(', ')}.` : '')
      );
    } catch (err) {
      setError(err.message || 'Could not read that file.');
    }
  };

  const handleReady = async () => {
    if (!window.confirm('Mark this video ready to rate? Holds and moves lock for everyone but admins.')) return;
    setBusy(true);
    setError(null);
    setProblems(null);
    try {
      const video = await adminMarkReady(videoId);
      setCurrentVideo({ ...currentVideo, ...video });
      setNotice(
        `Marked ready to rate${video.irr_overlap ? ' — drawn into the 3-rater overlap subset' : ''}. Assign raters from the Admin tab.`
      );
    } catch (err) {
      const list = err.response?.data?.problems;
      if (Array.isArray(list) && list.length) {
        setError('Cannot mark ready yet:');
        setProblems(list);
      } else {
        setError(errorText(err, 'Could not mark the video ready.'));
      }
    } finally {
      setBusy(false);
    }
  };

  const handleReopen = async () => {
    setBusy(true);
    setError(null);
    setProblems(null);
    try {
      const video = await adminReopenVideo(videoId);
      setCurrentVideo({ ...currentVideo, ...video });
      setNotice('Reopened: holds and moves can be edited again.');
    } catch (err) {
      setError(errorText(err, 'Could not reopen the video.'));
    } finally {
      setBusy(false);
    }
  };

  const overlapText = currentVideo.irr_overlap
    ? `overlap: yes${currentVideo.irr_overlap_set_by ? ` (${currentVideo.irr_overlap_set_by})` : ''}`
    : `overlap: ${currentVideo.irr_overlap_set_by ? `no (${currentVideo.irr_overlap_set_by})` : 'not drawn yet'}`;

  const athleteOptions = athletes ?? [];
  const athleteKnown = !form.athlete_id || athleteOptions.some((a) => a.athlete_id === form.athlete_id);

  const renderInput = (f) => {
    const common = { value: form[f.key] ?? '', disabled: busy };
    if (f.kind === 'textarea') {
      return (
        <textarea
          className="description-textarea"
          rows="2"
          {...common}
          onChange={(e) => update(f.key, e.target.value)}
        />
      );
    }
    if (f.kind === 'source_type') {
      const options = sourceTypes.includes(form.source_type) || !form.source_type
        ? sourceTypes
        : [...sourceTypes, form.source_type];
      return (
        <select className="auth-input" {...common} onChange={(e) => update(f.key, e.target.value)}>
          {!form.source_type && <option value="">Choose…</option>}
          {options.map((t) => (
            <option key={t} value={t}>
              {formatLabel(t)}
            </option>
          ))}
        </select>
      );
    }
    if (f.kind === 'athlete') {
      return (
        <select className="auth-input" {...common} onChange={(e) => update(f.key, e.target.value)}>
          <option value="">{athletes === null ? 'Loading athletes…' : 'No athlete'}</option>
          {!athleteKnown && <option value={form.athlete_id}>Unknown athlete {shortId(form.athlete_id)}</option>}
          {athleteOptions.map((a) => (
            <option key={a.athlete_id} value={a.athlete_id}>
              {athleteLabel(a)}
            </option>
          ))}
        </select>
      );
    }
    return (
      <input
        className="auth-input"
        type={f.kind === 'number' ? 'number' : f.kind === 'date' ? 'date' : 'text'}
        min={f.kind === 'number' ? 0 : undefined}
        placeholder={f.placeholder}
        {...common}
        onChange={(e) => update(f.key, e.target.value)}
      />
    );
  };

  const readOnlyValue = (f) => {
    const v = currentVideo[f.key];
    if (v === null || v === undefined || v === '') return '—';
    if (f.kind === 'source_type') return formatLabel(v);
    if (f.kind === 'athlete') return shortId(v);
    return String(v);
  };

  return (
    <div className="video-meta-panel" data-testid="video-meta-panel">
      <div className="video-meta-header">
        <span className="video-meta-title">
          <strong>{currentVideo.filename}</strong>
          {' · '}
          <span className={`status-pill prep-${prepStatus}`} data-testid="prep-status">
            {prepStatus}
          </span>
          {' · '}
          <span className="cell-sub" data-testid="overlap-status">
            {overlapText}
            {currentVideo.rater_target ? ` · target ${currentVideo.rater_target} rater${currentVideo.rater_target === 1 ? '' : 's'}` : ''}
          </span>
        </span>
        <div className="video-meta-actions">
          <button type="button" className="btn-secondary" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? 'Hide details' : 'Video details'}
          </button>
          {isAdmin && (
            <>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => fileInputRef.current?.click()}
                disabled={busy}
              >
                Import metadata JSON
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,application/json"
                onChange={handleImportFile}
                style={{ display: 'none' }}
                data-testid="metadata-json-input"
                aria-label="Metadata JSON file"
              />
            </>
          )}
          {isAdmin && prepStatus === 'draft' && (
            <button type="button" className="btn-primary" onClick={handleReady} disabled={busy}>
              Mark ready to rate
            </button>
          )}
          {isAdmin && prepStatus !== 'draft' && (
            <button type="button" className="btn-secondary" onClick={handleReopen} disabled={busy}>
              Reopen for editing
            </button>
          )}
        </div>
      </div>

      {locked && !isAdmin && (
        <div className="onboarding-banner locked-banner" role="note" data-testid="locked-banner">
          <span className="onboarding-text">
            This video is <strong>{prepStatus}</strong>: holds and moves are locked and cannot be
            changed. Your own labels can still be edited{prepStatus === 'closed' ? ' by an admin only' : ''}.
          </span>
        </div>
      )}

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

      {open && (
        <div className="video-meta-form" data-testid="video-meta-form">
          {FIELDS.map((f) => (
            <label key={f.key} className="video-meta-field">
              <span className="form-label">{f.label}</span>
              {isAdmin ? (
                renderInput(f)
              ) : (
                <span className="video-meta-value">{readOnlyValue(f)}</span>
              )}
            </label>
          ))}
          {isAdmin && (
            <div className="video-meta-footer">
              <button type="button" className="btn-primary" onClick={handleSave} disabled={busy}>
                {busy ? 'Saving…' : 'Save details'}
              </button>
            </div>
          )}
          {!isAdmin && (
            <p className="cell-sub">Video details are filled in by an admin during prep.</p>
          )}
        </div>
      )}
    </div>
  );
}

export default VideoMetadataPanel;
