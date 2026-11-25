import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { MarketDetailView } from './MarketDetailView';
import { MarketDialog } from './MarketDialog';
import { marketName, localize, Mark, MarketStatus, PackageIcon, platforms } from './marketIcons';
import { errorText, fileBase64, useMarketRequest } from './marketRequest';
import { marketText } from './pluginMarketText';
import {
  packageBase,
  packageScope,
  type Catalog,
  type Installation,
  type MarketDetail,
  type MarketView,
  type PluginMarketProps,
} from './pluginMarketTypes';
import './pluginMarket.css';

const PAGE_SIZE = 24;
type Review = {
  plugin_id: string;
  version: string;
  permissions: string[];
  digest: string;
  archive_base64: string;
  revision: number;
};
type Position = {
  viewport: Element | Window;
  top: number;
  card: HTMLButtonElement;
};
function positionOf(card: HTMLButtonElement): Position {
  let container = card.parentElement;
  while (container && container !== document.documentElement) {
    const { overflowY } = getComputedStyle(container);
    if (
      (overflowY === 'auto' || overflowY === 'scroll') &&
      container.scrollHeight > container.clientHeight
    )
      return { viewport: container, top: container.scrollTop, card };
    container = container.parentElement;
  }
  return { viewport: window, top: window.scrollY, card };
}

