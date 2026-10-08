import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { signIn, confirmSignIn } from 'aws-amplify/auth';
import styles from './LoginPage.module.css';

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || '/';

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [needsNewPassword, setNeedsNewPassword] = useState(false);

  async function handleLogin(e) {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const result = await signIn({ username, password });

      if (result.nextStep?.signInStep === 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED') {
        setNeedsNewPassword(true);
        setLoading(false);
        return;
      }

      if (result.isSignedIn) {
        navigate(from, { replace: true });
      }
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleNewPassword(e) {
    e.preventDefault();
    setError('');

    if (newPassword !== confirmNewPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }

    setLoading(true);
    try {
      const result = await confirmSignIn({ challengeResponse: newPassword });
      if (result.isSignedIn) {
        navigate(from, { replace: true });
      }
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setLoading(false);
    }
  }

  function friendlyError(err) {
    const code = err.name || err.code || '';
    if (code === 'NotAuthorizedException') return 'Incorrect username or password.';
    if (code === 'UserNotFoundException') return 'User not found.';
    if (code === 'UserNotConfirmedException') return 'Account not confirmed. Contact your administrator.';
    if (code === 'PasswordResetRequiredException') return 'Password reset required. Contact your administrator.';
    return err.message || 'An unexpected error occurred. Please try again.';
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.header}>
          <div className={styles.logo}>SRD</div>
          <h1 className={styles.title}>Student Risk Dashboard</h1>
          <p className={styles.subtitle}>Sign in to your account</p>
        </div>

        {!needsNewPassword ? (
          <form onSubmit={handleLogin} className={styles.form} noValidate>
            <div className={styles.field}>
              <label htmlFor="username" className={styles.label}>Username</label>
              <input
                id="username"
                type="text"
                className={styles.input}
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="username"
                required
                disabled={loading}
                placeholder="Enter your username"
              />
            </div>

            <div className={styles.field}>
              <label htmlFor="password" className={styles.label}>Password</label>
              <input
                id="password"
                type="password"
                className={styles.input}
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                disabled={loading}
                placeholder="Enter your password"
              />
            </div>

            {error && (
              <div className={styles.error} role="alert">
                {error}
              </div>
            )}

            <button type="submit" className={styles.button} disabled={loading || !username || !password}>
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleNewPassword} className={styles.form} noValidate>
            <div className={styles.newPasswordBanner}>
              You must set a new password before continuing.
            </div>

            <div className={styles.field}>
              <label htmlFor="newPassword" className={styles.label}>New Password</label>
              <input
                id="newPassword"
                type="password"
                className={styles.input}
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                autoComplete="new-password"
                required
                disabled={loading}
                placeholder="Minimum 8 characters"
              />
            </div>

            <div className={styles.field}>
              <label htmlFor="confirmNewPassword" className={styles.label}>Confirm New Password</label>
              <input
                id="confirmNewPassword"
                type="password"
                className={styles.input}
                value={confirmNewPassword}
                onChange={e => setConfirmNewPassword(e.target.value)}
                autoComplete="new-password"
                required
                disabled={loading}
                placeholder="Repeat new password"
              />
            </div>

            {error && (
              <div className={styles.error} role="alert">
                {error}
              </div>
            )}

            <button type="submit" className={styles.button} disabled={loading || !newPassword || !confirmNewPassword}>
              {loading ? 'Setting password…' : 'Set New Password'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
