import { useEffect, useRef, useState, type ReactNode } from 'react';

import { connectPage } from '../../plugin-slots/src/richPageBridge';
import { menuPath, routeRank, verifyPageDocument } from '../../plugin-slots/src/richPage';
import type {
  DevicePageCall,
  PackagePage,
  PageScope,
  PageTarget,
  RichPage,
} from '../../plugin-slots/src/richPage';
import type { MarketplaceTransport } from './client';

const BASE = '/api/v1/platform-plugins/v2/optional-business';
type Release = {
  plugin_id: string;
  actual_digest: string | null;
  status: string;
  pages?: PackagePage[];
};
export interface RichPackagePagesProps {
  scope: PageScope;
  target: PageTarget;
  transport: MarketplaceTransport;
  pathname: string;
  navigate(path: string, options?: { replace?: boolean }): void;
  management?: ReactNode;
  managementLabel?: string;
  invokeDevice?: DevicePageCall;
  streamCommand?: (
    path: string,
    body: Record<string, unknown>,
    signal: AbortSignal,
    onEvent: (value: unknown) => void
  ) => Promise<unknown>;
  revision?: number;
  locale?: string;
  onStatus?: (status: {
    pluginId: string;
    digest: string;
    pageId: string;
    ready: boolean;
    error?: string;
  }) => void;
}

type Item = { pluginId: string; digest: string; page: PackagePage };
type Selected = RichPackagePagesProps & { item: Item };

function PackageFrame(props: Selected & { retired: boolean; onPending(count: number): void }) {
  const {
    transport,
    target,
    scope: { tenantId, projectId },
    item: {
      pluginId,
      digest,
      page: { id },
    },
  } = props;
  const current = useRef(props);
  current.current = props;
  const frame = useRef<HTMLIFrameElement>(null);
  const dispose = useRef<(() => void) | undefined>(undefined);
  const [loaded, setLoaded] = useState<{ page: RichPage; html: string } | null>(null);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (ready && !props.retired && !error) {
      current.current.onStatus?.({ pluginId, digest, pageId: id, ready: true });
    }
  }, [props.retired, ready, error, pluginId, digest, id]);
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({
      tenant_id: tenantId,
      project_id: projectId,
      expected_digest: digest,
      target,
      page_id: id,
    });
    void transport<RichPage>(BASE + '/' + encodeURIComponent(pluginId) + '/ui?' + query, {
      signal: controller.signal,
    })
      .then(async (page) => ({
        page,
        html: await verifyPageDocument(page, target, digest, id),
      }))
      .then((value) => {
        if (!controller.signal.aborted) setLoaded(value);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        const reason = cause instanceof Error ? cause.message : 'page_load_failed';
        setError(reason);
        current.current.onStatus?.({
          pluginId,
          digest,
          pageId: id,
          ready: false,
          error: reason,
        });
      });
    return () => {
      controller.abort();
      dispose.current?.();
    };
  }, [transport, target, tenantId, projectId, pluginId, digest, id]);

  function connect() {
    dispose.current?.();
    if (!loaded || !frame.current?.contentWindow) return;
    const { page, html } = loaded;
    const host = new MessageChannel();
    let close: (() => void) | undefined;
    let alive = true;
    const watchdog = setTimeout(() => {
      if (!alive) return;
      setError('page_runtime_unavailable');
      current.current.onStatus?.({
        pluginId,
        digest,
        pageId: id,
        ready: false,
        error: 'page_runtime_unavailable',
      });
      dispose.current?.();
    }, 15000);
    dispose.current = () => {
      alive = false;
      clearTimeout(watchdog);
      close?.();
      host.port1.close();
    };
    host.port1.onmessage = (event) => {
      if (!alive || close || event.data !== 'memstack.page.connect' || event.ports.length !== 1)
        return;
      const path = BASE + '/' + encodeURIComponent(pluginId) + '/commands';
      close = connectPage(event.ports[0]!, page, {
        scope: { tenantId, projectId },
        target,
        pathname: current.current.pathname,
        locale: current.current.locale || document.documentElement.lang || navigator.language,
        isRetired: () => current.current.retired,
        pendingChanged: (count) => current.current.onPending(count),
        status(loaded) {
          clearTimeout(watchdog);
          if (loaded) {
            setReady(true);
          } else {
            setError('page_execution_failed');
            current.current.onStatus?.({
              pluginId,
              digest,
              pageId: id,
              ready: false,
              error: 'page_execution_failed',
            });
            dispose.current?.();
          }
        },
        navigate: (newPath) => current.current.navigate(newPath),
        invoke(name, payload, signal, progress) {
          const body = {
            tenant_id: tenantId,
            project_id: projectId,
            expected_digest: digest,
            command_id: name,
            ...(payload === undefined ? {} : { payload }),
          };
          if (progress) {
            if (!current.current.streamCommand)
              return Promise.reject(new Error('package_stream_unavailable'));
            return current.current.streamCommand(path + '?stream=true', body, signal, progress);
          }
          return transport(path, { method: 'POST', body, signal });
        },
        device: (name, payload, signal) =>
          current.current.invokeDevice?.({
            pluginId,
            digest,
            tool: name,
            payload: payload ?? {},
            signal,
          }) ?? Promise.reject(new Error('device_grant_unavailable')),
      });
      host.port1.close();
    };
    frame.current.contentWindow.postMessage(
      { type: 'memstack.page.open', title: page.title, document: html },
      '*',
      [host.port2]
    );
  }
  if (error) return <p role="alert">{error}</p>;
  if (!loaded) return null;
  const frameUrl = new URL(
    target === 'web' ? '/memstack-package-frame.html' : './memstack-package-frame.html',
    location.href
  ).href;
  return (
    <iframe
      ref={frame}
      title={loaded.page.title}
      src={frameUrl}
      sandbox="allow-scripts"
      onLoad={connect}
      data-release-digest={digest}
      data-page-ready={ready}
      style={{ display: 'block', width: '100%', minHeight: '65vh', border: 0 }}
    />
  );
}

