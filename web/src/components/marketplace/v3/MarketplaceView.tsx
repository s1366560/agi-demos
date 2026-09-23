import { MarketplaceOAuth } from './MarketplaceOAuth';
import { MarketplaceCache } from './MarketplaceCache';
import { useEffect, useRef, useState } from 'react';
import {
  filterPlugins,
  type MarketplaceClient,
  type MarketplaceInstallation,
  type MarketplacePreflight,
  type MarketplaceSource,
  type PluginDescriptor,
} from '../../../../../agi-stack/packages/plugin-marketplace-ui/src/client';
import type { MarketplaceMessage } from '../../../../../agi-stack/packages/plugin-marketplace-ui/src/messages';
import './MarketplaceView.css';
import { MarketplaceCredentials } from './MarketplaceCredentials';

type Props = {
  client: MarketplaceClient;
  t: (key: MarketplaceMessage) => string;
  scope: string;
  canManage: boolean;
  local: boolean;
  onInstallSignedV2?: (() => void) | undefined;
};
export function MarketplaceView({ client, t, scope, canManage, local, onInstallSignedV2 }: Props) {
  const [tab, setTab] = useState<'discover' | 'installed' | 'sources'>('discover');
  const [catalog, setCatalog] = useState<PluginDescriptor[]>([]);
  const [sources, setSources] = useState<MarketplaceSource[]>([]);
  const [installed, setInstalled] = useState<MarketplaceInstallation[]>([]);
  const [filters, setFilters] = useState({
    query: '',
    category: '',
    capability: '',
    target: '',
    source: '',
  });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [notice, setNotice] = useState(false);
  const [detail, setDetail] = useState<PluginDescriptor | null>(null);
  const [review, setReview] = useState<{
    preflight: MarketplacePreflight;
    installation?: MarketplaceInstallation;
    key: string;
  } | null>(null);
  const [approved, setApproved] = useState(false);
  const [configure, setConfigure] = useState<MarketplaceInstallation | null>(null);
  const [removal, setRemoval] = useState<MarketplaceInstallation | null>(null);
  const [source, setSource] = useState({
    name: '',
    location: '',
    kind: 'https' as MarketplaceSource['kind'],
    trusted: false,
  });
  const reviewPanel = useRef<HTMLElement | null>(null);
  const detailPanel = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (review) reviewPanel.current?.focus();
  }, [review]);
  useEffect(() => {
    if (detail) detailPanel.current?.focus();
  }, [detail]);
  const generation = useRef(0);
  const working = useRef(false);
  const reading = useRef<AbortController | null>(null);
  const [sourceErrors, setSourceErrors] = useState<Array<{ source_id: string; error: string }>>([]);
  async function refresh() {
    const token = generation.current;
    reading.current?.abort();
    const controller = new AbortController();
    reading.current = controller;
    const results = await Promise.all([
      client.catalog(controller.signal),
      client.sources(controller.signal),
      client.installations(controller.signal),
    ]);
    if (token !== generation.current || controller.signal.aborted) return;
    setCatalog(results[0].items);
    setSourceErrors(results[0].errors ?? []);
    setSources(results[1].items);
    setInstalled(results[2].items);
    setLoaded(true);
  }
  useEffect(() => {
    generation.current += 1;
    const token = generation.current;
    working.current = false;
    setBusy(false);
    setNotice(false);
    setCatalog([]);
    setSources([]);
    setInstalled([]);
    setSourceErrors([]);
    setLoaded(false);
    setReview(null);
    setDetail(null);
    setRemoval(null);
    setConfigure(null);
    setApproved(false);
    setError('');
    setFilters({ query: '', category: '', capability: '', target: '', source: '' });
    setSource({ name: '', location: '', kind: 'https', trusted: false });
    void refresh().catch((caught: unknown) => {
      if (token === generation.current && !reading.current?.signal.aborted)
        setError(caught instanceof Error ? caught.message : String(caught));
    });
    return () => {
      reading.current?.abort();
      generation.current += 1;
    };
  }, [client]);
  async function perform<T>(work: () => Promise<T>, success?: (value: T) => void, changed = true) {
    if (working.current) return;
    const token = generation.current;
    working.current = true;
    setBusy(true);
    setError('');
    setNotice(false);
    try {
      const value = await work();
      if (token !== generation.current) return;
      success?.(value);
      if (changed) await refresh();
      if (token === generation.current) setNotice(changed);
    } catch (caught) {
      if (token === generation.current)
        setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (token === generation.current) {
        working.current = false;
        setBusy(false);
      }
    }
  }
  function inspect(plugin: PluginDescriptor, installation?: MarketplaceInstallation) {
    setApproved(false);
    void perform(
      () => client.preflight(plugin),
      (preflight) => {
        setReview({
          preflight,
          ...(installation ? { installation } : {}),
          key: crypto.randomUUID(),
        });
      },
      false
    );
  }
  const visible = filterPlugins(catalog, filters);
  const filterOptions = {
    category: [...new Set(catalog.map((item) => item.category))],
    capability: [...new Set(catalog.flatMap((item) => item.capabilities))],
    target: [...new Set(catalog.flatMap((item) => item.targets))],
    source: sources.map((item) => item.id),
  };
  return (
    <section className="marketplace-v3" aria-busy={busy}>
      <header>
        <div>
          <h2>{t('title')}</h2>
          <p>{t('description')}</p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void perform(refresh, undefined, false)}
        >
          {t('refresh')}
        </button>
      </header>
      <p className="marketplace-scope">
        {t('scope')}: <code>{scope}</code>
      </p>
      <nav aria-label={t('title')}>
        {(['discover', 'installed', 'sources'] as const).map((name) => (
          <button key={name} type="button" aria-pressed={tab === name} onClick={() => setTab(name)}>
            {t(name)}
          </button>
        ))}
      </nav>
      {error ? (
        <p role="alert" className="marketplace-error">
          {error}
        </p>
      ) : null}
      {sourceErrors.map((item) => (
        <p role="alert" key={item.source_id}>
          {sources.find((source) => source.id === item.source_id)?.name ?? item.source_id}:{' '}
          {item.error}
        </p>
      ))}
      {busy || (!loaded && !error) ? <p role="status">{t(busy ? 'busy' : 'loading')}</p> : null}
      {notice && !busy ? <p role="status">{t('actionConfirmed')}</p> : null}
      {tab === 'discover' ? (
        <>
          <div className="marketplace-filters">
            <label>
              {t('search')}
              <input
                type="search"
                value={filters.query}
                onChange={(event) => setFilters({ ...filters, query: event.target.value })}
              />
            </label>
            {(Object.keys(filterOptions) as Array<keyof typeof filterOptions>).map((key) => (
              <label key={key}>
                {t(key)}
                <select
                  value={filters[key]}
                  onChange={(event) => setFilters({ ...filters, [key]: event.target.value })}
                >
                  <option value="">{t('all')}</option>
                  {filterOptions[key].map((value) => (
                    <option key={value} value={value}>
                      {key === 'source'
                        ? (sources.find((item) => item.id === value)?.name ?? value)
                        : value}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          {loaded && !visible.length ? <p>{t('empty')}</p> : null}
          <div className="marketplace-grid">
            {visible.map((plugin) => (
              <article key={`${plugin.source_id}:${plugin.id}:${plugin.version}`}>
                <div className="marketplace-card-title">
                  <h3>{plugin.name}</h3>
                  <span>{plugin.version}</span>
                </div>
                <p>{plugin.description}</p>
                <p className="marketplace-muted">
                  {plugin.publisher} ·{' '}
                  {sources.find((item) => item.id === plugin.source_id)?.name ?? plugin.source_id}
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
                <div className="marketplace-actions">
                  <button type="button" onClick={() => setDetail(plugin)}>
                    {t('details')}
                  </button>
                  <button
                    type="button"
                    disabled={
                      !canManage ||
                      busy ||
                      !plugin.compatible ||
                      (plugin.format === 'v2' && !onInstallSignedV2)
                    }
                    onClick={() =>
                      plugin.format === 'v2' ? onInstallSignedV2?.() : inspect(plugin)
                    }
                  >
                    {t(plugin.format === 'v2' ? 'signedInstaller' : 'install')}
                  </button>
                </div>
              </article>
            ))}
          </div>
        </>
      ) : null}
      {tab === 'installed' ? (
        <div className="marketplace-grid">
          {loaded && !installed.filter((item) => item.status !== 'uninstalled').length ? (
            <p>{t('noInstalled')}</p>
          ) : null}
          {installed
            .filter((item) => item.status !== 'uninstalled')
            .map((item) => (
              <article key={`${item.source_id}:${item.id}`}>
                <h3>
                  {item.name} · {item.version}
                </h3>
                <p role="status">{t(item.status)}</p>
                {item.error ? <p role="alert">{item.error}</p> : null}
                {item.install_strategy !== 'signed-v2'
                  ? item.oauth_services?.map((service) => (
                      <MarketplaceOAuth
                        key={service.name}
                        client={client}
                        installationId={item.id}
                        service={service}
                        canManage={canManage}
                        t={t}
                      />
                    ))
                  : null}
                <div className="marketplace-actions">
                  {item.install_strategy === 'signed-v2' ? (
                    <button
                      type="button"
                      disabled={busy || !canManage || !onInstallSignedV2}
                      onClick={onInstallSignedV2}
                    >
                      {t('signedInstaller')}
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        disabled={busy || !canManage}
                        onClick={() =>
                          void perform(() =>
                            client.action(item, item.status === 'enabled' ? 'disable' : 'enable')
                          )
                        }
                      >
                        {t(item.status === 'enabled' ? 'disable' : 'enable')}
                      </button>
                      <button
                        type="button"
                        disabled={busy || !canManage || item.required_credentials?.length === 0}
                        onClick={() => {
                          setConfigure(item);
                        }}
                      >
                        {t('configure')}
                      </button>
                      <button
                        type="button"
                        disabled={busy || !canManage}
                        onClick={() => void perform(() => client.action(item, 'verify'))}
                      >
                        {t('verify')}
                      </button>
                      <button
                        type="button"
                        disabled={
                          busy ||
                          !canManage ||
                          !catalog.some(
                            (plugin) =>
                              plugin.id === item.plugin_id && plugin.source_id === item.source_id
                          )
                        }
                        onClick={() => {
                          const plugin = catalog.find(
                            (entry) =>
                              entry.id === item.plugin_id && entry.source_id === item.source_id
                          );
                          if (plugin) inspect(plugin, item);
                        }}
                      >
                        {t('update')}
                      </button>
                      <button
                        type="button"
                        disabled={busy || !canManage}
                        onClick={() => setRemoval(item)}
                      >
                        {t('uninstall')}
                      </button>
                    </>
                  )}
                </div>
              </article>
            ))}
        </div>
      ) : null}
      {tab === 'sources' ? (
        <>
          <MarketplaceCache client={client} canManage={canManage} t={t} />
          {loaded && !sources.length ? <p>{t('noSources')}</p> : null}
          <div className="marketplace-grid">
            {sources.map((item) => (
              <article key={item.id}>
                <h3>{item.name}</h3>
                <p>{item.kind}</p>
                <code>{item.location}</code>
                <div>
                  <button
                    type="button"
                    disabled={busy || !canManage}
                    onClick={() => void perform(() => client.removeSource(item.id))}
                  >
                    {t('remove')}
                  </button>
                </div>
              </article>
            ))}
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void perform(
                () => client.addSource(source),
                () => setSource({ name: '', location: '', kind: 'https', trusted: false })
              );
            }}
          >
            <h3>{t('addSource')}</h3>
            <fieldset disabled={busy || !canManage}>
              <label>
                {t('name')}
                <input
                  required
                  value={source.name}
                  onChange={(event) => setSource({ ...source, name: event.target.value })}
                />
              </label>
              <label>
                {t('kind')}
                <select
                  value={source.kind}
                  onChange={(event) =>
                    setSource({ ...source, kind: event.target.value as MarketplaceSource['kind'] })
                  }
                >
                  {(
                    ['https', 'git', ...(local ? ['local'] : [])] as MarketplaceSource['kind'][]
                  ).map((kind) => (
                    <option key={kind} value={kind}>
                      {t(kind)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t('location')}
                <input
                  required
                  type={source.kind === 'https' ? 'url' : 'text'}
                  value={source.location}
                  onChange={(event) => setSource({ ...source, location: event.target.value })}
                />
              </label>
              <label className="marketplace-check">
                <input
                  type="checkbox"
                  checked={source.trusted}
                  onChange={(event) => setSource({ ...source, trusted: event.target.checked })}
                />
                {t('trust')}
              </label>
              <button type="submit" disabled={!source.trusted}>
                {t('addSource')}
              </button>
            </fieldset>
          </form>
        </>
      ) : null}
      {detail ? (
        <section
          ref={detailPanel}
          tabIndex={-1}
          className="marketplace-review"
          aria-label={t('details')}
        >
          <h3>{detail.name}</h3>
          <p>{detail.description}</p>
          <dl>
            {(['publisher', 'version', 'format', 'category'] as const).map((key) => (
              <div key={key}>
                <dt>{t(key)}</dt>
                <dd>{detail[key]}</dd>
              </div>
            ))}
          </dl>
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
      {review ? (
        <section
          ref={reviewPanel}
          tabIndex={-1}
          className="marketplace-review"
          aria-label={t('permissions')}
        >
          <h3>
            {review.preflight.plugin.name} · {review.preflight.plugin.version}
          </h3>
          <p>
            {t('scope')}: {scope}
          </p>
          <p>
            {t('source')}:{' '}
            {sources.find((source) => source.id === review.preflight.plugin.source_id)?.name ??
              review.preflight.plugin.source_id}
          </p>
          <code>{review.preflight.digest}</code>
          <h4>{t('permissions')}</h4>
          {review.preflight.permissions.length ? (
            <ul>
              {review.preflight.permissions.map((permission) => (
                <li key={permission}>{permission}</li>
              ))}
            </ul>
          ) : (
            <p>{t('noPermissions')}</p>
          )}
          {!review.preflight.compatible ? (
            <p role="alert">{review.preflight.reasons.join('; ')}</p>
          ) : null}
          <label className="marketplace-check">
            <input
              type="checkbox"
              checked={approved}
              onChange={(event) => setApproved(event.target.checked)}
            />
            {t('approve')}
          </label>
          <div className="marketplace-actions">
            <button
              type="button"
              disabled={busy || !canManage || !approved || !review.preflight.compatible}
              onClick={() =>
                void perform(
                  () =>
                    review.installation
                      ? client.action(
                          review.installation,
                          'update',
                          {
                            preflight_id: review.preflight.id,
                            approved_permissions: review.preflight.permissions,
                          },
                          review.key
                        )
                      : client.install(review.preflight, review.key),
                  () => {
                    setReview(null);
                    setTab('installed');
                  }
                )
              }
            >
              {t(review.installation ? 'confirmUpdate' : 'confirmInstall')}
            </button>
            <button type="button" disabled={busy} onClick={() => setReview(null)}>
              {t('cancel')}
            </button>
          </div>
        </section>
      ) : null}
      {configure ? (
        <MarketplaceCredentials
          key={configure.id}
          installation={configure}
          t={t}
          busy={busy}
          canManage={canManage}
          onSave={(credentials) =>
            perform(
              () => client.action(configure, 'configure', { credentials }),
              () => setConfigure(null)
            )
          }
          onCancel={() => setConfigure(null)}
        />
      ) : null}
      {removal ? (
        <section className="marketplace-review">
          <h3>{removal.name}</h3>
          <p>{t('confirmRemoval')}</p>
          <button
            type="button"
            disabled={busy || !canManage}
            onClick={() =>
              void perform(
                () => client.action(removal, 'uninstall'),
                () => setRemoval(null)
              )
            }
          >
            {t('confirm')}
          </button>
          <button type="button" disabled={busy} onClick={() => setRemoval(null)}>
            {t('cancel')}
          </button>
        </section>
      ) : null}
    </section>
  );
}
