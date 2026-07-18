import { useEffect, useRef, useState } from 'react';
import {
  ArrowRightIcon,
  CheckCircledIcon,
  ClockIcon,
  Cross2Icon,
  ExclamationTriangleIcon,
  ExternalLinkIcon,
  EyeClosedIcon,
  EyeOpenIcon,
  LockClosedIcon,
  MixerHorizontalIcon,
  ReaderIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

const WORKSPACE_SSO_PUBLIC_SESSION = Object.freeze({
  userCode: 'N7QK4X2P',
  displayCode: 'N7QK 4X2P',
  authorizationUrl: 'https://app.memstack.ai/device',
  authorizationUrlComplete: 'https://app.memstack.ai/device?user_code=N7QK4X2P',
  lifetimeSeconds: 10 * 60,
});

function formatCountdown(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

export function LoginScreen({ onLogin }) {
  const { t } = useI18n();
  const [email, setEmail] = useState('alex@northstar.ai');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [workspaceSso, setWorkspaceSso] = useState(null);
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const ssoDialogRef = useRef(null);
  const ssoOpen = workspaceSso !== null;
  const ssoExpiresAt = workspaceSso?.phase === 'waiting' ? workspaceSso.expiresAt : null;

  useEffect(() => {
    if (ssoExpiresAt === null) return undefined;

    const updateRemainingTime = () => {
      const nextRemaining = Math.max(0, Math.ceil((ssoExpiresAt - Date.now()) / 1000));
      setRemainingSeconds(nextRemaining);
      if (nextRemaining === 0) {
        setWorkspaceSso((current) => (
          current?.phase === 'waiting' ? { ...current, phase: 'expired' } : current
        ));
      }
    };

    updateRemainingTime();
    const timer = window.setInterval(updateRemainingTime, 1000);
    return () => window.clearInterval(timer);
  }, [ssoExpiresAt]);

  useEffect(() => {
    if (!ssoOpen) return undefined;

    const dialog = ssoDialogRef.current;
    const previouslyFocused = document.activeElement;
    const focusableSelector = 'button:not(:disabled), a[href], input:not(:disabled)';
    dialog?.querySelector(focusableSelector)?.focus();

    const handleDialogKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        cancelWorkspaceSso();
        return;
      }
      if (event.key !== 'Tab' || !dialog) return;
      const focusable = Array.from(dialog.querySelectorAll(focusableSelector));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleDialogKeyDown);
    return () => {
      document.removeEventListener('keydown', handleDialogKeyDown);
      if (previouslyFocused instanceof HTMLElement && previouslyFocused.isConnected) {
        previouslyFocused.focus();
      }
    };
  }, [ssoOpen]);

  function submit(event) {
    event.preventDefault();
    if (!email.includes('@') || password.length < 6) {
      setError(t('Enter a valid work email and at least 6 password characters.'));
      return;
    }
    setError('');
    setLoading(true);
    window.setTimeout(() => onLogin({ email, remember }), 650);
  }

  function continueWithSso() {
    const expiresAt = Date.now() + WORKSPACE_SSO_PUBLIC_SESSION.lifetimeSeconds * 1000;
    setError('');
    setLoading(false);
    setRemainingSeconds(WORKSPACE_SSO_PUBLIC_SESSION.lifetimeSeconds);
    setWorkspaceSso({ phase: 'waiting', expiresAt });
  }

  function cancelWorkspaceSso() {
    setWorkspaceSso(null);
    setRemainingSeconds(0);
  }

  const ssoExpired = workspaceSso?.phase === 'expired';

  return (
    <main className="login-screen">
      <section
        className="login-story"
        aria-hidden={ssoOpen || undefined}
        inert={ssoOpen || undefined}
      >
        <header className="login-brand">
          <img src="/memstack-icon.png" alt="MemStack" />
          <div>
            <strong>MemStack</strong>
            <span>{t('Agent workspace')}</span>
          </div>
        </header>
        <div className="login-story-copy">
          <span>{t('WORK THAT CONTINUES')}</span>
          <h1>{t('Your agents, projects, and decisions in one trusted workspace.')}</h1>
          <p>
            {t('Sign in once to resume tasks, review plans, switch project context, and govern every agent resource.')}
          </p>
        </div>
        <div className="login-proof-list">
          <article>
            <MixerHorizontalIcon />
            <div>
              <b>{t('One task kernel')}</b>
              <span>{t('Move between general work and code without losing context.')}</span>
            </div>
          </article>
          <article>
            <ReaderIcon />
            <div>
              <b>{t('Review before action')}</b>
              <span>{t('Plans, permissions, and outputs stay inspectable.')}</span>
            </div>
          </article>
          <article>
            <LockClosedIcon />
            <div>
              <b>{t('Tenant isolation')}</b>
              <span>{t('Projects, memory, credentials, and audit remain scoped.')}</span>
            </div>
          </article>
        </div>
        <footer>
          <LockClosedIcon /> {t('Encrypted session · SSO ready · Audit enabled')}
        </footer>
      </section>

      <section
        className="login-form-side"
        aria-hidden={ssoOpen || undefined}
        inert={ssoOpen || undefined}
      >
        <form className="login-card" onSubmit={submit}>
          <header>
            <span>{t('WELCOME BACK')}</span>
            <h2>{t('Sign in to MemStack')}</h2>
            <p>{t('Use your organization account to continue.')}</p>
          </header>
          <button
            className="login-sso"
            type="button"
            onClick={continueWithSso}
            disabled={loading}
          >
            <img src="/memstack-icon.png" alt="" />
            {t('Continue with workspace SSO')}
            <ArrowRightIcon />
          </button>
          <div className="login-divider"><span>{t('or use email')}</span></div>
          <label>
            <span>{t('Work email')}</span>
            <input
              autoFocus
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
            />
          </label>
          <label>
            <span>{t('Password')}</span>
            <div className="login-password">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                placeholder={t('Enter your password')}
              />
              <button
                type="button"
                onClick={() => setShowPassword((value) => !value)}
                aria-label={t(showPassword ? 'Hide password' : 'Show password')}
              >
                {showPassword ? <EyeClosedIcon /> : <EyeOpenIcon />}
              </button>
            </div>
          </label>
          <div className="login-options">
            <label>
              <input
                type="checkbox"
                checked={remember}
                onChange={(event) => setRemember(event.target.checked)}
              />
              <span>
                <i>{remember ? <CheckCircledIcon /> : null}</i>
                {t('Keep me signed in on this device')}
              </span>
            </label>
            <button type="button">{t('Forgot password?')}</button>
          </div>
          {error ? <div className="login-error" role="alert">{error}</div> : null}
          <button className="login-submit" type="submit" disabled={loading}>
            {t(loading ? 'Signing in…' : 'Sign in')}
            <ArrowRightIcon />
          </button>
          <p className="login-legal">
            {t('By continuing, you agree to your organization policies and MemStack terms.')}
          </p>
        </form>
        <div className="login-help">
          <span>{t('New to MemStack?')}</span>
          <button type="button">{t('Request workspace access')}</button>
        </div>
      </section>

      {workspaceSso ? (
        <div className="login-device-auth-backdrop">
          <section
            ref={ssoDialogRef}
            className={`login-device-auth-dialog ${workspaceSso.phase}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby="login-device-auth-title"
            aria-describedby="login-device-auth-description"
          >
            <button
              className="login-device-auth-close"
              type="button"
              onClick={cancelWorkspaceSso}
              aria-label={t('Cancel workspace SSO')}
            >
              <Cross2Icon />
            </button>

            <span className="login-device-auth-icon" aria-hidden="true">
              {ssoExpired ? <ExclamationTriangleIcon /> : <ExternalLinkIcon />}
            </span>

            <header>
              <span>{t('SECURE WORKSPACE SIGN-IN')}</span>
              <h2 id="login-device-auth-title">
                {t(ssoExpired ? 'This sign-in code has expired' : 'Continue in your browser')}
              </h2>
              <p id="login-device-auth-description">
                {t(ssoExpired
                  ? 'Start workspace SSO again to generate a new one-time code.'
                  : 'Approve this desktop from your organization session. This window will continue automatically.')}
              </p>
            </header>

            <div className="login-device-auth-code">
              <span>{t('One-time code')}</span>
              <strong>{WORKSPACE_SSO_PUBLIC_SESSION.displayCode}</strong>
              <small>
                <span>{t('Verification address')}</span>
                {WORKSPACE_SSO_PUBLIC_SESSION.authorizationUrl}
              </small>
            </div>

            <div
              className={`login-device-auth-status ${workspaceSso.phase}`}
              role={ssoExpired ? 'alert' : undefined}
            >
              {ssoExpired
                ? <ExclamationTriangleIcon aria-hidden="true" />
                : <ClockIcon aria-hidden="true" />}
              <span>
                <b role={ssoExpired ? undefined : 'status'}>
                  {t(ssoExpired ? 'Expired' : 'Waiting for approval…')}
                </b>
                <small>
                  {t(ssoExpired
                    ? 'The expired code can no longer authorize this desktop.'
                    : 'Code expires in {time}', {
                    time: formatCountdown(remainingSeconds),
                  })}
                </small>
              </span>
            </div>

            <div className="login-device-auth-actions">
              <button type="button" onClick={cancelWorkspaceSso}>{t('Cancel')}</button>
              {ssoExpired ? (
                <button className="primary" type="button" onClick={continueWithSso}>
                  <ReloadIcon />
                  {t('Request new code')}
                </button>
              ) : (
                <a
                  href={WORKSPACE_SSO_PUBLIC_SESSION.authorizationUrlComplete}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  <ExternalLinkIcon />
                  {t('Open browser')}
                </a>
              )}
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
