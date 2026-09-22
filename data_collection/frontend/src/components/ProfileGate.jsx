/**
 * ProfileGate — the one-screen rater profile, collected once after the first
 * sign-in and required before anything else renders.
 *
 * `GET /api/me/profile` answered 404, so `POST /api/me/profile` is the way
 * through. Tier starts `open`; an admin promotes a rater to `validated` from
 * the Admin view, which is why there is no tier control here.
 */
import { useState } from 'react';
import { createMyProfile } from '../api/client';

function ProfileGate({ onCreated, onSignOut, email }) {
  const [displayName, setDisplayName] = useState('');
  const [yearsClimbing, setYearsClimbing] = useState('');
  const [highestGrade, setHighestGrade] = useState('');
  const [coachingCert, setCoachingCert] = useState('');
  const [researchBackground, setResearchBackground] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const name = displayName.trim();
    if (!name) {
      setError('Enter a display name.');
      return;
    }
    const years = yearsClimbing.trim() === '' ? null : Number(yearsClimbing);
    if (years !== null && (!Number.isInteger(years) || years < 0 || years > 100)) {
      setError('Years climbing must be a whole number between 0 and 100.');
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const profile = await createMyProfile({
        display_name: name,
        years_climbing: years,
        highest_grade: highestGrade.trim() || null,
        coaching_cert: coachingCert.trim() || null,
        research_background: researchBackground,
      });
      onCreated(profile);
    } catch (err) {
      setError(
        err.response?.data?.detail || err.message || 'Could not save the profile. Try again.'
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-gate">
      <div className="auth-card profile-card">
        <h1 className="auth-title">Rater profile</h1>
        <p className="auth-subtitle">
          One screen, saved once. This is how ratings are attributed and how a
          rater is validated for Paper A.
          {email && (
            <>
              {' '}
              Signed in as <strong>{email}</strong>.
            </>
          )}
        </p>

        <form onSubmit={handleSubmit} className="auth-form" data-testid="profile-form">
          <div className="auth-field">
            <label className="auth-label" htmlFor="profile-display-name">
              Display name
            </label>
            <input
              id="profile-display-name"
              className="auth-input"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value.slice(0, 120))}
              autoFocus
              autoComplete="name"
              disabled={busy}
            />
          </div>

          <div className="auth-field">
            <label className="auth-label" htmlFor="profile-years">
              Years climbing
            </label>
            <input
              id="profile-years"
              className="auth-input"
              type="number"
              min="0"
              max="100"
              step="1"
              inputMode="numeric"
              value={yearsClimbing}
              onChange={(e) => setYearsClimbing(e.target.value)}
              disabled={busy}
            />
          </div>

          <div className="auth-field">
            <label className="auth-label" htmlFor="profile-grade">
              Highest grade climbed
            </label>
            <input
              id="profile-grade"
              className="auth-input"
              placeholder="e.g. V6, 7a"
              value={highestGrade}
              onChange={(e) => setHighestGrade(e.target.value)}
              disabled={busy}
            />
          </div>

          <div className="auth-field">
            <label className="auth-label" htmlFor="profile-cert">
              Coaching certification <span className="optional-flag">(optional)</span>
            </label>
            <input
              id="profile-cert"
              className="auth-input"
              value={coachingCert}
              onChange={(e) => setCoachingCert(e.target.value)}
              disabled={busy}
            />
          </div>

          <div className="auth-field">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={researchBackground}
                onChange={(e) => setResearchBackground(e.target.checked)}
                disabled={busy}
              />
              <span>I have a research background (movement science, sports science, or similar)</span>
            </label>
          </div>

          <button type="submit" className="auth-submit" disabled={busy}>
            {busy && <span className="auth-spinner" aria-hidden="true" />}
            {busy ? 'Saving…' : 'Save profile'}
          </button>

          {error && (
            <p className="auth-error" role="alert">
              {error}
            </p>
          )}
        </form>

        {onSignOut && (
          <p className="auth-toggle-line">
            Wrong account?{' '}
            <button type="button" className="auth-toggle" onClick={onSignOut} disabled={busy}>
              Sign out
            </button>
          </p>
        )}
      </div>
    </div>
  );
}

export default ProfileGate;
