import { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, Button } from '@radix-ui/themes';
import { ComponentInstanceIcon, GlobeIcon, Link2Icon } from '@radix-ui/react-icons';

import { DesktopApiClient } from '../../api/client';
import { useI18n } from '../../i18n';
import type {
  BrowserBridgeInstallResult,
  BrowserBridgeStatus,
  BrowserBridgeUninstallResult,
  BrowserOriginGrant,
  DesktopRuntimeConfig,
  LocalRuntimeStatus,
} from '../../types';
import { SettingsPage } from './SettingsCorePages';
import './BrowserIntegrationSettingsPage.css';

const BROWSER_BRIDGE_STATUS_POLL_MS = 5_000;

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

// Local-runtime bridge between the Chrome extension (native messaging broker)
// and the desktop sidecar. Status polling runs only while this section is
// mounted; leaving the section unmounts the page and clears the interval.
export function BrowserIntegrationSettingsPage({ config }: { config?: DesktopRuntimeConfig }) {
  const { t } = useI18n();
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke;
  const originGrantsClient = useMemo(
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

  const refreshOriginGrants = useCallback(async () => {
    if (!originGrantsClient) return;
    try {
      const grants = await originGrantsClient.listBrowserOriginGrants();
      setOriginGrants(grants);
      setOriginGrantsError(null);
    } catch (error) {
      setOriginGrantsError(formatError(error));
    }
  }, [originGrantsClient]);

  useEffect(() => {
    setOriginGrants(null);
    setOriginGrantsError(null);
    void refreshOriginGrants();
  }, [refreshOriginGrants]);

  const revokeOriginGrant = async (grantId: string) => {
    if (!originGrantsClient || revokingGrantId) return;
    setRevokingGrantId(grantId);
    setOriginGrantsError(null);
    try {
      await originGrantsClient.revokeBrowserOriginGrant(grantId);
      await refreshOriginGrants();
    } catch (error) {
      setOriginGrantsError(formatError(error));
    } finally {
      setRevokingGrantId(null);
    }
  };

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

  const runRegistration = async (action: 'install' | 'uninstall') => {
    if (!invoke || actionBusy) return;
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

      {originGrantsClient ? (
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
