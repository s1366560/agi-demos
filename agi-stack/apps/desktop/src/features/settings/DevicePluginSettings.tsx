import { useCallback, useEffect, useRef, useState } from 'react';

import type { LocalPluginReference } from '../../api/localPluginClient';
import { pluginArchiveBase64 } from '../../api/localPluginClient';
import { localPluginEnUS, localPluginZhCN } from './localPluginMessages';
import { openFilesWithDesktopDialog } from '../runtime/nativeFileBridge';

import { deviceRequest, type Catalog } from '../../packageHost/device';
type Preview = {
  reference: LocalPluginReference;
  declared_permissions: string[];
  tools: string[];
  workspace?: { label: string; token: string };
};

export function DevicePluginSettings({
  tenant,
  project,
  pluginId,
  digest,
  loadArchive,
}: {
  tenant: string;
  project: string;
  pluginId?: string;
  digest?: string | null;
  loadArchive?: () => Promise<string>;
}) {
  const messages = document.documentElement.lang.startsWith('zh')
    ? localPluginZhCN
    : localPluginEnUS;
  const t = (key: keyof typeof messages) => messages[key];
  const [modelUrl, setModelUrl] = useState('');
  const [modelName, setModelName] = useState('');
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [preview, setPreview] = useState<(Preview & { archive: string }) | null>(null);
  const manager = catalog?.can_manage === true;
  const [approved, setApproved] = useState(false);
  const [revoke, setRevoke] = useState<string | null>(null);
  const [args, setArgs] = useState('{}');
  const [result, setResult] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const mounted = useRef(false);
  const inFlight = useRef(false);
  const invoke = useCallback(
    <T,>(operation: Record<string, unknown>, token?: string): Promise<T> =>
      deviceRequest<T>(tenant, project, pluginId, operation, token),
    [tenant, project, pluginId],
  );

  const refresh = useCallback(async () => {
    const next = await invoke<Catalog>({ action: 'list' });
    if (mounted.current) {
      setCatalog(next);
      setRevoke(null);
      setPreview(null);
      setApproved(false);
      setResult('');
    }
  }, [invoke]);

  useEffect(() => {
    mounted.current = true;
    let live = true;
    void invoke<Catalog>({ action: 'list' })
      .then((data) => {
        if (live) setCatalog(data);
      })
      .catch((cause: unknown) => {
        if (live) setError(String(cause));
      });
    return () => {
      live = false;
      mounted.current = false;
    };
  }, [invoke]);

  const perform = async (work: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError('');
    setResult('');
    try {
      await work();
    } catch (cause) {
      if (mounted.current) setError(String(cause));
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  const choose = () =>
    perform(async () => {
      if (!catalog) return;
      setPreview(null);
      setApproved(false);
      let archive: string;
      if (loadArchive && manager) {
        archive = await loadArchive();
      } else {
        const files = await openFilesWithDesktopDialog('plugin_package');
        if (!mounted.current || files.status === 'cancelled') return;
        const file = files.files[0];
        if (files.files.length !== 1 || !file) throw new Error('device_plugin_archive_invalid');
        archive = await pluginArchiveBase64(file);
      }
      if (!mounted.current) return;
      const data = await invoke<Preview>(
        { action: 'inspect', archive_base64: archive },
        catalog.context_token,
      );
      if (
        (pluginId && data.reference.bundle_id !== pluginId) ||
        (digest &&
          data.reference.digest.replace(/^sha256:/u, '') !== digest.replace(/^sha256:/u, ''))
      ) {
        throw new Error('device_plugin_release_changed');
      }
      if (mounted.current) setPreview({ ...data, archive });
    });
  const install = () =>
    perform(async () => {
      if (!catalog || !preview || !approved) return;
      await invoke(
        {
          action: 'install',
          archive_base64: preview.archive,
          reference: preview.reference,
          approved_permissions: preview.declared_permissions,
          approve_for_day: manager,
          ...(preview.workspace && {
            workspace_token: preview.workspace.token,
          }),
          ...(preview.declared_permissions.includes('device.local-chat') &&
            (modelName || modelUrl) && {
              local_model: { base_url: modelUrl, model: modelName },
            }),
        },
        catalog.context_token,
      );
      if (mounted.current) await refresh();
    });

  const installations = (catalog?.installations ?? []).filter(
    ({ reference }) =>
      (!pluginId || reference.bundle_id === pluginId) &&
      (!digest || reference.digest.replace(/^sha256:/u, '') === digest.replace(/^sha256:/u, '')),
  );
  return (
    <section className="local-plugin-settings">
      <h2>{t('localPlugins.deviceTitle')}</h2>
      <p>
        {tenant} / {project}
      </p>
      {catalog ? (
        <dl>
          <dt>{t('localPlugins.deviceId')}</dt>
          <dd>
            <code>{catalog.machine_id}</code>
          </dd>
          <dt>{t('localPlugins.deviceFingerprint')}</dt>
          <dd>
            <code>{catalog.device_fingerprint}</code>
          </dd>
          <dt>{t('localPlugins.deviceGeneration')}</dt>
          <dd>
            <code>{catalog.generation_id}</code>
          </dd>
        </dl>
      ) : null}
      <button type="button" disabled={busy} onClick={() => void perform(refresh)}>
        {t('localPlugins.refresh')}
      </button>
      <button
        type="button"
        disabled={busy || !catalog?.trust_configured}
        onClick={() => void choose()}
      >
        {t(loadArchive && manager ? 'localPlugins.prepareRelease' : 'localPlugins.choose')}
      </button>
      {catalog && !catalog.trust_configured ? <p>{t('localPlugins.noTrust')}</p> : null}
      {catalog && pluginId && installations.length === 0 ? (
        <p role="status">{t('localPlugins.devicePending')}</p>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
      {preview ? (
        <div>
          <h3>
            {preview.reference.bundle_id} · {preview.reference.version}
          </h3>
          <code>{preview.reference.digest}</code>
          <p>{t('localPlugins.permissions')}</p>
          <ul>
            {preview.declared_permissions.map((permission) => (
              <li key={permission}>{permission}</li>
            ))}
          </ul>
          {preview.workspace && (
            <fieldset>
              <legend>
                {t('localPlugins.localWorkspace')} · {preview.workspace.label}
              </legend>
              <button
                disabled={busy}
                type="button"
                onClick={() =>
                  void perform(async () => {
                    const pick = window.__MEMSTACK_DESKTOP__?.core?.invoke;
                    if (!pick || !catalog) throw new Error('native_file_bridge_unavailable');
                    const picked = await pick<{ status: string }>('package_workspace_choose');
                    if (picked.status !== 'selected') return;
                    setApproved(false);
                    const offer = await invoke<Preview>(
                      { action: 'inspect', archive_base64: preview.archive },
                      catalog.context_token,
                    );
                    if (mounted.current) setPreview({ ...offer, archive: preview.archive });
                  })
                }
              >
                {t('localPlugins.chooseDirectory')}
              </button>
              {preview.declared_permissions.includes('device.local-chat') && (
                <>
                  <p>{t('localPlugins.deviceModelDescription')}</p>
                  <label>
                    {t('localPlugins.deviceModelOrigin')}
                    <input
                      value={modelUrl}
                      onChange={(e) => {
                        setApproved(false);
                        setModelUrl(e.target.value);
                      }}
                    />
                  </label>
                  <label>
                    {t('localPlugins.deviceModelName')}
                    <input
                      value={modelName}
                      onChange={(e) => {
                        setApproved(false);
                        setModelName(e.target.value);
                      }}
                    />
                  </label>
                </>
              )}
            </fieldset>
          )}
          <label>
            <input
              type="checkbox"
              checked={approved}
              onChange={(event) => setApproved(event.target.checked)}
            />
            {t(manager ? 'localPlugins.deviceApprove' : 'localPlugins.deviceExistingGrant')}
          </label>
          <button type="button" disabled={busy || !approved} onClick={() => void install()}>
            {t('localPlugins.install')}
          </button>
        </div>
      ) : null}
      {catalog && installations.length > 0 ? (
        <label>
          {t('localPlugins.deviceArgs')}
          <textarea value={args} onChange={(event) => setArgs(event.target.value)} />
        </label>
      ) : null}
      {catalog &&
        installations.map((item) => (
          <article key={item.reference.bundle_id}>
            <h3>
              {item.reference.bundle_id} · {item.reference.version}
            </h3>
            <code>{item.reference.digest}</code>
            {item.grant_status !== 'approved' || catalog.generation_id !== item.generation_id ? (
              <p role="status">
                {t('localPlugins.deviceGrantUnavailable')} ·{' '}
                {catalog.generation_id !== item.generation_id
                  ? t('localPlugins.deviceGeneration')
                  : item.grant_status}
              </p>
            ) : (
              <p role="status">{t('localPlugins.deviceReady')}</p>
            )}
            {item.last_invoked_at ? (
              <p>
                {t('localPlugins.deviceLastRun')} · {item.reference.version} ·{' '}
                {item.last_invoked_at}
              </p>
            ) : null}
            {item.last_error ? <p role="alert">{item.last_error}</p> : null}
            {manager && item.grant_status === 'approved' ? (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  revoke !== item.grant_id
                    ? setRevoke(item.grant_id)
                    : void perform(async () => {
                        await invoke(
                          {
                            action: 'revoke',
                            reference: item.reference,
                            grant_id: item.grant_id,
                          },
                          catalog.context_token,
                        );
                        if (mounted.current) await refresh();
                      })
                }
              >
                {t(revoke === item.grant_id ? 'localPlugins.confirm' : 'localPlugins.revoke')}
              </button>
            ) : null}
            {item.tools.map((tool) => (
              <button
                type="button"
                key={tool}
                disabled={
                  busy ||
                  item.grant_status !== 'approved' ||
                  catalog.generation_id !== item.generation_id
                }
                onClick={() =>
                  void perform(async () => {
                    const output = await invoke(
                      {
                        action: 'invoke',
                        reference: item.reference,
                        grant_id: item.grant_id,
                        tool,
                        input: JSON.parse(args),
                      },
                      catalog.context_token,
                    );
                    if (mounted.current) {
                      await refresh();
                      if (mounted.current) setResult(JSON.stringify(output, null, 2));
                    }
                  })
                }
              >
                {t('localPlugins.deviceRun')} {tool}
              </button>
            ))}
          </article>
        ))}
      {result ? <pre aria-live="polite">{result}</pre> : null}
    </section>
  );
}
