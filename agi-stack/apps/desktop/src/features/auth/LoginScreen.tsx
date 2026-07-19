import { useEffect, useState } from 'react';
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

import { useI18n } from '../../i18n';
import type { AuthState, RuntimeMode } from '../../types';
import { useModalDialog } from '../settings/useModalDialog';
import {
  resolveWorkspaceContinueLabelKey,
  resolveWorkspaceSsoAction,
  validateLoginCredentials,
} from './loginScreenModel';
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
  onWorkspaceSso: (trustedDevice: boolean) => void;
  workspaceSso: WorkspaceSsoPresentation | null;
  onOpenWorkspaceSso: () => void;
  onCancelWorkspaceSso: () => void;
};

export type WorkspaceSsoPresentation = {
  userCode: string;
  authorizationUrl: string;
  expiresAt: number;
  openError: string | null;
};

function formatDeviceUserCode(userCode: string): string {
  return userCode.length === 8 ? `${userCode.slice(0, 4)} ${userCode.slice(4)}` : userCode;
}

function formatCountdown(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function secondsUntil(expiresAt: number | null): number {
  return expiresAt === null ? 0 : Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
}

function verificationAddress(authorizationUrl: string): string {
  try {
    const url = new URL(authorizationUrl);
    url.search = '';
    return url.toString().replace(/\/$/u, '');
  } catch {
    return authorizationUrl;
  }
}

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
  onWorkspaceSso,
  workspaceSso,
  onOpenWorkspaceSso,
  onCancelWorkspaceSso,
}: LoginScreenProps) {
  const { t } = useI18n();
  const [showPassword, setShowPassword] = useState(false);
  const [trustedDevice, setTrustedDevice] = useState(true);
  const [interactionError, setInteractionError] = useState<string | null>(null);
  const busy = auth.status === 'signing_in';
  const ssoExpiresAt = workspaceSso?.expiresAt ?? null;
  const [countdown, setCountdown] = useState(() => ({
    expiresAt: ssoExpiresAt,
    remainingSeconds: secondsUntil(ssoExpiresAt),
  }));
  const remainingSeconds =
    countdown.expiresAt === ssoExpiresAt
      ? countdown.remainingSeconds
      : secondsUntil(ssoExpiresAt);
  const ssoExpired = workspaceSso !== null && remainingSeconds === 0;
  const deviceDialogRef = useModalDialog({
    active: workspaceSso !== null,
    onClose: onCancelWorkspaceSso,
  });

  useEffect(() => {
    if (ssoExpiresAt === null) {
      setCountdown({ expiresAt: null, remainingSeconds: 0 });
      return undefined;
    }
    const updateRemainingTime = () => {
      setCountdown({
        expiresAt: ssoExpiresAt,
        remainingSeconds: secondsUntil(ssoExpiresAt),
      });
    };
    updateRemainingTime();
    const timer = window.setInterval(updateRemainingTime, 1000);
    return () => window.clearInterval(timer);
  }, [ssoExpiresAt]);

  const continueWithWorkspace = () => {
    setInteractionError(null);
    const action = resolveWorkspaceSsoAction(mode, localReady, trustedDevice);
    if (action.kind === 'local_session') {
      onLocalSession(action.trustedDevice);
      return;
    }
    if (action.kind === 'workspace_sso') {
      onWorkspaceSso(trustedDevice);
      return;
    }
    setInteractionError(t('login.localWorkspaceUnavailable'));
  };

  const visibleError = interactionError ?? auth.error;

  return (
    <main className="desktop-login-screen">
      <section
        className="desktop-login-story"
        inert={workspaceSso ? true : undefined}
        aria-hidden={workspaceSso ? true : undefined}
      >
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

      <section
        className="desktop-login-form-side"
        inert={workspaceSso ? true : undefined}
        aria-hidden={workspaceSso ? true : undefined}
      >
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
            onClick={continueWithWorkspace}
            disabled={busy}
          >
            <img src="/icon-192.png" alt="" />
            {t(resolveWorkspaceContinueLabelKey(mode))}
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

      {workspaceSso ? (
        <div className="desktop-device-auth-backdrop">
          <section
            ref={deviceDialogRef}
            className={`desktop-device-auth-dialog ${ssoExpired ? 'expired' : 'waiting'}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby="desktop-device-auth-title"
            aria-describedby="desktop-device-auth-description"
            tabIndex={-1}
          >
            <button
              className="desktop-device-auth-close"
              type="button"
              onClick={onCancelWorkspaceSso}
              aria-label={t('login.deviceCancel')}
            >
              <Cross2Icon />
            </button>
            <div className="desktop-device-auth-icon">
              {ssoExpired ? <ExclamationTriangleIcon /> : <ExternalLinkIcon />}
            </div>
            <header>
              <span>{t('login.deviceEyebrow')}</span>
              <h2 id="desktop-device-auth-title">
                {t(ssoExpired ? 'login.deviceExpiredTitle' : 'login.deviceTitle')}
              </h2>
              <p id="desktop-device-auth-description">
                {t(ssoExpired ? 'login.deviceExpiredDescription' : 'login.deviceDescription')}
              </p>
            </header>
            <div className="desktop-device-auth-code">
              <span>{t('login.deviceCode')}</span>
              <strong>{formatDeviceUserCode(workspaceSso.userCode)}</strong>
              <small>
                <span>{t('login.deviceVerificationAddress')}</span>
                {verificationAddress(workspaceSso.authorizationUrl)}
              </small>
            </div>
            <div
              className={`desktop-device-auth-status ${ssoExpired ? 'expired' : 'waiting'}`}
              role={ssoExpired ? 'alert' : undefined}
            >
              {ssoExpired ? (
                <ExclamationTriangleIcon aria-hidden="true" />
              ) : (
                <ClockIcon aria-hidden="true" />
              )}
              <span>
                <b role={ssoExpired ? undefined : 'status'}>
                  {t(ssoExpired ? 'login.deviceExpiredStatus' : 'login.deviceWaiting')}
                </b>
                <small>
                  {t(ssoExpired ? 'login.deviceExpiredDetail' : 'login.deviceExpiresCountdown', {
                    time: formatCountdown(remainingSeconds),
                  })}
                </small>
              </span>
            </div>
            {workspaceSso.openError ? (
              <div className="desktop-device-auth-error" role="alert">
                {workspaceSso.openError}
              </div>
            ) : null}
            <div className="desktop-device-auth-actions">
              <button type="button" onClick={onCancelWorkspaceSso}>
                {t('login.deviceCancel')}
              </button>
              {ssoExpired ? (
                <button
                  className="primary"
                  type="button"
                  onClick={() => onWorkspaceSso(trustedDevice)}
                >
                  <ReloadIcon />
                  {t('login.deviceRequestNewCode')}
                </button>
              ) : (
                <button className="primary" type="button" onClick={onOpenWorkspaceSso}>
                  <ExternalLinkIcon />
                  {t('login.deviceOpenBrowser')}
                </button>
              )}
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
