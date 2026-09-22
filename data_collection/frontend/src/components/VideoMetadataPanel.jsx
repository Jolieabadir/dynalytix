/**
 * VideoMetadataPanel — the prep-pass strip above the labeling area.
 *
 * Shows the video's dataset and prep_status. For an admin it is also the
 * metadata form (route grade, wall type, climber details, camera angle, gym,
 * notes → PUT /api/admin/videos/{id}/metadata) and the "Mark ready to rate"
 * button. Both are admin-only on the API, so a non-admin owner sees the badge
 * and the metadata read-only.
 *
 * Once a video is ready or closed its holds and moves are locked for anyone
 * but an admin. The API would answer 403; this says so before the click.
 */
import { useEffect, useState } from 'react';
import useStore from '../store/useStore';
import { adminUpdateVideoMetadata, adminMarkReady, adminReopenVideo } from '../api/client';

const FIELDS = [
  { key: 'route_grade', label: 'Route grade', placeholder: 'V4, 6b+' },
  { key: 'wall_type', label: 'Wall type', placeholder: 'board, spray wall, set boulder' },
  { key: 'climber_experience', label: 'Climber experience', placeholder: 'beginner / intermediate / advanced' },
  { key: 'climber_height_cm', label: 'Climber height (cm)', type: 'number' },
  { key: 'climber_ape_index_cm', label: 'Ape index (cm)', type: 'number' },
  { key: 'camera_angle', label: 'Camera angle', placeholder: 'side, front, 45°' },
  { key: 'gym', label: 'Gym' },
  { key: 'notes', label: 'Notes', textarea: true },
];

function fromVideo(video) {
  return Object.fromEntries(FIELDS.map((f) => [f.key, video?.[f.key] ?? '']));
}

function VideoMetadataPanel() {
  const currentVideo = useStore((s) => s.currentVideo);
  const setCurrentVideo = useStore((s) => s.setCurrentVideo);
  const profile = useStore((s) => s.profile);
  const setReadOnlyStructure = useStore((s) => s.setReadOnlyStructure);

  const isAdmin = Boolean(profile?.is_admin);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(() => fromVideo(currentVideo));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const videoId = currentVideo?.id;
  const prepStatus = currentVideo?.prep_status ?? 'draft';
  const locked = prepStatus !== 'draft';

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
    setNotice(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  if (!currentVideo) return null;

  const update = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSave = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const payload = {};
      for (const f of FIELDS) {
        const raw = form[f.key];
        if (f.type === 'number') {
          if (raw === '' || raw === null) continue; // unchanged; the API has no "clear" for ints
          const n = Number(raw);
          if (!Number.isInteger(n)) {
            setError(`${f.label} must be a whole number.`);
            setBusy(false);
            return;
          }
          payload[f.key] = n;
        } else {
          payload[f.key] = raw ?? ''; // '' clears a text field
        }
      }
      const video = await adminUpdateVideoMetadata(videoId, payload);
      setCurrentVideo({ ...currentVideo, ...video });
      setNotice('Video details saved.');
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Could not save the video details.');
    } finally {
      setBusy(false);
    }
  };

  const handleReady = async () => {
    if (!window.confirm('Mark this video ready to rate? Holds and moves lock for everyone but admins.')) return;
    setBusy(true);
    setError(null);
    try {
      const video = await adminMarkReady(videoId);
      setCurrentVideo({ ...currentVideo, ...video });
      setNotice('Marked ready to rate. Assign raters from the Admin tab.');
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Could not mark the video ready.');
    } finally {
      setBusy(false);
    }
  };

  const handleReopen = async () => {
    setBusy(true);
    setError(null);
    try {
      const video = await adminReopenVideo(videoId);
      setCurrentVideo({ ...currentVideo, ...video });
      setNotice('Reopened: holds and moves can be edited again.');
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Could not reopen the video.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="video-meta-panel" data-testid="video-meta-panel">
      <div className="video-meta-header">
        <span className="video-meta-title">
          <strong>{currentVideo.filename}</strong>
          {' · '}dataset {currentVideo.dataset ?? 'B'}
          {' · '}
          <span className={`status-pill prep-${prepStatus}`} data-testid="prep-status">
            {prepStatus}
          </span>
        </span>
        <div className="video-meta-actions">
          <button type="button" className="btn-secondary" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? 'Hide details' : 'Video details'}
          </button>
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
                f.textarea ? (
                  <textarea
                    className="description-textarea"
                    rows="2"
                    value={form[f.key] ?? ''}
                    onChange={(e) => update(f.key, e.target.value)}
                    disabled={busy}
                  />
                ) : (
                  <input
                    className="auth-input"
                    type={f.type || 'text'}
                    placeholder={f.placeholder}
                    value={form[f.key] ?? ''}
                    onChange={(e) => update(f.key, e.target.value)}
                    disabled={busy}
                  />
                )
              ) : (
                <span className="video-meta-value">
                  {currentVideo[f.key] === null || currentVideo[f.key] === undefined || currentVideo[f.key] === ''
                    ? '—'
                    : String(currentVideo[f.key])}
                </span>
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
