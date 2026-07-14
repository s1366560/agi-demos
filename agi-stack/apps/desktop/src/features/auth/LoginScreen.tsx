import { useState } from 'react';
import { Button } from '@radix-ui/themes';
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
import './LoginScreen.css';

type LoginScreenProps = {
  auth: AuthState;
  mode: RuntimeMode;
  localReady: boolean;
  email: string;
  password: string;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onEmailLogin: () => void;
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
  const [trustedDevice, setTrustedDevice] = useState(false);
  const busy = auth.status === 'signing_in';
  const localDesktop = mode === 'local' && localReady;

  return (
    <main className="desktop-login-screen">
      <section className="desktop-login-story">
        <header className="desktop-login-brand">
          <span className="desktop-login-mark" aria-hidden>
            M
          </span>
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
          onSubmit={(event) => {
            event.preventDefault();
            if (localDesktop) {
              onLocalSession(trustedDevice);
            } else {
              onEmailLogin();
            }
          }}
        >
          <header>
            <span>{t('login.welcome')}</span>
            <h2>{t('login.signInTitle')}</h2>
            <p>{
              localDesktop
                ? t('login.localDescription')
                : t('login.organizationDescription')
            }</p>
          </header>

          {localDesktop ? (
            <button className="desktop-login-sso" type="submit" disabled={busy}>
              <span className="desktop-login-sso-mark" aria-hidden>
                M
              </span>
              {t('login.continueLocal')}
              <ArrowRightIcon />
            </button>
          ) : (
            <>
              <label>
                <span>{t('login.workEmail')}</span>
                <input
                  autoFocus
                  type="email"
                  value={email}
                  onChange={(event) => onEmailChange(event.target.value)}
                  autoComplete="username"
                />
              </label>
              <label>
                <span>{t('login.password')}</span>
                <div className="desktop-login-password">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(event) => onPasswordChange(event.target.value)}
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
            </>
          )}

          {localDesktop ? (
            <label className="desktop-login-trusted">
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
          ) : null}

          {auth.error ? (
            <div className="desktop-login-error" role="alert">
              {auth.error}
            </div>
          ) : null}

          {!localDesktop ? (
            <Button className="desktop-login-submit" type="submit" loading={busy}>
              {busy ? t('login.signingIn') : t('login.signIn')}
              <ArrowRightIcon />
            </Button>
          ) : null}
          <p className="desktop-login-legal">{t('login.legal')}</p>
        </form>
      </section>
    </main>
  );
}
