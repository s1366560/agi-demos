import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, Button } from '@radix-ui/themes';
import {
  ActivityLogIcon,
  ComponentInstanceIcon,
  GlobeIcon,
  IdCardIcon,
  Link2Icon,
  LockClosedIcon,
} from '@radix-ui/react-icons';

import { DesktopApiClient } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  BrowserAuditEntry,
  BrowserBridgeInstallResult,
  BrowserBridgeStatus,
  BrowserBridgeUninstallResult,
  BrowserCapabilityGrant,
  BrowserOriginGrant,
  BrowserSiteCredentialMeta,
  DesktopRuntimeConfig,
  LocalRuntimeStatus,
} from '../../types';
import { SettingsPage } from './SettingsCorePages';
import './BrowserIntegrationSettingsPage.css';

const BROWSER_BRIDGE_STATUS_POLL_MS = 5_000;
const BROWSER_AUDIT_PAGE_LIMIT = 200;

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

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
  if (outcome === 'consent') return 'amber';
  return 'red';
}

// Local-runtime bridge between the Chrome extension (native messaging broker)
// and the desktop sidecar. Status polling runs only while this section is
// mounted; leaving the section unmounts the page and clears the interval.
export function BrowserIntegrationSettingsPage({ config }: { config?: DesktopRuntimeConfig }) {
  const { t } = useI18n();
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  const bridgeClient = useMemo(
    () => (config?.mode === 'local' ? new DesktopApiClient(config) : null),
    [config],
  );
  const [runtimeStatus, setRuntimeStatus] = useState<LocalRuntimeStatus | null>(null);
  const [bridgeStatus, setBridgeStatus] = useState<BrowserBridgeStatus | null>(null);
  const [optimisticEnabled, setOptimisticEnabled] = useState<boolean | null>(null);
  const [toggleBusy, setToggleBusy] = useState(false);
  const [toggleError, setToggleError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<'install' | 'uninstall' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [installResult, setInstallResult] = useState<BrowserBridgeInstallResult | null>(null);
  const [uninstallResult, setUninstallResult] = useState<BrowserBridgeUninstallResult | null>(null);
  const [originGrants, setOriginGrants] = useState<BrowserOriginGrant[] | null>(null);
  const [originGrantsError, setOriginGrantsError] = useState<string | null>(null);
  const [revokingGrantId, setRevokingGrantId] = useState<string | null>(null);
  const [optimisticFullCdpEnabled, setOptimisticFullCdpEnabled] = useState<boolean | null>(null);
  const [fullCdpToggleBusy, setFullCdpToggleBusy] = useState(false);
  const [fullCdpToggleError, setFullCdpToggleError] = useState<string | null>(null);
  const [capabilityGrants, setCapabilityGrants] = useState<BrowserCapabilityGrant[] | null>(null);
  const [capabilityGrantsError, setCapabilityGrantsError] = useState<string | null>(null);
  const [revokingCapabilityGrantId, setRevokingCapabilityGrantId] = useState<string | null>(null);
  const [siteCredentials, setSiteCredentials] = useState<BrowserSiteCredentialMeta[] | null>(null);
  const [siteCredentialsError, setSiteCredentialsError] = useState<string | null>(null);
  const [credentialOrigin, setCredentialOrigin] = useState('');
  const [credentialUsername, setCredentialUsername] = useState('');
  const [credentialPassword, setCredentialPassword] = useState('');
  const [credentialSaving, setCredentialSaving] = useState(false);
  const [deletingCredentialId, setDeletingCredentialId] = useState<string | null>(null);
  const [auditEntries, setAuditEntries] = useState<BrowserAuditEntry[] | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditOriginFilter, setAuditOriginFilter] = useState('');
  const [auditLoading, setAuditLoading] = useState(false);

  const refreshOriginGrants = useCallback(async () => {
    if (!bridgeClient) return;
    try {
      const grants = await bridgeClient.listBrowserOriginGrants();
      setOriginGrants(grants);
      setOriginGrantsError(null);
    } catch (error) {
      setOriginGrantsError(formatError(error));
    }
  }, [bridgeClient]);

  useEffect(() => {
    setOriginGrants(null);
    setOriginGrantsError(null);
    void refreshOriginGrants();
  }, [refreshOriginGrants]);

  const revokeOriginGrant = async (grantId: string) => {
    if (!bridgeClient || revokingGrantId) return;
    setRevokingGrantId(grantId);
    setOriginGrantsError(null);
    try {
      await bridgeClient.revokeBrowserOriginGrant(grantId);
      await refreshOriginGrants();
    } catch (error) {
      setOriginGrantsError(formatError(error));
    } finally {
      setRevokingGrantId(null);
    }
  };

  const refreshCapabilityGrants = useCallback(async () => {
    if (!bridgeClient) return;
    try {
      const grants = await bridgeClient.listBrowserCapabilityGrants();
      setCapabilityGrants(grants);
      setCapabilityGrantsError(null);
    } catch (error) {
      setCapabilityGrantsError(formatError(error));
    }
  }, [bridgeClient]);

  useEffect(() => {
    setCapabilityGrants(null);
    setCapabilityGrantsError(null);
    void refreshCapabilityGrants();
  }, [refreshCapabilityGrants]);

  const revokeCapabilityGrant = async (grantId: string) => {
    if (!bridgeClient || revokingCapabilityGrantId) return;
    setRevokingCapabilityGrantId(grantId);
    setCapabilityGrantsError(null);
    try {
      await bridgeClient.revokeBrowserCapabilityGrant(grantId);
      await refreshCapabilityGrants();
    } catch (error) {
      setCapabilityGrantsError(formatError(error));
    } finally {
      setRevokingCapabilityGrantId(null);
    }
  };

  const refreshSiteCredentials = useCallback(async () => {
    if (!bridgeClient) return;
    try {
      const credentials = await bridgeClient.listBrowserSiteCredentials();
      setSiteCredentials(credentials);
      setSiteCredentialsError(null);
    } catch (error) {
      setSiteCredentialsError(formatError(error));
    }
  }, [bridgeClient]);

  useEffect(() => {
    setSiteCredentials(null);
    setSiteCredentialsError(null);
    void refreshSiteCredentials();
  }, [refreshSiteCredentials]);

  const saveSiteCredential = async () => {
    if (!bridgeClient || credentialSaving) return;
    setCredentialSaving(true);
    setSiteCredentialsError(null);
    try {
      await bridgeClient.upsertBrowserSiteCredential({
        origin: credentialOrigin,
        username: credentialUsername,
        password: credentialPassword,
      });
      setCredentialOrigin('');
      setCredentialUsername('');
      setCredentialPassword('');
      await refreshSiteCredentials();
    } catch (error) {
      setSiteCredentialsError(formatError(error));
    } finally {
      setCredentialSaving(false);
    }
  };

  const deleteSiteCredential = async (credentialId: string) => {
    if (!bridgeClient || deletingCredentialId) return;
    setDeletingCredentialId(credentialId);
    setSiteCredentialsError(null);
    try {
      await bridgeClient.deleteBrowserSiteCredential(credentialId);
      await refreshSiteCredentials();
    } catch (error) {
      setSiteCredentialsError(formatError(error));
    } finally {
      setDeletingCredentialId(null);
    }
  };

  const refreshAuditEntries = useCallback(
    async (origin?: string) => {
      if (!bridgeClient) return;
      setAuditLoading(true);
      try {
        const entries = await bridgeClient.listBrowserAuditEntries({
          limit: BROWSER_AUDIT_PAGE_LIMIT,
          origin,
        });
        setAuditEntries(entries);
        setAuditError(null);
      } catch (error) {
        setAuditError(formatError(error));
      } finally {
        setAuditLoading(false);
      }
    },
    [bridgeClient],
  );

  useEffect(() => {
    setAuditEntries(null);
    setAuditError(null);
    void refreshAuditEntries();
  }, [refreshAuditEntries]);

  const refreshBridgeStatus = useCallback(async () => {
    if (!invoke) return;
    try {
      const status = await invoke<BrowserBridgeStatus>('browser_bridge_status');
      setBridgeStatus(status);
    } catch {
      setBridgeStatus(null);
    }
  }, [invoke]);

  useEffect(() => {
    if (!invoke) return;
    let cancelled = false;
    invoke<LocalRuntimeStatus>('local_runtime_status')
      .then((status) => {
        if (!cancelled) setRuntimeStatus(status);
      })
      .catch(() => {
        if (!cancelled) setRuntimeStatus(null);
      });
    void refreshBridgeStatus();
    const interval = window.setInterval(() => {
      void refreshBridgeStatus();
    }, BROWSER_BRIDGE_STATUS_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [invoke, refreshBridgeStatus]);

  const configuredEnabled = runtimeStatus?.config.browser_bridge?.enabled;
  const enabled = optimisticEnabled ?? configuredEnabled ?? bridgeStatus?.enabled ?? false;

  const configuredFullCdpEnabled = runtimeStatus?.config.browser_bridge?.full_cdp_access_enabled;
  const fullCdpEnabled = optimisticFullCdpEnabled ?? configuredFullCdpEnabled ?? false;

  const toggleBridge = async (next: boolean) => {
    if (!invoke || toggleBusy) return;
    setOptimisticEnabled(next);
    setToggleError(null);
    setToggleBusy(true);
    try {
      const current = await invoke<LocalRuntimeStatus>('local_runtime_status');
      const config = {
        ...current.config,
        browser_bridge: { ...current.config?.browser_bridge, enabled: next },
      };
      const updated = await invoke<LocalRuntimeStatus>('local_runtime_configure', { config });
      setRuntimeStatus(updated);
      setOptimisticEnabled(null);
      void refreshBridgeStatus();
    } catch (error) {
      setOptimisticEnabled(null);
      setToggleError(formatError(error));
    } finally {
      setToggleBusy(false);
    }
  };

  const toggleFullCdp = async (next: boolean) => {
    if (!invoke || fullCdpToggleBusy) return;
    setOptimisticFullCdpEnabled(next);
    setFullCdpToggleError(null);
    setFullCdpToggleBusy(true);
    try {
      const current = await invoke<LocalRuntimeStatus>('local_runtime_status');
      const config = {
        ...current.config,
        browser_bridge: {
          ...current.config?.browser_bridge,
          full_cdp_access_enabled: next,
        },
      };
      const updated = await invoke<LocalRuntimeStatus>('local_runtime_configure', { config });
      setRuntimeStatus(updated);
      setOptimisticFullCdpEnabled(null);
    } catch (error) {
      setOptimisticFullCdpEnabled(null);
      setFullCdpToggleError(formatError(error));
    } finally {
      setFullCdpToggleBusy(false);
    }
  };

  const runRegistration = async (action: 'install' | 'uninstall') => {    if (!invoke || actionBusy) return;
    setActionBusy(action);
    setActionError(null);
    try {
      if (action === 'install') {
        setInstallResult(await invoke<BrowserBridgeInstallResult>('browser_bridge_install'));
        setUninstallResult(null);
      } else {
        setUninstallResult(
          await invoke<BrowserBridgeUninstallResult>('browser_bridge_uninstall'),
        );
        setInstallResult(null);
      }
      void refreshBridgeStatus();
    } catch (error) {
      setActionError(formatError(error));
    } finally {
      setActionBusy(null);
    }
  };

  if (!invoke) {
    return (
      <SettingsPage
        eyebrow={t('settings.preferences')}
        title={t('settings.browserTitle')}
        description={t('settings.browserSubtitle')}
        className="settings-preference-page settings-browser-page"
      >
        <section className="settings-panel">
          <header>
            <GlobeIcon />
            <span>
              <strong>{t('settings.browser')}</strong>
              <small>{t('settings.browserUnavailable')}</small>
            </span>
          </header>
        </section>
      </SettingsPage>
    );
  }

  const brokerConnected = bridgeStatus?.brokerConnected ?? false;

  return (
    <SettingsPage
      eyebrow={t('settings.preferences')}
      title={t('settings.browserTitle')}
      description={t('settings.browserSubtitle')}
      className="settings-preference-page settings-browser-page"
    >
      <section className="settings-panel settings-browser-toggle-panel">
        <header>
          <GlobeIcon />
          <span>
            <strong>{t('settings.browserEnable')}</strong>
            <small>{t('settings.browserEnableDescription')}</small>
          </span>
        </header>
        <div className="settings-preference-switch-row">
          <span>
            <strong>{t('settings.browserBridge')}</strong>
            <small>{t('settings.browserBridgeDescription')}</small>
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            className={enabled ? 'active' : ''}
            disabled={toggleBusy}
            onClick={() => void toggleBridge(!enabled)}
          >
            <i aria-hidden="true" />
            {t(enabled ? 'settings.preferenceOn' : 'settings.preferenceOff')}
          </button>
        </div>
        {toggleError ? (
          <p className="settings-browser-error" role="alert">
            {toggleError}
          </p>
        ) : null}
      </section>

      <section className="settings-panel settings-browser-status-panel">
        <header>
          <ComponentInstanceIcon />
          <span>
            <strong>{t('settings.browserStatus')}</strong>
            <small>{t('settings.browserStatusDescription')}</small>
          </span>
        </header>
        <div className="settings-rows">
          <div className="settings-row">
            <span>
              <strong>{t('settings.browserBridge')}</strong>
            </span>
            <b>
              {bridgeStatus
                ? t(
                    bridgeStatus.enabled
                      ? 'settings.browserBridgeEnabled'
                      : 'settings.browserBridgeDisabled',
                  )
                : t('settings.notAvailable')}
            </b>
          </div>
          <div className="settings-row">
            <span>
              <strong>{t('settings.browserPort')}</strong>
            </span>
            <b>{bridgeStatus ? String(bridgeStatus.port) : t('settings.notAvailable')}</b>
          </div>
          <div className="settings-row">
            <span>
              <strong>{t('settings.browserBroker')}</strong>
            </span>
            <b>
              <Badge color={brokerConnected ? 'green' : 'gray'} variant="soft">
                {t(brokerConnected ? 'statusbar.connected' : 'statusbar.disconnected')}
              </Badge>
            </b>
          </div>
        </div>
      </section>

      <section className="settings-panel settings-browser-registration-panel">
        <header>
          <Link2Icon />
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
            <GlobeIcon />
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
            <LockClosedIcon />
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
            <IdCardIcon />
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
            <input
              type="text"
              autoComplete="off"
              placeholder={t('settings.browserCredentialsOriginPlaceholder')}
              aria-label={t('settings.browserCredentialsOrigin')}
              value={credentialOrigin}
              disabled={credentialSaving}
              onChange={(event) => setCredentialOrigin(event.currentTarget.value)}
            />
            <input
              type="text"
              autoComplete="off"
              placeholder={t('settings.browserCredentialsUsernamePlaceholder')}
              aria-label={t('settings.browserCredentialsUsername')}
              value={credentialUsername}
              disabled={credentialSaving}
              onChange={(event) => setCredentialUsername(event.currentTarget.value)}
            />
            <input
              type="password"
              autoComplete="new-password"
              placeholder={t('settings.browserCredentialsPasswordPlaceholder')}
              aria-label={t('settings.browserCredentialsPassword')}
              value={credentialPassword}
              disabled={credentialSaving}
              onChange={(event) => setCredentialPassword(event.currentTarget.value)}
            />
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
            <ActivityLogIcon />
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
            <Button
              type="submit"
              variant="soft"
              disabled={auditLoading}
              loading={auditLoading}
            >
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
                    <th>{t('settings.browserAuditColumn.time')}</th>
                    <th>{t('settings.browserAuditColumn.tool')}</th>
                    <th>{t('settings.browserAuditColumn.origin')}</th>
                    <th>{t('settings.browserAuditColumn.target')}</th>
                    <th>{t('settings.browserAuditColumn.outcome')}</th>
                    <th>{t('settings.browserAuditColumn.latency')}</th>
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
          <GlobeIcon />
          <span>
            <strong>{t('settings.browserExtensionSetup')}</strong>
          </span>
        </header>
        <p className="settings-browser-hint">{t('settings.browserExtensionHint')}</p>
      </section>
    </SettingsPage>
  );
}
