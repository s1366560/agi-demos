import { useEffect, useRef, useState } from 'react';
import type { MarketplaceCache as CacheStats, MarketplaceClient } from '../../../../../packages/plugin-marketplace-ui/src/client';
import type { MarketplaceMessage } from '../../../../../packages/plugin-marketplace-ui/src/messages';

export function MarketplaceCache({ client, canManage, t }: { client: MarketplaceClient; canManage: boolean; t: (key: MarketplaceMessage) => string }) {
  const [stats, setStats] = useState<CacheStats | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [removed, setRemoved] = useState<number | null>(null);
  const [reload, setReload] = useState(0);
  const generation = useRef(0);
  useEffect(() => {
    const version = ++generation.current;
    const controller = new AbortController();
    setStats(null); setError(''); setBusy(false); setRemoved(null);
    void client.cache(controller.signal).then((value) => { if (generation.current === version) setStats(value); }).catch((caught: unknown) => { if (!controller.signal.aborted && generation.current === version) setError(String(caught)); });
    return () => { generation.current++; controller.abort(); };
  }, [client, reload]);
  const cleanup = async () => {
    const version = generation.current;
    setBusy(true); setError('');
    try {
      const result = await client.cleanupCache();
      if (generation.current === version) { setStats(result); setRemoved(result.removed_bytes ?? 0); }
    } catch (caught) { if (generation.current === version) setError(String(caught)); }
    finally { if (generation.current === version) setBusy(false); }
  };
  return <section aria-label={t('cacheTitle')}>
    <h3>{t('cacheTitle')}</h3><p>{t('cacheHint')}</p>
    {error ? <p role="alert">{error}</p> : null}
    {stats ? <dl><dt>{t('cacheTotal')}</dt><dd>{stats.total_bytes}</dd><dt>{t('cacheReclaimable')}</dt><dd>{stats.reclaimable_bytes}</dd><dt>{t('cacheEntries')}</dt><dd>{stats.entries}</dd></dl> : <p>{t('loading')}</p>}
    {removed !== null ? <p role="status">{t('cacheRemoved')}: {removed}</p> : null}
    <div className="marketplace-actions"><button type="button" disabled={busy} onClick={() => setReload((value) => value + 1)}>{t('refresh')}</button><button type="button" disabled={busy || !canManage || !stats || stats.reclaimable_bytes <= 0} onClick={() => void cleanup()}>{t('cacheCleanup')}</button></div>
  </section>;
}
