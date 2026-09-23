import { useEffect, useRef, useState } from 'react';
import type { MarketplaceClient, MarketplaceOAuthStatus } from '../../../../../packages/plugin-marketplace-ui/src/client';
import type { MarketplaceMessage } from '../../../../../packages/plugin-marketplace-ui/src/messages';

export function MarketplaceOAuth({ client, installationId, service, canManage, t }: {
  client: MarketplaceClient; installationId: string; service: MarketplaceOAuthStatus & { name: string };
  canManage: boolean; t: (key: MarketplaceMessage) => string;
}) {
  const [state, setState] = useState<MarketplaceOAuthStatus>(service);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [clientId, setClientId] = useState('');
  const [metadataUrl, setMetadataUrl] = useState('');
  const generation = useRef(0);
  const actionGeneration = useRef(0);
  useEffect(() => {
    const version = ++generation.current;
    const action = actionGeneration.current;
    setState(service); setError(''); setBusy(false); setClientId(''); setMetadataUrl('');
    const controller = new AbortController();
    void client.oauthStatus(installationId, service.name, controller.signal).then((value) => {
      if (generation.current === version && actionGeneration.current === action) setState((previous) => value.status === 'authorizing' && !value.authorization_url && previous.authorization_url ? { ...value, authorization_url: previous.authorization_url } : value);
    }).catch((caught: unknown) => {
      if (!controller.signal.aborted && generation.current === version) setError(String(caught));
    });
    return () => { generation.current++; controller.abort(); };
  }, [client, installationId, service.name]);
  useEffect(() => {
    if (state.status !== 'authorizing' || busy) return;
    const version = generation.current;
    const action = actionGeneration.current;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void client.oauthStatus(installationId, service.name, controller.signal).then((value) => {
        if (generation.current === version && actionGeneration.current === action) setState((previous) => value.status === 'authorizing' && !value.authorization_url && previous.authorization_url ? { ...value, authorization_url: previous.authorization_url } : value);
      }).catch((caught: unknown) => {
        if (!controller.signal.aborted && generation.current === version) setError(String(caught));
      });
    }, 2000);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [client, installationId, service.name, state, busy]);
  const open = (url: string) => {
    const target = new URL(url);
    if (target.username || target.password || !(target.protocol === 'https:' || (target.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname)))) throw new Error(t('oauthInvalidUrl'));
    // Electron's existing window-open policy forwards allowed web URLs to the system browser.
    window.open(target.href, '_blank', 'noopener,noreferrer');
  };
  const mutate = async (action: 'start' | 'cancel' | 'disconnect') => {
    const version = generation.current;
    actionGeneration.current++;
    setBusy(true); setError('');
    try {
      const result = await client.oauthAction(installationId, service.name, action, {
        ...(clientId.trim() ? { client_id: clientId.trim() } : {}),
        ...(metadataUrl.trim() ? { client_metadata_url: metadataUrl.trim() } : {}),
      });
      if (generation.current !== version) return;
      setState(result);
      if (action === 'start' && result.authorization_url) open(result.authorization_url);
    } catch (caught) {
      if (generation.current === version) setError(caught instanceof Error ? caught.message : String(caught));
    } finally { if (generation.current === version) setBusy(false); }
  };
  return <section aria-label={`${t('oauthTitle')}: ${service.name}`}>
    <h4>{t('oauthTitle')} · {service.name}</h4>
    <p role="status">{t(`oauth_${state.status}`)}</p>
    {state.reason ? <p>{state.reason}</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {state.status === 'needs_configuration' ? <>
      <label>{t('oauthClientId')}<input value={clientId} onChange={(event) => setClientId(event.target.value)} disabled={busy || !canManage} /></label>
      <label>{t('oauthMetadataUrl')}<input type="url" value={metadataUrl} onChange={(event) => setMetadataUrl(event.target.value)} disabled={busy || !canManage} /></label>
    </> : null}
    <div className="marketplace-actions">
      {state.status === 'authorizing' ? <>
        {state.authorization_url ? <button type="button" disabled={busy || !canManage} onClick={() => { try { open(state.authorization_url!); } catch (caught) { setError(String(caught)); } }}>{t('oauthOpen')}</button> : null}
        <button type="button" disabled={busy || !canManage} onClick={() => void mutate('cancel')}>{t('oauthCancel')}</button>
      </> : <button type="button" disabled={busy || !canManage} onClick={() => void mutate(state.status === 'connected' ? 'disconnect' : 'start')}>{t(state.status === 'connected' ? 'oauthDisconnect' : 'oauthConnect')}</button>}
    </div>
  </section>;
}
