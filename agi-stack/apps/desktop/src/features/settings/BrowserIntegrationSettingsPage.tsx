import { Badge, Button } from '@radix-ui/themes';

import type { DesktopBrowserIntegrationClientV2 } from '../../plugins/desktopBrowserIntegrationAuthorityModuleV2';
import type { DesktopBrowserBridgeManagementClientV2 } from '../../plugins/desktopBrowserBridgeManagementAuthorityModuleV2';
import { useBrowserBridgeManagementV2 } from './useBrowserBridgeManagementV2';
import { useBrowserIntegrationManagementV2 } from './useBrowserIntegrationManagementV2';
import { useI18n } from '../../i18n';
import type { BrowserAuditEntry, BrowserOriginGrant, DesktopRuntimeConfig } from '../../types';
import { SettingsPage } from './SettingsCorePages';
import './BrowserIntegrationSettingsPage.css';

function formatGrantCreatedAt(value: string): string {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return value;
  return new Date(parsed).toLocaleString();
}

function grantDecisionColor(decision: BrowserOriginGrant['decision']): 'blue' | 'orange' | 'red' {
  if (decision === 'all') return 'orange';
  if (decision === 'decline') return 'red';
  return 'blue';
}

function auditOutcomeColor(outcome: BrowserAuditEntry['outcome']): 'green' | 'amber' | 'red' {
  if (outcome === 'ok') return 'green';
  if (outcome === 'consent' || outcome === 'consent_required') return 'amber';
  return 'red';
}

