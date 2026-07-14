import { useState } from 'react';
import {
  ArrowRightIcon,
  CheckCircledIcon,
  EyeClosedIcon,
  EyeOpenIcon,
  LockClosedIcon,
  MixerHorizontalIcon,
  ReaderIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

export function LoginScreen({ onLogin }) {
  const { t } = useI18n();
  const [email, setEmail] = useState('alex@northstar.ai');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

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
    setLoading(true);
    window.setTimeout(() => onLogin({ email: 'alex@northstar.ai', remember: true }), 650);
  }

  return (
    <main className="login-screen">
      <section className="login-story">
        <header className="login-brand"><img src="/memstack-icon.png" alt="MemStack" /><div><strong>MemStack</strong><span>{t('Agent workspace')}</span></div></header>
        <div className="login-story-copy">
          <span>{t('WORK THAT CONTINUES')}</span>
          <h1>{t('Your agents, projects, and decisions in one trusted workspace.')}</h1>
          <p>{t('Sign in once to resume tasks, review plans, switch project context, and govern every agent resource.')}</p>
        </div>
        <div className="login-proof-list">
          <article><MixerHorizontalIcon /><div><b>{t('One task kernel')}</b><span>{t('Move between general work and code without losing context.')}</span></div></article>
          <article><ReaderIcon /><div><b>{t('Review before action')}</b><span>{t('Plans, permissions, and outputs stay inspectable.')}</span></div></article>
          <article><LockClosedIcon /><div><b>{t('Tenant isolation')}</b><span>{t('Projects, memory, credentials, and audit remain scoped.')}</span></div></article>
        </div>
        <footer><LockClosedIcon /> {t('Encrypted session · SSO ready · Audit enabled')}</footer>
      </section>

      <section className="login-form-side">
        <form className="login-card" onSubmit={submit}>
          <header><span>{t('WELCOME BACK')}</span><h2>{t('Sign in to MemStack')}</h2><p>{t('Use your organization account to continue.')}</p></header>
          <button className="login-sso" type="button" onClick={continueWithSso} disabled={loading}><img src="/memstack-icon.png" alt="" />{t('Continue with workspace SSO')}<ArrowRightIcon /></button>
          <div className="login-divider"><span>{t('or use email')}</span></div>
          <label><span>{t('Work email')}</span><input autoFocus type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" /></label>
          <label><span>{t('Password')}</span><div className="login-password"><input type={showPassword ? 'text' : 'password'} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" placeholder={t('Enter your password')} /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={t(showPassword ? 'Hide password' : 'Show password')}>{showPassword ? <EyeClosedIcon /> : <EyeOpenIcon />}</button></div></label>
          <div className="login-options"><label><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /><span><i>{remember ? <CheckCircledIcon /> : null}</i>{t('Keep me signed in on this device')}</span></label><button type="button">{t('Forgot password?')}</button></div>
          {error ? <div className="login-error" role="alert">{error}</div> : null}
          <button className="login-submit" type="submit" disabled={loading}>{t(loading ? 'Signing in…' : 'Sign in')}<ArrowRightIcon /></button>
          <p className="login-legal">{t('By continuing, you agree to your organization policies and MemStack terms.')}</p>
        </form>
        <div className="login-help"><span>{t('New to MemStack?')}</span><button type="button">{t('Request workspace access')}</button></div>
      </section>
    </main>
  );
}
