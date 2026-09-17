/**
 * AuthGate — the sign-up / sign-in screen.
 *
 * Shown whenever there is no Supabase session. Every /api route except
 * /api/health now requires a bearer token, so without this the app 401s on its
 * very first call and sits on a loading screen forever.
 *
 * One card, one form. Sign in and create account are the same fields, so they
 * are the same form with a text toggle rather than two tabs. Email
 * confirmation is off in the Supabase project, so a successful sign-up returns
 * a session and the auth listener in App swaps this screen for the app with no
 * interstitial in between — the confirmation notice below is the fallback for
 * the day that setting changes back.
 */
import { useState } from 'react';
import { signIn, signUp, isAuthConfigured } from '../api/auth';

function AuthGate() {
  const [mode, setMode] = useState('signin'); // 'signin' | 'signup'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const configured = isAuthConfigured();
  const signingUp = mode === 'signup';

  const toggleMode = () => {
    setMode(signingUp ? 'signin' : 'signup');
    setError(null);
    setNotice(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setNotice(null);

    if (!email.trim() || !password) {
      setError('Enter both an email address and a password.');
      return;
    }
    if (signingUp && password.length < 6) {
      setError('Choose a password of at least 6 characters.');
      return;
    }

    setBusy(true);
    try {
      if (signingUp) {
        const { needsConfirmation } = await signUp(email.trim(), password);
        if (needsConfirmation) {
          // Only reachable if email confirmation is switched back on.
          setNotice('Account created. Check your email to confirm it, then sign in.');
          setMode('signin');
          setPassword('');
        }
        // Otherwise Supabase returns a session and the auth listener in App
        // swaps this screen out on its own.
      } else {
        await signIn(email.trim(), password);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-gate">
      <div className="auth-card">
        <h1 className="auth-title">Dynalytix</h1>
        <p className="auth-subtitle">Climbing movement labeling.</p>

        {!configured && (
          <p className="auth-error" role="alert">
            Sign-in is not configured in this build — VITE_SUPABASE_URL and
            VITE_SUPABASE_ANON_KEY are missing.
          </p>
        )}

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="auth-field">
            <label className="auth-label" htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              autoFocus
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={busy || !configured}
              className="auth-input"
            />
          </div>

          <div className="auth-field">
            <label className="auth-label" htmlFor="auth-password">Password</label>
            <input
              id="auth-password"
              type="password"
              autoComplete={signingUp ? 'new-password' : 'current-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy || !configured}
              className="auth-input"
            />
          </div>

          <button
            type="submit"
            className="auth-submit"
            disabled={busy || !configured}
          >
            {busy && <span className="auth-spinner" aria-hidden="true" />}
            {busy
              ? signingUp ? 'Creating account…' : 'Signing in…'
              : signingUp ? 'Create account' : 'Sign in'}
          </button>

          {error && <p className="auth-error" role="alert">{error}</p>}
          {notice && <p className="auth-notice" role="status">{notice}</p>}
        </form>

        <p className="auth-toggle-line">
          {signingUp ? 'Already have an account? ' : 'No account yet? '}
          <button type="button" className="auth-toggle" onClick={toggleMode} disabled={busy}>
            {signingUp ? 'Sign in instead' : 'Create one'}
          </button>
        </p>
      </div>
    </div>
  );
}

export default AuthGate;
