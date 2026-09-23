import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  createMarketplaceClient,
  filterPlugins,
  type MarketplaceClient,
  type PluginDescriptor,
  type MarketplaceTransport,
} from '../../../../../agi-stack/packages/plugin-marketplace-ui/src/client';
import {
  marketplaceEn,
  marketplaceZh,
  type MarketplaceMessage,
} from '../../../../../agi-stack/packages/plugin-marketplace-ui/src/messages';
import i18n from '@/i18n/config';
import { httpClient } from '@/services/client/httpClient';
import { MarketplaceView } from './MarketplaceView';

i18n.addResourceBundle('en-US', 'pluginMarketV3', {
  ...marketplaceEn,
  adminRequired:
    'Public catalog. A tenant and project administrator can manage sources and installations.',
});
i18n.addResourceBundle('zh-CN', 'pluginMarketV3', {
  ...marketplaceZh,
  adminRequired: '当前为公共目录。租户和项目管理员可以管理来源与安装。',
});
const transport: MarketplaceTransport = (path, options) => {
  const relative = path.replace(/^\/api\/v1/, '');
  if (options.method === 'POST') return httpClient.post(relative, options.body);
  if (options.method === 'DELETE') return httpClient.delete(relative);
  return httpClient.get(relative, options.signal ? { signal: options.signal } : {});
};
export function PluginMarketplaceV3({
  tenantId,
  projectId,
  canManage,
  onInstallSignedV2,
}: {
  tenantId: string;
  projectId: string | null;
  canManage: boolean;
  onInstallSignedV2?: (() => void) | undefined;
}) {
  const { t } = useTranslation('pluginMarketV3');
  const client = useMemo(
    () =>
      createMarketplaceClient(
        transport,
        { tenant_id: tenantId, ...(projectId ? { project_id: projectId } : {}) },
        canManage
      ),
    [tenantId, projectId, canManage]
  );
  if (!canManage)
    return <PublicMarketplaceV3 key={`${tenantId}:${projectId ?? ''}`} client={client} />;
  return (
    <MarketplaceView
      key={`${tenantId}:${projectId ?? ''}`}
      client={client}
      t={(key: MarketplaceMessage) => t(key)}
      scope={`${tenantId}${projectId ? ` / ${projectId}` : ''}`}
      canManage={canManage}
      local={false}
      onInstallSignedV2={onInstallSignedV2}
    />
  );
}

function PublicMarketplaceV3({ client }: { client: MarketplaceClient }) {
  const { t } = useTranslation('pluginMarketV3');
  const [items, setItems] = useState<PluginDescriptor[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [detail, setDetail] = useState<PluginDescriptor | null>(null);
  const [filters, setFilters] = useState({
    query: '',
    category: '',
    capability: '',
    target: '',
    source: '',
  });
  useEffect(() => {
    const controller = new AbortController();
    void client
      .catalog(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setItems(result.items);
        setError(
          (result.errors ?? []).map((item) => `${item.source_id}: ${item.error}`).join('; ')
        );
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted)
          setError(caught instanceof Error ? caught.message : String(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [client, reload]);
  const options = {
    category: [...new Set(items.map((item) => item.category))],
    capability: [...new Set(items.flatMap((item) => item.capabilities))],
    target: [...new Set(items.flatMap((item) => item.targets))],
    source: [...new Set(items.map((item) => item.source_id))],
  };
  const visible = filterPlugins(items, filters);
  return (
    <section className="marketplace-v3" aria-busy={loading}>
      <header>
        <div>
          <h2>{t('title')}</h2>
          <p>{t('description')}</p>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => {
            setLoading(true);
            setError('');
            setItems([]);
            setDetail(null);
            setReload((value) => value + 1);
          }}
        >
          {t('refresh')}
        </button>
      </header>
      <p role="status">{t('adminRequired')}</p>
      {error ? (
        <p role="alert" className="marketplace-error">
          {error}
        </p>
      ) : null}
      {loading ? <p role="status">{t('loading')}</p> : null}
      <div className="marketplace-filters">
        <label>
          {t('search')}
          <input
            type="search"
            value={filters.query}
            onChange={(event) => setFilters({ ...filters, query: event.target.value })}
          />
        </label>
        {(Object.keys(options) as Array<keyof typeof options>).map((key) => (
          <label key={key}>
            {t(key)}
            <select
              value={filters[key]}
              onChange={(event) => setFilters({ ...filters, [key]: event.target.value })}
            >
              <option value="">{t('all')}</option>
              {options[key].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      {!loading && !visible.length ? <p>{t('empty')}</p> : null}
      <div className="marketplace-grid">
        {visible.map((plugin) => (
          <article key={`${plugin.source_id}:${plugin.id}:${plugin.version}`}>
            <div className="marketplace-card-title">
              <h3>{plugin.name}</h3>
              <span>{plugin.version}</span>
            </div>
            <p>{plugin.description}</p>
            <p className="marketplace-muted">
              {plugin.publisher} · {plugin.source_id}
            </p>
            <div className="marketplace-badges">
              {plugin.capabilities.map((capability) => (
                <span key={capability}>{capability}</span>
              ))}
            </div>
            {!plugin.compatible ? (
              <p>
                {t('incompatible')}: {plugin.reasons.join('; ')}
              </p>
            ) : null}
            <button type="button" onClick={() => setDetail(plugin)}>
              {t('details')}
            </button>
          </article>
        ))}
      </div>
      {detail ? (
        <section className="marketplace-review" aria-label={t('details')}>
          <h3>
            {detail.name} · {detail.version}
          </h3>
          <p>
            {detail.publisher} · {detail.source_id} · {detail.format}
          </p>
          <p>
            {t('target')}: {detail.targets.join(', ')}
          </p>
          <p>
            {t('permissions')}: {detail.permissions.join(', ') || t('noPermissions')}
          </p>
          <h4>{t('readme')}</h4>
          <p className="marketplace-prose">{detail.readme ?? detail.description}</p>
          <h4>{t('changelog')}</h4>
          <p className="marketplace-prose">{detail.changelog}</p>
          <button type="button" onClick={() => setDetail(null)}>
            {t('close')}
          </button>
        </section>
      ) : null}
    </section>
  );
}