export function PluginMarket(props: PluginMarketProps) {
  return <ScopedMarket key={JSON.stringify([props.tenantId, props.projectId])} {...props} />;
}
function ScopedMarket(props: PluginMarketProps) {
  const { tenantId, projectId, pluginId, transport, locale } = props;
  const t = marketText(locale, projectId === null);
  const [query, setQuery] = useState('');
  const [view, setView] = useState<MarketView>('all');
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [versionChoice, setVersionChoice] = useState<{
    plugin: string;
    version: string;
  } | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [importError, setImportError] = useState('');
  const [importBusy, setImportBusy] = useState(false);
  const position = useRef<Position | null>(null);
  const lastId = useRef<string | null>(pluginId);
  const detailTitle = useRef<HTMLButtonElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const current = useRef(true);
  const importSeq = useRef(0);
  const scope = packageScope(tenantId, projectId);
  const base = packageBase(projectId);
  const [search, setSearch] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(query.trim());
      setOffset(0);
    }, 200);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    current.current = true;
    return () => {
      current.current = false;
    };
  }, []);
  const reload = () => setRevision((n) => n + 1);
  const catalog = useMarketRequest<Catalog>(
    transport,
    base + '/npm/catalog?' +
      new URLSearchParams({
        ...scope,
        q: search,
        view,
        offset: String(offset),
        limit: String(PAGE_SIZE),
      }),
    revision
  );
  const selectedVersion = versionChoice?.plugin === pluginId ? versionChoice.version : '';
  const detailPath = pluginId
    ? base + '/npm/detail?' +
      new URLSearchParams({
        ...scope,
        plugin_id: pluginId,
        ...(selectedVersion ? { version: selectedVersion } : {}),
      })
    : null;
  const detail = useMarketRequest<MarketDetail>(transport, detailPath, revision);
  useEffect(() => {
    setReview(null);
    setImportError('');
    setImportBusy(false);
    importSeq.current++;
  }, [pluginId]);
  useLayoutEffect(() => {
    if (lastId.current && !pluginId && position.current && catalog?.data) {
      position.current.viewport.scrollTo({
        top: position.current.top,
        behavior: 'instant',
      });
      const restored = document.getElementById(position.current.card.id);
      restored?.focus({ preventScroll: true });
      position.current = null;
    }
    if (pluginId && lastId.current !== pluginId) detailTitle.current?.focus();
    if (pluginId || catalog?.data) lastId.current = pluginId;
  }, [pluginId, catalog?.data]);

  const manage =
    props.canManage !== false &&
    (pluginId ? detail?.data?.can_manage : catalog?.data?.can_manage) === true;
  async function inspectFile(getFile: () => Promise<string | null>) {
    const seq = ++importSeq.current;
    const stillHere = () => current.current && seq === importSeq.current;
    setImportError('');
    setReview(null);
    setImportBusy(true);
    try {
      const raw = await getFile();
      if (!raw || !stillHere()) return;
      const candidate = await transport<Omit<Review, 'archive_base64' | 'revision'>>(
        base + '/inspect',
        {
          method: 'POST',
          body: { ...scope, archive_base64: raw },
        }
      );
      const state = await transport<Installation>(
        base +
          '/' +
          encodeURIComponent(candidate.plugin_id) +
          '?' +
          new URLSearchParams(scope),
        {}
      );
      if (stillHere())
        setReview({
          ...candidate,
          archive_base64: raw,
          revision: state.desired_revision,
        });
    } catch (cause) {
      if (stillHere()) setImportError(errorText(cause));
    } finally {
      if (stillHere()) setImportBusy(false);
    }
  }
  function openImport() {
    if (!manage || importBusy) return;
    if (props.importArchive) void inspectFile(props.importArchive);
    else file.current?.click();
  }
  async function installFile() {
    if (!review || !manage) return;
    const state = await transport<{ desired_revision: number }>(base + '/install', {
      method: 'POST',
      body: {
        ...scope,
        archive_base64: review.archive_base64,
        approved_permissions: review.permissions,
        expected_digest: review.digest,
        expected_revision: review.revision,
      },
    });
    const pluginPath = base + '/' + encodeURIComponent(review.plugin_id);
    await transport(pluginPath + '/enable', {
      method: 'POST',
      body: { ...scope, expected_revision: state.desired_revision },
    });
    const active = await transport<Installation>(pluginPath + '?' + new URLSearchParams(scope), {});
    if (active.actual_digest !== review.digest) throw new Error(active.failure || t.pending);
    if (current.current) {
      setReview(null);
      reload();
      props.onChanged?.();
      props.onSelect(review.plugin_id);
      props.onActivated?.(active);
    }
  }
  const result = catalog?.data;
  const entries = result?.items ?? [];
  const selected = detail?.data;
  const error = pluginId ? detail?.error : catalog?.error;
  return (
    <div className="pm-market" data-testid="plugin-market">
      <input
        hidden
        ref={file}
        type="file"
        accept=".mspkg"
        aria-label={t.pickFile}
        onChange={(event) => {
          const candidate = event.target.files?.[0];
          event.target.value = '';
          if (candidate)
            void inspectFile(async () => {
              if (candidate.size > 12 * 1024 * 1024) throw new Error(t.size);
              return fileBase64(candidate);
            });
        }}
      />
      {importError && (
        <p role="alert" className="pm-error">
          {importError}
        </p>
      )}
      {pluginId && (
        <button
          ref={detailTitle}
          type="button"
          className="pm-back"
          onClick={() => {
            setVersionChoice(null);
            props.onSelect(null);
          }}
        >
          <Mark name="back" size={16} />
          {t.back}
        </button>
      )}
      {error && (
        <div role="alert" className="pm-warning">
          <span>{error}</span>
          <button type="button" className="pm-btn" onClick={reload}>
            {t.retry}
          </button>
        </div>
      )}
      {pluginId ? (
        selected ? (
          <MarketDetailView
            {...props}
            key={pluginId}
            detail={selected}
            text={t}
            version={selectedVersion}
            onVersion={(v) => setVersionChoice({ plugin: pluginId, version: v })}
            reload={reload}
            importLocal={openImport}
          />
        ) : (
          !error && (
            <p role="status" className="pm-muted">
              {t.loadingDetail}
            </p>
          )
        )
      ) : (
        <>
          <div className="pm-heading">
            <h2>{t.title}</h2>
            <div className="pm-actions">
              <button
                type="button"
                className="pm-icon-btn"
                onClick={reload}
                aria-label={t.refresh}
                title={t.refresh}
              >
                <Mark name="refresh" />
              </button>
              {manage && (
                <details className="pm-menu">
                  <summary className="pm-btn">
                    <Mark name="more" size={16} />
                    {t.more}
                  </summary>
                  <div className="pm-menu-list">
                    <button type="button" disabled={importBusy} onClick={openImport}>
                      <Mark name="upload" size={16} />
                      {t.local}
                    </button>
                  </div>
                </details>
              )}
            </div>
          </div>
          <div className="pm-toolbar">
            <div className="pm-tabs" role="group" aria-label={t.navigation}>
              {(['all', 'installed', 'updates'] as const).map((key) => (
                <button
                  type="button"
                  key={key}
                  aria-pressed={view === key}
                  onClick={() => {
                    setView(key);
                    setOffset(0);
                  }}
                >
                  {t[key]}
                </button>
              ))}
            </div>
            <label className="pm-search">
              <Mark name="search" size={17} />
              <input
                aria-label={t.search}
                type="search"
                placeholder={t.search}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
          </div>
          {result?.source && (
            <div className="pm-source" title={result.source}>
              <Mark name="source" size={14} />
              <span>{t.source}</span>
              <code>{result.source}</code>
            </div>
          )}
          {result?.source_error && (
            <div className="pm-warning" role="status">
              <strong>{t.offline}</strong>
              <span>{result.source_error}</span>
              <button type="button" className="pm-btn" onClick={reload}>
                {t.retry}
              </button>
            </div>
          )}
          {result ? (
            entries.length ? (
              <div className="pm-cards">
                {entries.map((item) => {
                  const name = marketName(item, locale);
                  const desc = localize(item.description, locale);
                  return (
                    <button
                      id={'pm-card-' + item.plugin_id}
                      key={item.plugin_id}
                      className="pm-card"
                      type="button"
                      aria-label={name}
                      onClick={(e) => {
                        position.current = positionOf(e.currentTarget);
                        props.onSelect(item.plugin_id);
                      }}
                    >
                      <span className="pm-card-top">
                        <PackageIcon icon={item.icon} />
                        <MarketStatus item={item} text={t} />
                      </span>
                      <strong className="pm-card-title">{name}</strong>
                      {desc && <span className="pm-card-description">{desc}</span>}
                      <span className="pm-card-foot">
                        <span>
                          {platforms(item.targets, t).join(' · ') ||
                            item.package_name ||
                            t.localOnly}
                        </span>
                        <span className="pm-card-version">
                          {item.latest_version ?? item.installation?.installed_version}
                          <Mark name="arrow" size={15} />
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="pm-empty" role="status">
                {search
                  ? t.empty
                  : view === 'installed'
                    ? t.noneInstalled
                    : view === 'updates'
                      ? t.noUpdates
                      : t.emptyCatalog}
              </p>
            )
          ) : (
            !error && (
              <p role="status" className="pm-muted">
                {t.loading}
              </p>
            )
          )}
          {result && (offset > 0 || offset + entries.length < result.total) && (
            <div className="pm-pager">
              <button
                type="button"
                className="pm-btn"
                disabled={!offset}
                onClick={() => setOffset(Math.max(offset - PAGE_SIZE, 0))}
              >
                {t.prev}
              </button>
              <span>
                {offset + 1}–{offset + entries.length} {t.range} {result.total}
              </span>
              <button
                type="button"
                className="pm-btn"
                disabled={offset + entries.length >= result.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                {t.next}
              </button>
            </div>
          )}
        </>
      )}
      {review && manage && (
        <MarketDialog
          title={t.review}
          text={t}
          confirmLabel={t.permissionsApproved}
          onConfirm={installFile}
          onClose={() => {
            setReview(null);
            reload();
          }}
        >
          <p>
            <strong>{review.plugin_id}</strong> · {review.version}
            <span> · {t.scopeLabel} {projectId ?? tenantId}</span>
          </p>
          <h4>{t.permissions}</h4>
          {review.permissions.length ? (
            <ul className="pm-tokens">
              {review.permissions.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : (
            <p>{t.noPermissions}</p>
          )}
          <p className="pm-digest">{review.digest}</p>
        </MarketDialog>
      )}
    </div>
  );
}