// Local-runtime bridge between the Chrome extension (native messaging broker)
// and the desktop sidecar. Status polling runs only while this section is
// mounted; leaving the section unmounts the page and clears the interval.
export function BrowserIntegrationSettingsPage({
  config,
  browserIntegrationClientV2,
  browserBridgeManagementClientV2,
}: {
  config?: DesktopRuntimeConfig;
  browserIntegrationClientV2: DesktopBrowserIntegrationClientV2;
  browserBridgeManagementClientV2: DesktopBrowserBridgeManagementClientV2;
}) {
  const { t } = useI18n();
  const {
    bridgeStatus,
    enabled,
    fullCdpEnabled,
    toggleBusy,
    toggleError,
    fullCdpToggleBusy,
    fullCdpToggleError,
    actionBusy,
    actionError,
    installResult,
    uninstallResult,
    loadError,
    toggleBridge,
    toggleFullCdp,
    runRegistration,
  } = useBrowserBridgeManagementV2(browserBridgeManagementClientV2, config);
  const {
    bridgeClient,
    originGrants,
    originGrantsError,
    revokingGrantId,
    revokeOriginGrant,
    capabilityGrants,
    capabilityGrantsError,
    revokingCapabilityGrantId,
    revokeCapabilityGrant,
    siteCredentials,
    siteCredentialsError,
    credentialOrigin,
    setCredentialOrigin,
    credentialUsername,
    setCredentialUsername,
    credentialPassword,
    setCredentialPassword,
    credentialSaving,
    saveSiteCredential,
    deletingCredentialId,
    deleteSiteCredential,
    auditEntries,
    auditError,
    auditOriginFilter,
    setAuditOriginFilter,
    auditLoading,
    refreshAuditEntries,
  } = useBrowserIntegrationManagementV2(browserIntegrationClientV2, config);

  const brokerConnected = bridgeStatus?.brokerConnected ?? false;

  return (
    <SettingsPage
      eyebrow={t('settings.preferences')}
      title={t('settings.browserTitle')}
      description={t('settings.browserSubtitle')}
      className="settings-preference-page settings-browser-page"
    >
      <section className="settings-panel settings-browser-toggle-panel">
        <div className="settings-preference-switch-row">
          <span>
            <strong>{t('settings.browserBridge')}</strong>
            <small>{t('settings.browserBridgeDescription')}</small>
          </span>
          <button
            type="button"
            role="switch"
            aria-label={t('settings.browserBridge')}
            aria-checked={enabled}
            className={enabled ? 'active' : ''}
            disabled={toggleBusy}
            onClick={() => void toggleBridge(!enabled)}
          >
            <i aria-hidden="true" />
            {t(enabled ? 'settings.preferenceOn' : 'settings.preferenceOff')}
          </button>
        </div>
        {toggleError || loadError ? (
          <p className="settings-browser-error" role="alert">
            {toggleError ?? loadError}
          </p>
        ) : null}
      </section>

      <section
        className="settings-panel settings-browser-status-panel"
        aria-label={t('settings.browserStatus')}
      >
        <dl className="settings-browser-connection-status">
          <div>
            <dt>{t('settings.browserBroker')}</dt>
            <dd>
              <Badge color={brokerConnected ? 'green' : 'gray'} variant="soft">
                {t(brokerConnected ? 'statusbar.connected' : 'statusbar.disconnected')}
              </Badge>
            </dd>
          </div>
          <div>
            <dt>{t('settings.browserPort')}</dt>
            <dd>{bridgeStatus ? String(bridgeStatus.port) : t('settings.notAvailable')}</dd>
          </div>
        </dl>
      </section>

      <section className="settings-panel settings-browser-registration-panel">
        <header>
          <span>
            <strong>{t('settings.browserRegistration')}</strong>
            <small>{t('settings.browserRegistrationDescription')}</small>
          </span>
        </header>
        <div className="settings-browser-actions">
          <Button
            type="button"
            variant="soft"
            disabled={actionBusy !== null}
            onClick={() => void runRegistration('install')}
          >
            {actionBusy === 'install'
              ? t('settings.browserRegistering')
              : t('settings.browserRegister')}
          </Button>
          <Button
            type="button"
            variant="soft"
            color="gray"
            disabled={actionBusy !== null}
            onClick={() => void runRegistration('uninstall')}
          >
            {actionBusy === 'uninstall'
              ? t('settings.browserUnregistering')
              : t('settings.browserUnregister')}
          </Button>
        </div>
        {actionError ? (
          <p className="settings-browser-error" role="alert">
            {actionError}
          </p>
        ) : null}
        {installResult ? (
          <div className="settings-browser-results">
            {installResult.installed.map((entry) => (
              <div className="settings-row" key={entry.browser}>
                <span>
                  <strong>{entry.browser}</strong>
                  <small>{entry.manifestPath}</small>
                </span>
                <b>{t('settings.browserRegistered')}</b>
              </div>
            ))}
            {installResult.skipped.map((browser) => (
              <div className="settings-row" key={browser}>
                <span>
                  <strong>{browser}</strong>
                </span>
                <b>{t('settings.browserSkipped')}</b>
              </div>
            ))}
          </div>
        ) : null}
        {uninstallResult ? (
          <div className="settings-browser-results">
            {uninstallResult.removed.map((browser) => (
              <div className="settings-row" key={browser}>
                <span>
                  <strong>{browser}</strong>
                </span>
                <b>{t('settings.browserRemoved')}</b>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      {bridgeClient ? (
        <section className="settings-panel settings-browser-grants-panel">
          <header>
            <span>
              <strong>{t('settings.browserOriginGrants')}</strong>
              <small>{t('settings.browserOriginGrantsDescription')}</small>
            </span>
          </header>
          {originGrantsError ? (
            <p className="settings-browser-error" role="alert">
              {originGrantsError}
            </p>
          ) : null}
          {originGrants === null && !originGrantsError ? (
            <p className="settings-browser-hint">{t('settings.browserOriginGrantsLoading')}</p>
          ) : null}
          {originGrants !== null && originGrants.length === 0 ? (
            <p className="settings-browser-hint">{t('settings.browserOriginGrantsEmpty')}</p>
          ) : null}
          {originGrants !== null && originGrants.length > 0 ? (
            <div className="settings-rows">
              {originGrants.map((grant) => (
                <div className="settings-row" key={grant.id}>
                  <span>
                    <strong>{grant.host}</strong>
                    <small>{formatGrantCreatedAt(grant.created_at)}</small>
                  </span>
                  <b className="settings-browser-grant-actions">
                    <Badge color={grantDecisionColor(grant.decision)} variant="soft">
                      {t(`settings.browserOriginDecision.${grant.decision}`)}
                    </Badge>
                    <Button
                      type="button"
                      size="1"
                      variant="soft"
                      color="red"
                      disabled={revokingGrantId !== null}
                      loading={revokingGrantId === grant.id}
                      onClick={() => void revokeOriginGrant(grant.id)}
                    >
                      {t('settings.browserOriginRevoke')}
                    </Button>
                  </b>
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {bridgeClient ? (
        <section className="settings-panel settings-browser-fullcdp-panel">
          <header>
            <span>
              <strong>{t('settings.browserFullCdp')}</strong>
              <small>{t('settings.browserFullCdpDescription')}</small>
            </span>
          </header>
          <div className="settings-preference-switch-row">
            <span>
              <strong>{t('settings.browserFullCdpToggle')}</strong>
              <small>{t('settings.browserFullCdpToggleDescription')}</small>
            </span>
            <button
              type="button"
              role="switch"
              aria-label={t('settings.browserFullCdpToggle')}
              aria-checked={fullCdpEnabled}
              className={fullCdpEnabled ? 'active' : ''}
              disabled={fullCdpToggleBusy}
              onClick={() => void toggleFullCdp(!fullCdpEnabled)}
            >
              <i aria-hidden="true" />
              {t(fullCdpEnabled ? 'settings.preferenceOn' : 'settings.preferenceOff')}
            </button>
          </div>
          <p className="settings-browser-warning">{t('settings.browserFullCdpWarning')}</p>
          {fullCdpToggleError ? (
            <p className="settings-browser-error" role="alert">
              {fullCdpToggleError}
            </p>
          ) : null}
          {capabilityGrantsError ? (
            <p className="settings-browser-error" role="alert">
              {capabilityGrantsError}
            </p>
          ) : null}
          {capabilityGrants === null && !capabilityGrantsError ? (
            <p className="settings-browser-hint">{t('settings.browserFullCdpGrantsLoading')}</p>
          ) : null}
          {capabilityGrants !== null && capabilityGrants.length === 0 ? (
            <p className="settings-browser-hint">{t('settings.browserFullCdpGrantsEmpty')}</p>
          ) : null}
          {capabilityGrants !== null && capabilityGrants.length > 0 ? (
            <div className="settings-rows">
              {capabilityGrants.map((grant) => (
                <div className="settings-row" key={grant.id}>
                  <span>
                    <strong>{grant.host}</strong>
                    <small>{formatGrantCreatedAt(grant.created_at)}</small>
                  </span>
                  <b className="settings-browser-grant-actions">
                    <Badge color={grantDecisionColor(grant.decision)} variant="soft">
                      {t(`settings.browserOriginDecision.${grant.decision}`)}
                    </Badge>
                    <Button
                      type="button"
                      size="1"
                      variant="soft"
                      color="red"
                      disabled={revokingCapabilityGrantId !== null}
                      loading={revokingCapabilityGrantId === grant.id}
                      onClick={() => void revokeCapabilityGrant(grant.id)}
                    >
                      {t('settings.browserOriginRevoke')}
                    </Button>
                  </b>
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {bridgeClient ? (
        <section className="settings-panel settings-browser-credentials-panel">
          <header>
            <span>
              <strong>{t('settings.browserCredentials')}</strong>
              <small>{t('settings.browserCredentialsDescription')}</small>
            </span>
          </header>
          <p className="settings-browser-hint">{t('settings.browserCredentialsVaultNote')}</p>
          <form
            className="settings-browser-credential-form"
            onSubmit={(event) => {
              event.preventDefault();
              void saveSiteCredential();
            }}
          >
            <label>
              <span>{t('settings.browserCredentialsOrigin')}</span>
              <input
                type="text"
                autoComplete="off"
                placeholder={t('settings.browserCredentialsOriginPlaceholder')}
                aria-label={t('settings.browserCredentialsOrigin')}
                value={credentialOrigin}
                disabled={credentialSaving}
                onChange={(event) => setCredentialOrigin(event.currentTarget.value)}
              />
            </label>
            <label>
              <span>{t('settings.browserCredentialsUsername')}</span>
              <input
                type="text"
                autoComplete="off"
                placeholder={t('settings.browserCredentialsUsernamePlaceholder')}
                aria-label={t('settings.browserCredentialsUsername')}
                value={credentialUsername}
                disabled={credentialSaving}
                onChange={(event) => setCredentialUsername(event.currentTarget.value)}
              />
            </label>
            <label>
              <span>{t('settings.browserCredentialsPassword')}</span>
              <input
                type="password"
                autoComplete="new-password"
                placeholder={t('settings.browserCredentialsPasswordPlaceholder')}
                aria-label={t('settings.browserCredentialsPassword')}
                value={credentialPassword}
                disabled={credentialSaving}
                onChange={(event) => setCredentialPassword(event.currentTarget.value)}
              />
            </label>
            <Button
              type="submit"
              variant="soft"
              disabled={
                credentialSaving ||
                !credentialOrigin.trim() ||
                !credentialUsername.trim() ||
                !credentialPassword
              }
              loading={credentialSaving}
            >
              {credentialSaving
                ? t('settings.browserCredentialsSaving')
                : t('settings.browserCredentialsSave')}
            </Button>
          </form>
          {siteCredentialsError ? (
            <p className="settings-browser-error" role="alert">
              {siteCredentialsError}
            </p>
          ) : null}
          {siteCredentials === null && !siteCredentialsError ? (
            <p className="settings-browser-hint">{t('settings.browserCredentialsLoading')}</p>
          ) : null}
          {siteCredentials !== null && siteCredentials.length === 0 ? (
            <p className="settings-browser-hint">{t('settings.browserCredentialsEmpty')}</p>
          ) : null}
          {siteCredentials !== null && siteCredentials.length > 0 ? (
            <div className="settings-rows">
              {siteCredentials.map((credential) => (
                <div className="settings-row" key={credential.id}>
                  <span>
                    <strong>{credential.origin}</strong>
                    <small>
                      {credential.username} · {formatGrantCreatedAt(credential.created_at)}
                    </small>
                  </span>
                  <b className="settings-browser-grant-actions">
                    <Button
                      type="button"
                      size="1"
                      variant="soft"
                      color="red"
                      disabled={deletingCredentialId !== null}
                      loading={deletingCredentialId === credential.id}
                      onClick={() => void deleteSiteCredential(credential.id)}
                    >
                      {t('settings.browserCredentialsDelete')}
                    </Button>
                  </b>
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {bridgeClient ? (
        <section className="settings-panel settings-browser-audit-panel">
          <header>
            <span>
              <strong>{t('settings.browserAudit')}</strong>
              <small>{t('settings.browserAuditDescription')}</small>
            </span>
          </header>
          <form
            className="settings-browser-audit-controls"
            onSubmit={(event) => {
              event.preventDefault();
              void refreshAuditEntries(auditOriginFilter);
            }}
          >
            <input
              type="text"
              autoComplete="off"
              placeholder={t('settings.browserAuditOriginFilterPlaceholder')}
              aria-label={t('settings.browserAuditOriginFilter')}
              value={auditOriginFilter}
              disabled={auditLoading}
              onChange={(event) => setAuditOriginFilter(event.currentTarget.value)}
            />
            <Button type="submit" variant="soft" disabled={auditLoading} loading={auditLoading}>
              {t('settings.browserAuditRefresh')}
            </Button>
          </form>
          {auditError ? (
            <p className="settings-browser-error" role="alert">
              {auditError}
            </p>
          ) : null}
          {auditEntries === null && !auditError ? (
            <p className="settings-browser-hint">{t('settings.browserAuditLoading')}</p>
          ) : null}
          {auditEntries !== null && auditEntries.length === 0 ? (
            <p className="settings-browser-hint">{t('settings.browserAuditEmpty')}</p>
          ) : null}
          {auditEntries !== null && auditEntries.length > 0 ? (
            <div className="settings-browser-audit-scroll">
              <table className="settings-browser-audit-table">
                <thead>
                  <tr>
                    <th scope="col">{t('settings.browserAuditColumn.time')}</th>
                    <th scope="col">{t('settings.browserAuditColumn.tool')}</th>
                    <th scope="col">{t('settings.browserAuditColumn.origin')}</th>
                    <th scope="col">{t('settings.browserAuditColumn.target')}</th>
                    <th scope="col">{t('settings.browserAuditColumn.outcome')}</th>
                    <th scope="col">{t('settings.browserAuditColumn.latency')}</th>
                  </tr>
                </thead>
                <tbody>
                  {auditEntries.map((entry) => (
                    <tr key={entry.id}>
                      <td>{formatGrantCreatedAt(entry.created_at)}</td>
                      <td>{entry.tool_name}</td>
                      <td>{entry.origin}</td>
                      <td>{entry.target_summary}</td>
                      <td>
                        <Badge color={auditOutcomeColor(entry.outcome)} variant="soft">
                          {t(`settings.browserAuditOutcome.${entry.outcome}`)}
                        </Badge>
                      </td>
                      <td>{t('settings.browserAuditLatency', { ms: entry.latency_ms })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="settings-panel settings-browser-hint-panel">
        <header>
          <span>
            <strong>{t('settings.browserExtensionSetup')}</strong>
          </span>
        </header>
        <p className="settings-browser-hint">{t('settings.browserExtensionHint')}</p>
      </section>
    </SettingsPage>
  );
}
