import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  pageSearch,
  splitPageLocation,
} from "../../plugin-slots/src/pageLocation";
import { connectPage } from "../../plugin-slots/src/richPageBridge";
import {
  menuPath,
  routeRank,
  verifyPageDocument,
} from "../../plugin-slots/src/richPage";
import type {
  DevicePageCall,
  PackagePage,
  PageScope,
  PageTarget,
  RichPage,
} from "../../plugin-slots/src/richPage";
import { savePageExport } from "./savePageExport";
import { createPageVoiceAuthority } from "./pageVoiceAuthority";
import type { OpenVoiceSocket } from "../../plugin-slots/src/pageVoice";
import type { MarketplaceTransport } from "./client";

import { packageBase, packageScope } from "./pluginMarketTypes";
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
  navigate(
    path: string,
    options?: { replace?: boolean; pluginId?: string },
  ): void;
  management?: ReactNode;
  pluginId?: string;
  unmatched?: ReactNode;
  backToMarket?: ReactNode;
  managementLabel?: string;
  invokeDevice?: DevicePageCall;
  saveNativeExport?(blob: Blob): Promise<unknown>;
  reviewDevice?(pluginId: string, digest: string, signal: AbortSignal): Promise<void>;
  openVoiceSocket?: OpenVoiceSocket;
  streamCommand?: (
    path: string,
    body: Record<string, unknown>,
    signal: AbortSignal,
    onEvent: (value: unknown) => void,
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
  /** Offer the installed pages in a menu. A host with its own navigation turns this off. */
  pageMenu?: boolean;
  /** Show the selected and loaded release digests below the page. */
  diagnostics?: boolean;
}

type Item = { pluginId: string; digest: string; page: PackagePage };
type Selected = RichPackagePagesProps & {
  item: Item;
  catalog?: Item[];
  inSlot?: boolean;
  openPage(pluginId: string, pageId: string, destination?: string): void;
};

