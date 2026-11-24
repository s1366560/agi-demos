import { useState, type ReactNode } from 'react';
import { Badge } from '@radix-ui/themes';
import { LockClosedIcon, PersonIcon } from '@radix-ui/react-icons';
import { useI18n } from '../../i18n';
import type { AuthState, DesktopRuntimeConfig, TenantSummary } from '../../types';
import './SettingsCorePages.css';

export function SettingsPage({
  title,
  description,
  action,
  children,
  className = '',
}: {
  eyebrow?: string;
  title: string;
  description: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`settings-page ${className}`.trim()}>
      <header className="settings-page-heading">
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {action}
      </header>
      {children}
    </div>
  );
}

export function AccountSettingsPage({
  auth,
  tenant,
  config,
  onSignOut,
}: {
  auth: Pick<AuthState, 'status' | 'session' | 'user'>;
  tenant: TenantSummary | null;
  config: DesktopRuntimeConfig;
  onSignOut: () => void | Promise<void>;
}) {
  const { locale, t } = useI18n();
  const [signingOut, setSigningOut] = useState(false);
  const session = auth.session;
  const isLocal = config.mode === 'local';
  const user = auth.user;

  const signOut = async () => {
    setSigningOut(true);
    try {
      await onSignOut();
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <SettingsPage
      eyebrow={t('settings.accountEyebrow')}
      title={t('settings.accountTitle')}
      description={t('settings.accountSubtitle')}
      className="settings-account-page"
    >
      <section className="settings-panel settings-account-profile">
        <div className="settings-account-hero">
          <span className="settings-profile-avatar">
            <PersonIcon />
          </span>
          <div>
            <strong>{user?.name || user?.email || t('settings.signedOut')}</strong>
            <small>{user?.email || config.apiBaseUrl}</small>
            <Badge color={auth.status === 'signed_in' ? 'green' : 'gray'} variant="soft">
              {t(`settings.authStatus.${auth.status}`)}
            </Badge>
          </div>
        </div>
        <div className="settings-rows">
          <SettingsRow
            label={t('settings.authMethod')}
            value={session ? authMethodLabel(session.auth_method, t) : t('settings.notAvailable')}
          />
          <SettingsRow
            label={t('settings.currentOrganization')}
            value={tenant?.name || t('settings.notAvailable')}
            description={tenant?.plan || tenant?.slug || undefined}
          />
          {!isLocal ? (
            <SettingsRow
              label={t('settings.sessionSecurity')}
              value={
                session
                  ? t(
                      session.trusted_device
                        ? 'settings.trustedDevice'
                        : 'settings.temporarySession',
                    )
                  : t('settings.notAvailable')
              }
            />
          ) : null}
        </div>
      </section>

      <section className="settings-panel settings-security-panel">
        <header>
          <LockClosedIcon />
          <span>
            <strong>{t('settings.security')}</strong>
            <small>{t('settings.securityDescription')}</small>
          </span>
        </header>
        <div className="settings-rows">
          {!isLocal ? (
            <SettingsRow
              label={t('settings.sessionExpires')}
              value={
                session?.expires_at
                  ? new Date(session.expires_at).toLocaleString(locale)
                  : t('settings.notAvailable')
              }
            />
          ) : null}
          <SettingsRow
            label={t('settings.accountCreated')}
            value={
              user?.created_at
                ? new Date(user.created_at).toLocaleDateString(locale)
                : t('settings.notAvailable')
            }
          />
          <SettingsRow
            label={t('settings.workspaceRoles')}
            value={user?.roles.length ? user.roles.join(', ') : t('settings.notAvailable')}
          />
        </div>
      </section>

      {auth.status === 'signed_in' ? (
        <button
          className="settings-signout"
          type="button"
          disabled={signingOut}
          onClick={() => void signOut()}
        >
          {signingOut ? t('settings.signingOut') : t('settings.signOutOfMemStack')}
        </button>
      ) : null}
    </SettingsPage>
  );
}

export function SettingsRow({
  label,
  value,
  description,
}: {
  label: string;
  value: string;
  description?: string;
}) {
  return (
    <div className="settings-row">
      <span>
        <strong>{label}</strong>
        {description ? <small>{description}</small> : null}
      </span>
      <b>{value}</b>
    </div>
  );
}

function authMethodLabel(method: string, t: (key: string) => string): string {
  const keyByMethod: Record<string, string> = {
    password: 'settings.authMethod.password',
    workspace_sso: 'settings.authMethod.workspaceSso',
    api_key: 'settings.authMethod.apiKey',
    local: 'settings.authMethod.local',
  };
  const key = keyByMethod[method];
  return key ? t(key) : method;
}
