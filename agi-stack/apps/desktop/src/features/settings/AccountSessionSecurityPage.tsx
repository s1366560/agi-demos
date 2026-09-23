import { useState } from 'react';
import { Button } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type { AuthState, DesktopRuntimeConfig } from '../../types';

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
  const [signOutFailed, setSignOutFailed] = useState(false);
  const session = auth.session;
  const isLocal = config.mode === 'local';
  const signOut = async () => {
    setSigningOut(true);
    setSignOutFailed(false);
    try {
      await onSignOut();
    } catch {
      setSignOutFailed(true);
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <section className="settings-account-security" aria-label={t('settings.sessionSecurity')}>
      <h2>{t('settings.sessionSecurity')}</h2>
      <dl className="settings-security-facts">
        <div>
          <dt>{t('runtime.connectionMode')}</dt>
          <dd>{t(`runtime.mode.${config.mode}`)}</dd>
        </div>
        <div>
          <dt>{t('settings.authMethod')}</dt>
          <dd>
            {session ? t(authMethodMessageKey(session.auth_method)) : t('settings.notAvailable')}
          </dd>
        </div>
        {!isLocal && session ? (
          <>
            <div>
              <dt>{t('settings.sessionSecurity')}</dt>
              <dd>
                {t(session.trusted_device ? 'settings.trustedDevice' : 'settings.temporarySession')}
              </dd>
            </div>
            <div>
              <dt>{t('settings.sessionExpires')}</dt>
              <dd>
                {session.expires_at
                  ? new Date(session.expires_at).toLocaleString(locale)
                  : t('settings.notAvailable')}
              </dd>
            </div>
          </>
        ) : null}
      </dl>
      {signOutFailed ? (
        <p className="settings-inline-error" role="alert">
          {t('desktopProductionRouter.reason.authorityUnavailable')}
        </p>
      ) : null}
      {auth.status === 'signed_in' ? (
        <Button variant="soft" color="gray" loading={signingOut} onClick={() => void signOut()}>
          {signingOut ? t('settings.signingOut') : t('settings.signOutOfMemStack')}
        </Button>
      ) : null}
    </section>
  );
}

function authMethodMessageKey(method: string): string {
  const keys: Record<string, string> = {
    password: 'settings.authMethod.password',
    workspace_sso: 'settings.authMethod.workspaceSso',
    api_key: 'settings.authMethod.apiKey',
    local: 'settings.authMethod.local',
  };
  return keys[method] ?? 'settings.notAvailable';
}
