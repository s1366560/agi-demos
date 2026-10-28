import { useEffect, useRef, useState } from 'react';
import type { DesktopMCPOAuthStatus, DesktopMCPServerSummary } from '../../api/client';
import type { DesktopProjectMcpServersClientV2 } from '../../plugins/desktopProjectMcpServersAuthorityModuleV2';
import { useI18n } from '../../i18n';
import { mcpServerRevision } from './mcpMutationAttemptModel';

export function MCPServerOAuth({
  server,
  client,
  canManage,
  onChanged,
}: {
  server: DesktopMCPServerSummary;
  client: DesktopProjectMcpServersClientV2;
  canManage: boolean;
  onChanged: () => Promise<void>;
}) {
  const { t } = useI18n();
  const [status, setStatus] = useState<DesktopMCPOAuthStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clientId, setClientId] = useState('');
  const [scopes, setScopes] = useState('');
  const [clientMetadata, setClientMetadata] = useState('');
  const attempts = useRef(new Map<string, string>());
  const lifetime = useRef(0);
  const mutation = useRef<AbortController | null>(null);
  const statusRef = useRef(status);
  statusRef.current = status;

  useEffect(() => {
    const current = ++lifetime.current;
    setBusy(false);
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const result = await client.getMCPOAuthStatus(server.id, controller.signal);
        if (controller.signal.aborted || lifetime.current !== current) return;
        if (statusRef.current?.status === 'authorizing' && result.status === 'connected')
          void onChanged();
        setStatus((previous) => ({
          ...result,
          ...(result.status === 'authorizing' && previous?.authorization_url
            ? { authorization_url: previous.authorization_url }
            : {}),
        }));
        if (result.status === 'authorizing')
          timer = setTimeout(() => {
            void load();
          }, 1000);
      } catch (caught) {
        if (!controller.signal.aborted && lifetime.current === current)
          setError(caught instanceof Error ? caught.message : String(caught));
      }
    };
    void load();
    return () => {
      controller.abort();
      mutation.current?.abort();
      clearTimeout(timer);
      lifetime.current += 1;
    };
  }, [client, server.id, server.runtime_metadata?.revision, status?.status === 'authorizing']);

  const mutate = async (action: 'start' | 'cancel' | 'disconnect') => {
    if (busy || !canManage) return;
    const current = lifetime.current;
    const controller = new AbortController();
    mutation.current?.abort();
    mutation.current = controller;
    const fields = {
      action,
      project_id: server.project_id,
      expected_revision: mcpServerRevision(server),
      ...(clientId.trim() ? { client_id: clientId.trim() } : {}),
      ...(clientMetadata.trim() ? { client_metadata_url: clientMetadata.trim() } : {}),
      scopes: scopes.trim() ? scopes.trim().split(/\s+/u) : [],
    };
    const signature = JSON.stringify(fields);
    let key = attempts.current.get(signature);
    if (!key) {
      key = crypto.randomUUID();
      attempts.current.set(signature, key);
    }
    setBusy(true);
    setError(null);
    try {
      const result = await client.mutateMCPOAuth(
        server.id,
        { ...fields, idempotency_key: key },
        controller.signal,
      );
      if (lifetime.current !== current) return;
      attempts.current.delete(signature);
      setStatus(result);
      if (action === 'disconnect') await onChanged();
    } catch (caught) {
      if (lifetime.current === current)
        setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (lifetime.current === current) setBusy(false);
    }
  };
  let authorizationUrl: string | null = null;
  if (status?.status === 'authorizing' && status.authorization_url) {
    try {
      const url = new URL(status.authorization_url);
      if (url.protocol === 'https:' && !url.username && !url.password) authorizationUrl = url.href;
    } catch {
      /* Invalid provider URLs are never opened. */
    }
  }

  return (
    <div className="mcp-server-oauth">
      <small>
        {t('settings.mcpOAuth.label')}:{' '}
        {t(`settings.mcpOAuth.status.${status?.status ?? 'not_connected'}`)}
      </small>
      <details>
        <summary>{t('settings.mcpOAuth.clientOptions')}</summary>
        <label>
          {t('settings.mcpOAuth.clientId')}
          <input
            value={clientId}
            disabled={busy}
            onChange={(event) => setClientId(event.target.value)}
          />
        </label>
        <label>
          {t('settings.mcpOAuth.clientMetadata')}
          <input
            value={clientMetadata}
            disabled={busy}
            onChange={(event) => setClientMetadata(event.target.value)}
          />
        </label>
        <label>
          {t('settings.mcpOAuth.scopes')}
          <input
            value={scopes}
            disabled={busy}
            onChange={(event) => setScopes(event.target.value)}
          />
        </label>
      </details>
      <div className="mcp-server-actions">
        {status?.status === 'authorizing' ? (
          <>
            {authorizationUrl ? (
              <a href={authorizationUrl} target="_blank" rel="noopener noreferrer">
                {t('settings.mcpOAuth.open')}
              </a>
            ) : null}
            <button
              type="button"
              disabled={busy || !canManage}
              onClick={() => {
                void mutate('cancel');
              }}
            >
              {t('common.cancel')}
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={busy || !canManage}
            onClick={() => {
              void mutate('start');
            }}
          >
            {t(
              status?.status === 'connected'
                ? 'settings.mcpOAuth.reconnect'
                : 'settings.mcpOAuth.connect',
            )}
          </button>
        )}
        {status?.status === 'connected' || status?.status === 'expired' ? (
          <button
            type="button"
            disabled={busy || !canManage}
            onClick={() => {
              void mutate('disconnect');
            }}
          >
            {t('settings.mcpOAuth.disconnect')}
          </button>
        ) : null}
      </div>
      {error ? <small role="alert">{error}</small> : null}
    </div>
  );
}