function PageDiagnostics({
  target,
  locale,
  plugin,
  page,
  selected,
  actual,
  error,
}: {
  target: PageTarget;
  locale: string;
  plugin: string;
  page: string;
  selected: string;
  actual?: string | undefined;
  error?: string | undefined;
}) {
  const zh = locale.startsWith('zh');
  return (
    <details>
      <summary>{zh ? '页面诊断' : 'Page diagnostics'}</summary>
      <dl style={{ overflowWrap: 'anywhere' }}>
        <dt>{zh ? '运行端' : 'Renderer'}</dt>
        <dd>{target}</dd>
        <dt>{zh ? '插件页面' : 'Package page'}</dt>
        <dd>
          {plugin} / {page}
        </dd>
        <dt>{zh ? '项目选择的摘要' : 'Selected digest'}</dt>
        <dd>
          <code>{selected}</code>
        </dd>
        <dt>{zh ? '实际装载的摘要' : 'Loaded digest'}</dt>
        <dd>
          <code>{actual ?? (zh ? '尚未装载' : 'Not loaded')}</code>
        </dd>
        {error && (
          <>
            <dt>{zh ? '装载错误' : 'Load error'}</dt>
            <dd>{error}</dd>
          </>
        )}
      </dl>
    </details>
  );
}

/** Preserve the last verified frame while a new release is loading in the same scope. */
function PageRelease(props: Selected) {
  const { item } = props;
  const [active, setActive] = useState<Item | null>(null);
  const [failure, setFailure] = useState<{
    digest: string;
    reason: string;
  } | null>(null);
  const preparing = active && active.digest !== item.digest;
  const [draining, setDraining] = useState<Item[]>([]);
  const pending = useRef(new Map<string, number>());
  const visible = active?.digest ?? item.digest;
  const releases = [
    ...draining.filter(
      (previous) => previous.digest !== item.digest && previous.digest !== visible
    ),
    ...(preparing ? [active, item] : [item]),
  ];

  return (
    <>
      {releases.map((release) => (
        <div key={release.digest} hidden={release.digest !== visible}>
          <PackageFrame
            {...props}
            item={release}
            retired={release.digest !== item.digest}
            onPending={(count) => {
              if (count) pending.current.set(release.digest, count);
              else {
                pending.current.delete(release.digest);
                setDraining((previous) =>
                  previous.some((entry) => entry.digest === release.digest)
                    ? previous.filter((entry) => entry.digest !== release.digest)
                    : previous
                );
              }
            }}
            onStatus={(status) => {
              props.onStatus?.(status);
              if (status.digest !== item.digest) return;
              if (status.ready) {
                if (active && active.digest !== item.digest && pending.current.has(active.digest)) {
                  setDraining((previous) => [
                    ...previous.filter((entry) => entry.digest !== active.digest),
                    active,
                  ]);
                }
                setActive(release);
                setFailure(null);
              } else if (status.error) {
                if (active?.digest === status.digest) setActive(null);
                setFailure({ digest: status.digest, reason: status.error });
              }
            }}
          />
        </div>
      ))}
      {preparing && failure?.digest === item.digest && <p role="alert">{failure.reason}</p>}
      <PageDiagnostics
        target={props.target}
        locale={props.locale || document.documentElement.lang || navigator.language}
        plugin={item.pluginId}
        page={item.page.id}
        selected={item.digest}
        actual={active?.digest}
        error={failure?.digest === item.digest ? failure.reason : undefined}
      />
    </>
  );
}

