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

import { useI18n } from '../../i18n';
import type { AuthState, RuntimeMode } from '../../types';
import { resolveWorkspaceSsoAction, validateLoginCredentials } from './loginScreenModel';
import './LoginScreen.css';

type LoginScreenProps = {
  auth: AuthState;
  mode: RuntimeMode;
  localReady: boolean;
  email: string;
  password: string;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onEmailLogin: (trustedDevice: boolean) => void;
  onLocalSession: (trustedDevice: boolean) => void;
};

export function LoginScreen({
  auth,
  mode,
  localReady,
  email,
  password,
  onEmailChange,
  onPasswordChange,
  onEmailLogin,
  onLocalSession,
}: LoginScreenProps) {
  const { t } = useI18n();
  const [showPassword, setShowPassword] = useState(false);
  const [trustedDevice, setTrustedDevice] = useState(true);
  const [interactionError, setInteractionError] = useState<string | null>(null);
  const busy = auth.status === 'signing_in';

  const continueWithWorkspaceSso = () => {
    setInteractionError(null);
    const action = resolveWorkspaceSsoAction(mode, localReady);
    if (action.kind === 'local_session') {
      onLocalSession(action.trustedDevice);
      return;
    }
    setInteractionError(t('login.workspaceSsoUnavailable'));
  };

  const visibleError = interactionError ?? auth.error;

  return (
    <main className="desktop-login-screen">
      <section className="desktop-login-story">
        <header className="desktop-login-brand">
          <img src="/icon-192.png" alt="MemStack" />
          <div>
            <strong>MemStack</strong>
            <span>{t('login.agentWorkspace')}</span>
          </div>
        </header>
        <div className="desktop-login-story-copy">
          <span>{t('login.eyebrow')}</span>
          <h1>{t('login.headline')}</h1>
          <p>{t('login.description')}</p>
        </div>
        <div className="desktop-login-proof-list">
          <article>
            <MixerHorizontalIcon />
            <div>
              <b>{t('login.kernelTitle')}</b>
              <span>{t('login.kernelDescription')}</span>
            </div>
          </article>
          <article>
            <ReaderIcon />
            <div>
              <b>{t('login.reviewTitle')}</b>
              <span>{t('login.reviewDescription')}</span>
            </div>
          </article>
          <article>
            <LockClosedIcon />
            <div>
              <b>{t('login.isolationTitle')}</b>
              <span>{t('login.isolationDescription')}</span>
            </div>
          </article>
        </div>
        <footer>
          <LockClosedIcon /> {t('login.securityFooter')}
        </footer>
      </section>

      <section className="desktop-login-form-side">
        <form
          className="desktop-login-card"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (validateLoginCredentials(email, password)) {
              setInteractionError(t('login.invalidCredentials'));
              return;
            }
            setInteractionError(null);
            onEmailLogin(trustedDevice);
          }}
        >
          <header>
            <span>{t('login.welcome')}</span>
            <h2>{t('login.signInTitle')}</h2>
            <p>{t('login.organizationDescription')}</p>
          </header>

          <button
            className="desktop-login-sso"
            type="button"
            onClick={continueWithWorkspaceSso}
            disabled={busy}
          >
            <img src="/icon-192.png" alt="" />
            {t('login.workspaceSso')}
            <ArrowRightIcon />
          </button>

          <div className="desktop-login-divider">
            <span>{t('login.emailDivider')}</span>
          </div>

          <label>
            <span>{t('login.workEmail')}</span>
            <input
              autoFocus
              required
              type="email"
              value={email}
              onChange={(event) => {
                setInteractionError(null);
                onEmailChange(event.target.value);
              }}
              autoComplete="username"
            />
          </label>
          <label>
            <span>{t('login.password')}</span>
            <div className="desktop-login-password">
              <input
                required
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(event) => {
                  setInteractionError(null);
                  onPasswordChange(event.target.value);
                }}
                autoComplete="current-password"
                placeholder={t('login.passwordPlaceholder')}
              />
              <button
                type="button"
                onClick={() => setShowPassword((value) => !value)}
                aria-label={t(showPassword ? 'login.hidePassword' : 'login.showPassword')}
              >
                {showPassword ? <EyeClosedIcon /> : <EyeOpenIcon />}
              </button>
            </div>
          </label>

          <div className="desktop-login-options">
            <label>
              <input
                type="checkbox"
                checked={trustedDevice}
                onChange={(event) => setTrustedDevice(event.target.checked)}
              />
              <span>
                <i>{trustedDevice ? <CheckCircledIcon /> : null}</i>
                {t('login.keepSignedIn')}
              </span>
            </label>
            <button type="button">{t('login.forgotPassword')}</button>
          </div>

          {visibleError ? (
            <div className="desktop-login-error" role="alert">
              {visibleError}
            </div>
          ) : null}

          <button className="desktop-login-submit" type="submit" disabled={busy}>
            {busy ? t('login.signingIn') : t('login.signIn')}
            <ArrowRightIcon />
          </button>
          <p className="desktop-login-legal">{t('login.legal')}</p>
        </form>
        <div className="desktop-login-help">
          <span>{t('login.newToMemStack')}</span>
          <button type="button">{t('login.requestWorkspaceAccess')}</button>
        </div>
      </section>
    </main>
  );
}
