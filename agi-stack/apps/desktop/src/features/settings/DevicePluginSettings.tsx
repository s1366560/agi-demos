import { useCallback, useEffect, useRef, useState } from 'react';

import type { LocalPluginReference } from '../../api/localPluginClient';
import { pluginArchiveBase64 } from '../../api/localPluginClient';
import { useI18n } from '../../i18n';
import { openFilesWithDesktopDialog } from '../runtime/nativeFileBridge';

type Installed = {
  reference: LocalPluginReference;
  tools: string[];
  grant_id: string;
  grant_status: string;
  last_invoked_at: string | null;
  last_error: string | null;
  generation_id: string;
};
type Catalog = {
  context_token: string;
  machine_id: string;
  device_fingerprint: string;
  generation_id: string;
  trust_configured: boolean;
  can_manage: boolean;
  installations: Installed[];
};
type Preview = { reference: LocalPluginReference; declared_permissions: string[]; tools: string[] };

export function DevicePluginSettings({
  tenant,
  project,
}: {
  tenant: string;
  project: string;
}) {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [preview, setPreview] = useState<(Preview & { archive: string }) | null>(null);
  const manager=catalog?.can_manage === true;
  const [approved, setApproved] = useState(false);
  const [revoke, setRevoke] = useState<string | null>(null);
  const [args, setArgs] = useState('{}');
  const [result, setResult] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const mounted = useRef(false);
  const inFlight = useRef(false);
  const invoke = useCallback(
    async <T,>(operation: Record<string, unknown>, token?: string): Promise<T> => {
      const bridge = window.__MEMSTACK_DESKTOP__;
      if (bridge?.runtime !== 'electron' || !bridge.core?.invoke)
        throw new Error('device_plugin_native_required');
      return (await bridge.core.invoke('device_plugin_manage_v2', {
        input: {
          tenant_id: tenant,
          project_id: project,
          context_token: token,
          operation,
        },
      })) as T;
    },
    [tenant, project],
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
      const files = await openFilesWithDesktopDialog('plugin_package');
      if (!mounted.current || files.status === 'cancelled') return;
      const file = files.files[0];
      if (files.files.length !== 1 || !file) throw new Error('device_plugin_archive_invalid');
      const archive = await pluginArchiveBase64(file);
      if (!mounted.current) return;
      const data = await invoke<Preview>(
        { action: 'inspect', archive_base64: archive },
        catalog.context_token,
      );
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
        },
        catalog.context_token,
      );
      if (mounted.current) await refresh();
    });

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
        {t('localPlugins.choose')}
      </button>
      {catalog && !catalog.trust_configured ? <p>{t('localPlugins.noTrust')}</p> : null}
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
      {catalog && catalog.installations.length > 0 ? (
        <label>
          {t('localPlugins.deviceArgs')}
          <textarea value={args} onChange={(event) => setArgs(event.target.value)} />
        </label>
      ) : null}
      {catalog?.installations.map((item) => (
        <article key={item.reference.bundle_id}>
          <h3>
            {item.reference.bundle_id} · {item.reference.version}
          </h3>
          <code>{item.reference.digest}</code>
          {item.grant_status !== 'approved' ? (
            <p role="status">
              {t('localPlugins.deviceGrantUnavailable')} · {item.grant_status}
            </p>
          ) : null}
          {item.last_invoked_at ? (
            <p>
              {t('localPlugins.deviceLastRun')} · {item.reference.version} · {item.last_invoked_at}
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
                        { action: 'revoke', reference: item.reference, grant_id: item.grant_id },
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