function PackageFrame(
  props: Selected & { retired: boolean; onPending(count: number): void },
) {
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
  const deviceReview = useRef<AbortController | null>(null);
  useEffect(() => {
    if (props.retired) deviceReview.current?.abort();
    return () => deviceReview.current?.abort();
  }, [props.retired, props.pathname]);
  const stopVoice = useRef<(() => void) | undefined>(undefined);
  useEffect(() => {
    if (props.retired) stopVoice.current?.();
    return () => stopVoice.current?.();
  }, [props.retired, props.pathname]);
  const dispose = useRef<(() => void) | undefined>(undefined);
  const [loaded, setLoaded] = useState<{ page: RichPage; html: string } | null>(
    null,
  );
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [sourceCapturing, setSourceCapturing] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [anchors, setAnchors] = useState<Record<string, { target: string; rect: number[]; search: string }>>({});
  useEffect(() => {
    if (ready && !props.retired && !error) {
      current.current.onStatus?.({ pluginId, digest, pageId: id, ready: true });
    }
  }, [props.retired, ready, error, pluginId, digest, id]);
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({
      ...packageScope(tenantId, projectId),
      expected_digest: digest,
      target,
      page_id: id,
    });
    void transport<RichPage>(
      packageBase(projectId) +
        "/" +
        encodeURIComponent(pluginId) +
        "/ui?" +
        query,
      {
        signal: controller.signal,
      },
    )
      .then(async (page) => ({
        page,
        html: await verifyPageDocument(page, target, digest, id),
      }))
      .then((value) => {
        if (!controller.signal.aborted) setLoaded(value);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        const reason =
          cause instanceof Error ? cause.message : "page_load_failed";
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
  }, [transport, target, tenantId, projectId, pluginId, digest, id, attempt]);

  function connect() {
    dispose.current?.();
    if (!loaded || !frame.current?.contentWindow) return;
    const { page, html } = loaded;
    const host = new MessageChannel();
    let close: (() => void) | undefined;
    let alive = true;
    const watchdog = setTimeout(() => {
      if (!alive) return;
      setError("page_runtime_unavailable");
      current.current.onStatus?.({
        pluginId,
        digest,
        pageId: id,
        ready: false,
        error: "page_runtime_unavailable",
      });
      dispose.current?.();
    }, 15000);
    dispose.current = () => {
      alive = false;
      clearTimeout(watchdog);
      stopVoice.current?.();
      close?.();
      host.port1.close();
    };
    host.port1.onmessage = (event) => {
      if (
        !alive ||
        close ||
        event.data !== "memstack.page.connect" ||
        event.ports.length !== 1
      )
        return;
      const path =
        packageBase(projectId) +
        "/" +
        encodeURIComponent(pluginId) +
        "/commands";
      const voice = createPageVoiceAuthority({
        tenantId, projectId, pluginId, locale: current.current.locale || navigator.language,
        open: current.current.openVoiceSocket,
        authorize: (conversation, signal) => transport(path, {
          method: "POST", signal, body: {
            ...packageScope(tenantId, projectId), expected_digest: digest,
            command_id: page.voice_authorization, payload: { conversation_id: conversation },
          },
        }),
      });
      stopVoice.current = voice.stop;
      close = connectPage(event.ports[0]!, page, {
        ...(current.current.openVoiceSocket ? { voice } : {}),
        scope: { tenantId, projectId },
        target,
        get pathname() {
          return current.current.pathname;
        },
        locale:
          current.current.locale ||
          document.documentElement.lang ||
          navigator.language,
        isRetired: () => current.current.retired,
        pendingChanged: (count) => current.current.onPending(count),
        status(loaded) {
          clearTimeout(watchdog);
          if (loaded) {
            setReady(true);
          } else {
            setError("page_execution_failed");
            current.current.onStatus?.({
              pluginId,
              digest,
              pageId: id,
              ready: false,
              error: "page_execution_failed",
            });
            dispose.current?.();
          }
        },
        saveCsv: (text, signal) => savePageExport(text, signal, current.current.locale || navigator.language, current.current.saveNativeExport),
        pointerCapture: setSourceCapturing,
        anchorSlot(name, targetPage, rect, search) {
          if (current.current.inSlot) throw new Error("page_slot_denied");
          const query = pageSearch(search, true);
          setAnchors(previous => {
            const next = { ...previous };
            if (rect) next[name] = { target: targetPage, rect, search: query };
            else delete next[name];
            return next;
          });
        },
        reviewDevice: signal => {
          if (current.current.retired || !current.current.reviewDevice) throw new Error("page_capability_unavailable");
          if (deviceReview.current) throw new Error("device_review_unavailable");
          const controller = new AbortController();
          deviceReview.current = controller;
          return current.current.reviewDevice(pluginId, digest, AbortSignal.any([signal, controller.signal]))
            .finally(() => { deviceReview.current = null; });
        },
        openPage: (pluginId, pageId, destination) => current.current.openPage(pluginId, pageId, destination),
        navigate: (newPath, options) =>
          current.current.navigate(newPath, options),
        invoke(name, payload, signal, progress) {
          const body = {
            ...packageScope(tenantId, projectId),
            expected_digest: digest,
            command_id: name,
            ...(payload === undefined ? {} : { payload }),
          };
          if (progress) {
            if (!current.current.streamCommand)
              return Promise.reject(new Error("package_stream_unavailable"));
            return current.current.streamCommand(
              path + "?stream=true",
              body,
              signal,
              progress,
            );
          }
          return transport(path, { method: "POST", body, signal });
        },
        device: (name, payload, signal) =>
          current.current.invokeDevice?.({
            pluginId,
            digest,
            tool: name,
            payload: payload ?? {},
            signal,
          }) ?? Promise.reject(new Error("device_grant_unavailable")),
      });
      host.port1.close();
    };
    frame.current.contentWindow.postMessage(
      { type: "memstack.page.open", title: page.title, document: html },
      "*",
      [host.port2],
    );
  }
  if (error) return <div role="alert">{error}
    {props.inSlot && <button type="button" onClick={() => {
      setError(""); setLoaded(null); setReady(false); setAttempt(previous => previous + 1);
    }}>{props.locale?.startsWith("zh") ? "重试" : "Retry"}</button>}
  </div>;
  if (!loaded) return null;
  const frameUrl = new URL(
    target === "web"
      ? "/memstack-package-frame.html"
      : "./memstack-package-frame.html",
    location.href,
  ).href;
  const surface = (
    <iframe
      ref={frame}
      title={loaded.page.title}
      src={frameUrl}
      sandbox="allow-scripts allow-forms"
      onLoad={connect}
      data-release-digest={digest}
      data-page-ready={ready}
      style={{
        display: "block",
        width: "100%",
        ...(props.inSlot ? { height: "100%" } : {}),
        minHeight: props.inSlot ? 0 : loaded.page.workbench ? "var(--workbench-frame-height, calc(100dvh - 6rem))" : "65vh",
        border: 0,
      }}
    />
  );
  if (!loaded.page.anchored_slots || props.inSlot) return surface;
  return <div style={{ position: "relative", overflow: "hidden" }}>
    {surface}
    {!props.retired && Object.entries(anchors).map(([name, anchor]) => {
      const targetItem = props.catalog?.find(candidate =>
        candidate.pluginId + "/" + candidate.page.id === anchor.target &&
        candidate.page.contributes_to === pluginId + "/" + name);
      const [left, top, width, height] = anchor.rect;
      return <section key={name} aria-label={targetItem?.page.title || name}
        style={{ position: "absolute", left, top, width, height, overflow: "hidden", pointerEvents: sourceCapturing ? "none" : "auto" }}>
        {targetItem ? <PageRelease key={JSON.stringify([anchor.target, anchor.search])}
          {...props} inSlot item={targetItem}
          pathname={"/" + pageSearch(anchor.search, false, targetItem.page.query_params ?? [])}
          onStatus={() => {}} />
          : <div role="status">
            {props.locale?.startsWith("zh") ? "当前项目未安装所需插件" : "The required package is unavailable in this project"}
            {" · "}{anchor.target}
            {props.backToMarket}
          </div>}
      </section>;
    })}
  </div>;
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
  const zh = locale.startsWith("zh");
  return (
    <details>
      <summary>{zh ? "页面诊断" : "Page diagnostics"}</summary>
      <dl style={{ overflowWrap: "anywhere" }}>
        <dt>{zh ? "运行端" : "Renderer"}</dt>
        <dd>{target}</dd>
        <dt>{zh ? "插件页面" : "Package page"}</dt>
        <dd>
          {plugin} / {page}
        </dd>
        <dt>{zh ? "项目选择的摘要" : "Selected digest"}</dt>
        <dd>
          <code>{selected}</code>
        </dd>
        <dt>{zh ? "实际装载的摘要" : "Loaded digest"}</dt>
        <dd>
          <code>{actual ?? (zh ? "尚未装载" : "Not loaded")}</code>
        </dd>
        {error && (
          <>
            <dt>{zh ? "装载错误" : "Load error"}</dt>
            <dd>{error}</dd>
          </>
        )}
      </dl>
    </details>
  );
}

