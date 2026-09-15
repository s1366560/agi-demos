import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import {
  pluginArchiveBase64,
  type LocalPluginAction,
  type LocalPluginClient,
  type LocalPluginInspection,
  type LocalPluginInstallation,
} from '../../api/localPluginClient';
import { useI18n } from '../../i18n';
import type { DesktopRuntimeConfig } from '../../types';
import { openFilesWithDesktopDialog } from '../runtime/nativeFileBridge';
import './LocalPluginSettings.css';

type Preview = {
  inspection: LocalPluginInspection;
  archive: string;
  filename: string;
};
type Confirmation = {
  action: 'revoke' | 'uninstall';
  installation: LocalPluginInstallation;
};

export function LocalPluginSettings({
  config,
  canManage,
}: {
  config: DesktopRuntimeConfig;
  canManage: boolean;
}) {
  const { t } = useI18n();
  const client = useMemo(
    () =>
      config.mode === 'local' && config.tenantId && config.projectId
        ? new DesktopApiClient(config).localPlugins()
        : null,
    [config],
  );
  const currentClient = useRef(client);
  currentClient.current = client;
  const controllerRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const [installations, setInstallations] = useState<readonly LocalPluginInstallation[]>([]);
  const [trustConfigured, setTrustConfigured] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [permissions, setPermissions] = useState<readonly string[]>([]);
  const [scopeApproved, setScopeApproved] = useState(false);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);

  const applyCatalog = useCallback((catalog: Awaited<ReturnType<LocalPluginClient['list']>>) => {
    setInstallations(catalog.installations);
    setTrustConfigured(catalog.trustConfigured);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    busyRef.current = false;
    setBusy(false);
    setInstallations([]);
    setTrustConfigured(null);
    setPreview(null);
    setConfirmation(null);
    setPermissions([]);
    setScopeApproved(false);
    setError(null);
    setNotice(false);
    if (client) {
      void client
        .list(controller.signal)
        .then((catalog) => {
          if (!controller.signal.aborted) applyCatalog(catalog);
        })
        .catch((caught: unknown) => {
          if (!controller.signal.aborted) setError(errorMessage(caught));
        });
    }
    return () => {
      controller.abort();
      controllerRef.current?.abort();
    };
  }, [client, applyCatalog]);

  const perform = useCallback(
    async (work: (active: LocalPluginClient, signal: AbortSignal) => Promise<void>) => {
      if (!client || busyRef.current) return;
      busyRef.current = true;
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setBusy(true);
      setError(null);
      setNotice(false);
      try {
        await work(client, controller.signal);
      } catch (caught) {
        if (!controller.signal.aborted && currentClient.current === client)
          setError(errorMessage(caught));
      } finally {
        if (currentClient.current === client && !controller.signal.aborted) {
          busyRef.current = false;
          setBusy(false);
        }
      }
    },
    [client],
  );

  const choose = () => {
    if (!canManage || trustConfigured !== true) return;
    void perform(async (active, signal) => {
      const result = await openFilesWithDesktopDialog('plugin_package');
      if (result.status === 'cancelled' || signal.aborted) return;
      const file = result.files[0];
      if (!file || result.files.length !== 1) throw new Error('local_plugin_archive_invalid');
      setPreview(null);
      setPermissions([]);
      setScopeApproved(false);
      const archive = await pluginArchiveBase64(file);
      if (signal.aborted) return;
      const inspection = await active.inspect(archive, signal);
      if (signal.aborted) return;
      setPreview({ inspection, archive, filename: file.name });
      setPermissions([]);
      setScopeApproved(false);
      setConfirmation(null);
    });
  };

  const install = () => {
    if (
      !preview ||
      !scopeApproved ||
      trustConfigured !== true ||
      !canManage ||
      permissions.length !== preview.inspection.declared_permissions.length
    )
      return;
    void perform(async (active, signal) => {
      await active.install(preview.inspection, preview.archive, permissions, signal);
      if (signal.aborted) return;
      setPreview(null);
      setNotice(true);
      const catalog = await active.list(signal);
      if (!signal.aborted) applyCatalog(catalog);
    });
  };
  const control = (action: LocalPluginAction, installation: LocalPluginInstallation) => {
    if (!canManage) return;
    void perform(async (active, signal) => {
      await active.control(action, installation, signal);
      if (signal.aborted) return;
      setConfirmation(null);
      setNotice(true);
      const catalog = await active.list(signal);
      if (!signal.aborted) applyCatalog(catalog);
    });
  };

  return (
    <section className="local-plugin-settings" aria-busy={busy}>
      <header>
        <div>
          <h2>{t('localPlugins.title')}</h2>
          <p>{t('localPlugins.description')}</p>
        </div>
        <button
          type="button"
          disabled={!client || busy}
          onClick={() =>
            void perform(async (active, signal) => {
              const catalog = await active.list(signal);
              if (!signal.aborted) applyCatalog(catalog);
            })
          }
        >
          {t('localPlugins.refresh')}
        </button>
        <button
          type="button"
          disabled={!client || !canManage || trustConfigured !== true || busy}
          onClick={choose}
        >
          {t('localPlugins.choose')}
        </button>
      </header>
      {!client ? (
        <p>{t('localPlugins.noScope')}</p>
      ) : (
        <p className="local-plugin-scope">
          {t('localPlugins.scope')}:{' '}
          <code>
            {config.tenantId} / {config.projectId}
          </code>
        </p>
      )}
      {trustConfigured === false ? <p role="status">{t('localPlugins.noTrust')}</p> : null}
      {error ? (
        <p className="local-plugin-error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? <p role="status">{t('localPlugins.confirmed')}</p> : null}
      {busy ? <p role="status">{t('localPlugins.busy')}</p> : null}
      {preview ? (
        <section className="local-plugin-review" aria-label={t('localPlugins.inspect')}>
          <h3>
            {t('localPlugins.inspect')}: {preview.filename}
          </h3>
          <p>
            <strong>{preview.inspection.reference.bundle_id}</strong> ·{' '}
            {preview.inspection.reference.version}
          </p>
          <code>{preview.inspection.reference.digest}</code>
          <ul>
            {preview.inspection.plugins.map((plugin) => (
              <li key={plugin.plugin_id}>
                {plugin.plugin_id} · {plugin.version}
              </li>
            ))}
          </ul>
          <fieldset disabled={busy}>
            <legend>{t('localPlugins.permissions')}</legend>
            {!preview.inspection.declared_permissions.length ? (
              <p>{t('localPlugins.noPermissions')}</p>
            ) : null}
            {preview.inspection.declared_permissions.map((permission) => (
              <label key={permission}>
                <input
                  type="checkbox"
                  checked={permissions.includes(permission)}
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setPermissions((current) =>
                      checked
                        ? [...new Set([...current, permission])]
                        : current.filter((item) => item !== permission),
                    );
                  }}
                />
                <code>{permission}</code>
              </label>
            ))}
            <label>
              <input
                type="checkbox"
                checked={scopeApproved}
                onChange={(event) => setScopeApproved(event.target.checked)}
              />
              {t('localPlugins.approveScope')}
            </label>
          </fieldset>
          <button
            type="button"
            disabled={
              busy ||
              !canManage ||
              !scopeApproved ||
              trustConfigured !== true ||
              permissions.length !== preview.inspection.declared_permissions.length
            }
            onClick={install}
          >
            {t('localPlugins.install')}
          </button>
          <button type="button" disabled={busy} onClick={() => setPreview(null)}>
            {t('localPlugins.cancel')}
          </button>
        </section>
      ) : null}
      {confirmation ? (
        <section className="local-plugin-review" aria-label={t('localPlugins.confirm')}>
          <h3>
            {t(`localPlugins.${confirmation.action}`)}:{' '}
            {confirmation.installation.reference.bundle_id} ·{' '}
            {confirmation.installation.reference.version}
          </h3>
          <p>{t('localPlugins.confirmDescription')}</p>
          <code>{confirmation.installation.reference.digest}</code>
          <button
            type="button"
            disabled={busy || !canManage}
            onClick={() => control(confirmation.action, confirmation.installation)}
          >
            {t('localPlugins.confirm')}
          </button>
          <button type="button" disabled={busy} onClick={() => setConfirmation(null)}>
            {t('localPlugins.cancel')}
          </button>
        </section>
      ) : null}
      {trustConfigured !== null && !installations.length ? <p>{t('localPlugins.empty')}</p> : null}
      <div className="local-plugin-list">
        {installations.map((installation) => (
          <article key={installation.reference.bundle_id}>
            <h3>
              {installation.reference.bundle_id} · {installation.reference.version}
            </h3>
            <p>
              {t(
                installation.authorization_status === 'revoked'
                  ? 'localPlugins.revoked'
                  : installation.enabled
                    ? 'localPlugins.enabled'
                    : 'localPlugins.disabled',
              )}
            </p>
            <p role={installation.activation_status === 'failed' ? 'alert' : 'status'}>
              {t(`localPlugins.activation.${installation.activation_status}`)}
              {installation.activation_error ? <>: {installation.activation_error}</> : null}
            </p>
            <code>{installation.reference.digest}</code>
            <ul>
              {installation.approved_permissions.map((permission) => (
                <li key={permission}>
                  <code>{permission}</code>
                </li>
              ))}
            </ul>
            {installation.authorization_status === 'revoked' ? (
              <p>{t('localPlugins.reapprove')}</p>
            ) : null}
            <div className="local-plugin-actions">
              <button
                type="button"
                disabled={busy || !canManage || installation.authorization_status === 'revoked'}
                onClick={() => control(installation.enabled ? 'disable' : 'enable', installation)}
              >
                {t(installation.enabled ? 'localPlugins.disable' : 'localPlugins.enable')}
              </button>
              <button
                type="button"
                disabled={busy || !canManage || installation.authorization_status === 'revoked'}
                onClick={() => {
                  setPreview(null);
                  setConfirmation({ action: 'revoke', installation });
                }}
              >
                {t('localPlugins.revoke')}
              </button>
              <button
                type="button"
                disabled={busy || !canManage}
                onClick={() => {
                  setPreview(null);
                  setConfirmation({ action: 'uninstall', installation });
                }}
              >
                {t('localPlugins.uninstall')}
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
function errorMessage(value: unknown): string {
  return value instanceof Error ? value.message : String(value);
}
