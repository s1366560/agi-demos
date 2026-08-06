import { useState } from 'react';
import { Badge } from '@radix-ui/themes';
import { LockClosedIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { AuthState, DesktopRuntimeConfig } from '../../types';
import { SettingsPage } from './SettingsCorePages';

export function AccountSessionSecurityPage({
  auth,
  config,
  onSignOut,
}: Readonly<{
  auth: AuthState;
  config: DesktopRuntimeConfig;
  onSignOut: () => void | Promise<void>;
}>) {
  const { locale, t } = useI18n();
  const [signingOut, setSigningOut] = useState(false);
  const session = auth.session;

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
      eyebrow={t('settings.security')}
      title={t('settings.sessionSecurity')}
      description={t('settings.securityDescription')}
      className="settings-account-page"
    >
      <section className="settings-panel settings-security-panel">
        <header>
          <LockClosedIcon />
          <span>
            <strong>{t('settings.sessionSecurity')}</strong>
            <small>{t('settings.securityDescription')}</small>
          </span>
          <Badge color={auth.status === 'signed_in' ? 'green' : 'gray'} variant="soft">
            {t(`settings.authStatus.${auth.status}`)}
          </Badge>
        </header>
        <dl className="settings-rows">
          <div>
            <dt>{t('settings.authMethod')}</dt>
            <dd>{session?.auth_method ?? t('settings.notAvailable')}</dd>
          </div>
          <div>
            <dt>{t('settings.sessionSecurity')}</dt>
            <dd>
              {session
                ? t(session.trusted_device ? 'settings.trustedDevice' : 'settings.temporarySession')
                : t('settings.notAvailable')}
            </dd>
          </div>
          <div>
            <dt>{t('settings.sessionExpires')}</dt>
            <dd>
              {session?.expires_at
                ? new Date(session.expires_at).toLocaleString(locale)
                : t('settings.notAvailable')}
            </dd>
          </div>
          <div>
            <dt>{t('runtime.connectionMode')}</dt>
            <dd>{config.mode}</dd>
          </div>
        </dl>
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