/** Preserve the last verified frame while a new release is loading in the same scope. */
/** A guest replacing its own filters already holds the new view and keyboard focus. */
function RoutedPageRelease(props: Selected) {
  const { pathname, search, hash } = splitPageLocation(props.pathname);
  const address = pathname + pageSearch(search) + hash;
  const requested = useRef<string | null>(null);
  const [view, setView] = useState({ address, generation: 0 });
  if (view.address !== address) {
    const acknowledged = requested.current === address;
    requested.current = null;
    setView({ address, generation: view.generation + (acknowledged ? 0 : 1) });
  }
  return (
    <PageRelease
      key={view.generation}
      {...props}
      navigate={(path, options) => {
        const next = splitPageLocation(path);
        if (options?.replace && next.pathname === pathname)
          requested.current =
            next.pathname + pageSearch(next.search) + next.hash;
        props.navigate(path, options);
      }}
    />
  );
}

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
      (previous) =>
        previous.digest !== item.digest && previous.digest !== visible,
    ),
    ...(preparing ? [active, item] : [item]),
  ];

  return (
    <>
      {releases.map((release) => (
        <div key={release.digest} hidden={release.digest !== visible} style={props.inSlot ? { height: "100%" } : undefined}>
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
                    ? previous.filter(
                        (entry) => entry.digest !== release.digest,
                      )
                    : previous,
                );
              }
            }}
            onStatus={(status) => {
              props.onStatus?.(status);
              if (status.digest !== item.digest) return;
              if (status.ready) {
                if (
                  active &&
                  active.digest !== item.digest &&
                  pending.current.has(active.digest)
                ) {
                  setDraining((previous) => [
                    ...previous.filter(
                      (entry) => entry.digest !== active.digest,
                    ),
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
      {preparing && failure?.digest === item.digest && (
        <p role="alert" style={props.inSlot ? { position: "absolute", insetInline: 0, top: 0, background: "Canvas", color: "CanvasText" } : undefined}>
          {failure.reason}
        </p>
      )}
      {!props.inSlot && props.diagnostics && <PageDiagnostics
        target={props.target}
        locale={
          props.locale || document.documentElement.lang || navigator.language
        }
        plugin={item.pluginId}
        page={item.page.id}
        selected={item.digest}
        actual={active?.digest}
        error={failure?.digest === item.digest ? failure.reason : undefined}
      />}
    </>
  );
}

export function RichPackagePages(props: RichPackagePagesProps) {
  const { tenantId, projectId } = props.scope;
  return <ScopedPackagePages key={JSON.stringify([tenantId, projectId, props.target])} {...props} />;
}

function ScopedPackagePages(props: RichPackagePagesProps) {
  const { scope, target, transport, revision = 0 } = props;
  const { pathname } = splitPageLocation(props.pathname);
  const [items, setItems] = useState<Item[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const { tenantId, projectId } = scope;
  useEffect(() => {
    let live = true;
    let controller: AbortController | null = null;
    const refresh = async () => {
      if (controller || !live) return;
      controller = new AbortController();
      try {
        const query = new URLSearchParams({
          ...packageScope(tenantId, projectId),
        });
        const data = await transport<{ items: Release[] }>(
          packageBase(projectId) + "/?" + query,
          {
            signal: controller.signal,
          },
        );
        if (!live) return;
        setItems(
          data.items.flatMap((release) =>
            release.actual_digest &&
            (release.status === "enabled" || release.status === "failed")
              ? (release.pages ?? [])
                  .filter((page) => page.targets.includes(target))
                  .map((page) => ({
                    pluginId: release.plugin_id,
                    digest: release.actual_digest!,
                    page,
                  }))
              : [],
          ),
        );
        setLoaded(true);
        setError("");
      } catch (cause) {
        if (live) {
          setItems([]);
          setError(
            cause instanceof Error ? cause.message : "page_catalog_failed",
          );
        }
      } finally {
        controller = null;
      }
    };
    void refresh();
    const poll = setInterval(() => {
      if (document.visibilityState !== "hidden") void refresh();
    }, 5000);
    window.addEventListener("focus", refresh);
    return () => {
      live = false;
      controller?.abort();
      clearInterval(poll);
      window.removeEventListener("focus", refresh);
    };
  }, [transport, tenantId, projectId, target, revision]);

  let bestRank: string | null = null;
  let selected: Item | undefined;
  const navigable = props.pluginId
    ? items.filter((i) => i.pluginId === props.pluginId)
    : items;
  for (const item of navigable) {
    for (const route of item.page.routes) {
      const rank = routeRank(route, pathname, scope);
      if (rank !== null && (bestRank === null || rank > bestRank)) {
        selected = item;
        bestRank = rank;
      }
    }
  }
  function openPage(pluginId: string, pageId: string, destination?: string) {
    const targetPage = items.find((item) => item.pluginId === pluginId && item.page.id === pageId);
    if (!targetPage) throw new Error("page_destination_unavailable");
    if (destination !== undefined) {
      const {pathname, search, hash} = splitPageLocation(destination);
      if (!targetPage.page.routes.some((route) => routeRank(route, pathname, scope) !== null))
        throw new Error("page_navigation_denied");
      const query = pageSearch(search, true, targetPage.page.query_params ?? []);
      props.navigate(pathname + query + hash, {pluginId});
      return;
    }
    const path = targetPage.page.routes.map((route) => menuPath(route, scope)).find(Boolean);
    if (!path) throw new Error("page_destination_unavailable");
    props.navigate(path, { pluginId });
  }
  const links = navigable.flatMap((item) => {
    const path = item.page.routes
      .map((route) => menuPath(route, scope))
      .find(Boolean);
    return path ? [{ item, path }] : [];
  });
  const home = (links.find(({ item }) => item.page.home) ?? links[0])?.path;
  const atHome = ["/", "/index.html", ""].includes(pathname);
  const atManagement = [
    "/plugins",
    "/plugins/",
    "/project-packages.html",
  ].includes(pathname);
  const zh = (
    props.locale ||
    document.documentElement.lang ||
    navigator.language
  ).startsWith("zh");
  const managementLabel =
    props.managementLabel ?? (zh ? "管理插件" : "Manage plugins");
  useEffect(() => {
    if (atHome && home) props.navigate(home, { replace: true });
  }, [atHome, home, props.navigate]);

  if (props.unmatched !== undefined && !selected) {
    if (!loaded && !error) return null;
    if (error && props.pluginId)
      return (
        <>
          <p role="alert">{error}</p>
          {props.unmatched}
        </>
      );
    return props.unmatched;
  }
  const slots = new Set(
    selected?.page.slots?.map((name) => selected.pluginId + "/" + name),
  );
  const embedded = items.filter(
    (i) => i.page.contributes_to && slots.has(i.page.contributes_to),
  );
  const workbenchReturn = selected?.page.workbench && props.target === "web" && props.management == null
    ? props.backToMarket : null;
  const pageMenu = props.pageMenu !== false && (!selected?.page.workbench || props.management != null);
  return (
    <div
      className="project-business-pages"
      data-testid="project-business-pages"
    >
      {(pageMenu || (props.backToMarket && !workbenchReturn) || props.management != null) && <nav
        className="project-business-navigation"
        aria-label={zh ? "项目导航" : "Project navigation"}
      >
        {props.backToMarket}
        {pageMenu && (
            <label>
              {zh ? "业务页面" : "Applications"}
              <select
                value={links.find(({ item }) => item === selected)?.path ?? ""}
                onChange={(event) => props.navigate(event.target.value)}
              >
                <option value="" disabled>
                  {selected?.page.title ?? (zh ? "选择页面" : "Choose a page")}
                </option>
                {links.map(({ item, path }) => (
                  <option key={item.pluginId + "/" + item.page.id} value={path}>
                    {item.page.title}
                  </option>
                ))}
              </select>
            </label>
          )}
        {props.management != null && (
          <button
            type="button"
            aria-current={atManagement ? "page" : undefined}
            onClick={() => props.navigate("/plugins")}
          >
            {managementLabel}
          </button>
        )}
      </nav>}
      {error && <p role="alert">{error}</p>}
      {atManagement ? (
        props.management
      ) : selected ? (
        <RoutedPageRelease
          key={JSON.stringify([
            tenantId,
            projectId,
            selected.pluginId,
            selected.page.id,
            props.locale,
            pathname,
          ])}
          {...props}
          openPage={openPage}
          item={selected}
          catalog={items}
        />
      ) : (
        !error &&
        (!loaded || (atHome && home) ? (
          <p role="status">{zh ? "正在加载…" : "Loading…"}</p>
        ) : (
          <p role="status">
            {atHome
              ? zh
                ? "此项目尚无可打开的业务页面。"
                : "This project has no available application pages."
              : zh
                ? "此页面在当前项目中不可用。"
                : "This page is unavailable in this project."}
          </p>
        ))
      )}
      {embedded.map((item) => (
        <section
          key={JSON.stringify([
            tenantId,
            projectId,
            selected?.pluginId,
            pathname,
            item.pluginId,
            item.page.id,
            props.locale,
          ])}
          aria-label={item.page.title}
        >
          <RoutedPageRelease
            {...props}
            item={item}
            openPage={openPage}
            onStatus={() => {}}
            navigate={(path, options) =>
              props.navigate(path, { ...options, pluginId: item.pluginId })
            }
          />
        </section>
      ))}
      {workbenchReturn && (
        <nav className="project-business-navigation" aria-label={managementLabel}>
          {workbenchReturn}
        </nav>
      )}
    </div>
  );
}