export function RichPackagePages(props: RichPackagePagesProps) {
  const { scope, target, transport, pathname, revision = 0 } = props;
  const [items, setItems] = useState<Item[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const { tenantId, projectId } = scope;
  useEffect(() => {
    let live = true;
    let controller: AbortController | null = null;
    const refresh = async () => {
      if (controller || !live) return;
      controller = new AbortController();
      try {
        const query = new URLSearchParams({
          tenant_id: tenantId,
          project_id: projectId,
        });
        const data = await transport<{ items: Release[] }>(BASE + '/?' + query, {
          signal: controller.signal,
        });
        if (!live) return;
        setItems(
          data.items.flatMap((release) =>
            release.actual_digest && (release.status === 'enabled' || release.status === 'failed')
              ? (release.pages ?? [])
                  .filter((page) => page.targets.includes(target))
                  .map((page) => ({
                    pluginId: release.plugin_id,
                    digest: release.actual_digest!,
                    page,
                  }))
              : []
          )
        );
        setLoaded(true);
        setError('');
      } catch (cause) {
        if (live) {
          setItems([]);
          setError(cause instanceof Error ? cause.message : 'page_catalog_failed');
        }
      } finally {
        controller = null;
      }
    };
    void refresh();
    const poll = setInterval(() => {
      if (document.visibilityState !== 'hidden') void refresh();
    }, 5000);
    window.addEventListener('focus', refresh);
    return () => {
      live = false;
      controller?.abort();
      clearInterval(poll);
      window.removeEventListener('focus', refresh);
    };
  }, [transport, tenantId, projectId, target, revision]);

  let bestRank: string | null = null;
  let selected: Item | undefined;
  for (const item of items) {
    for (const route of item.page.routes) {
      const rank = routeRank(route, pathname, scope);
      if (rank !== null && (bestRank === null || rank > bestRank)) {
        selected = item;
        bestRank = rank;
      }
    }
  }
  const links = items.flatMap((item) => {
    const path = item.page.routes.map((route) => menuPath(route, scope)).find(Boolean);
    return path ? [{ item, path }] : [];
  });
  const home = (links.find(({ item }) => item.page.home) ?? links[0])?.path;
  const atHome = ['/', '/index.html', ''].includes(pathname);
  const atManagement = ['/plugins', '/plugins/', '/project-packages.html'].includes(pathname);
  const zh = (props.locale || document.documentElement.lang || navigator.language).startsWith('zh');
  const managementLabel = props.managementLabel ?? (zh ? '管理插件' : 'Manage plugins');
  useEffect(() => {
    if (atHome && home) props.navigate(home, { replace: true });
  }, [atHome, home, props.navigate]);

  return (
    <div className="project-business-pages" data-testid="project-business-pages">
      <nav
        className="project-business-navigation"
        aria-label={zh ? '项目导航' : 'Project navigation'}
      >
        {links.length > 0 && (
          <label>
            {zh ? '业务页面' : 'Applications'}
            <select
              value={links.find(({ item }) => item === selected)?.path ?? ''}
              onChange={(event) => props.navigate(event.target.value)}
            >
              <option value="" disabled>
                {selected?.page.title ?? (zh ? '选择页面' : 'Choose a page')}
              </option>
              {links.map(({ item, path }) => (
                <option key={item.pluginId + '/' + item.page.id} value={path}>
                  {item.page.title}
                </option>
              ))}
            </select>
          </label>
        )}
        {props.management != null && (
          <button
            type="button"
            aria-current={atManagement ? 'page' : undefined}
            onClick={() => props.navigate('/plugins')}
          >
            {managementLabel}
          </button>
        )}
      </nav>
      {error && <p role="alert">{error}</p>}
      {atManagement ? (
        props.management
      ) : selected ? (
        <PageRelease
          key={JSON.stringify([tenantId, projectId, selected.pluginId, selected.page.id, pathname])}
          {...props}
          item={selected}
        />
      ) : (
        !error &&
        (!loaded || (atHome && home) ? (
          <p role="status">{zh ? '正在加载…' : 'Loading…'}</p>
        ) : (
          <p role="status">
            {atHome
              ? zh
                ? '此项目尚无可打开的业务页面。'
                : 'This project has no available application pages.'
              : zh
                ? '此页面在当前项目中不可用。'
                : 'This page is unavailable in this project.'}
          </p>
        ))
      )}
    </div>
  );
}
