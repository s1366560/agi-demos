import type { PageScope, PageTarget, RichPage } from "./richPage";
import { pageSearch, splitPageLocation } from "./pageLocation";
import { routeRank } from "./richPage";

type Operation = (
  name: string,
  payload: Record<string, unknown> | undefined,
  signal: AbortSignal,
  progress?: (value: unknown) => void,
) => Promise<unknown>;
export interface PageBridge {
  readonly scope: PageScope;
  readonly target: PageTarget;
  readonly pathname: string;
  readonly locale: string;
  status(loaded: boolean): void;
  isRetired?(): boolean;
  pendingChanged?(count: number): void;
  navigate(path: string, options?: { replace?: boolean }): void;
  invoke: Operation;
  device?: Operation | undefined;
}

export function connectPage(
  port: MessagePort,
  page: RichPage,
  bridge: PageBridge,
) {
  const pending = new Map<string, AbortController>();
  let closed = false;
  function reply(id: string, value: Record<string, unknown>) {
    if (!closed) port.postMessage({ id, ...value });
  }

  async function handle(data: unknown) {
    if (
      !data ||
      typeof data !== "object" ||
      !("id" in data) ||
      typeof data.id !== "string" ||
      !/^[a-zA-Z0-9-]{1,64}$/.test(data.id)
    )
      return;
    const message = data as Record<string, unknown>;
    const id = data.id;
    if (message.method === "cancel") {
      pending.get(id)?.abort();
      return;
    }
    if (bridge.isRetired?.()) {
      reply(id, { type: "error", error: "page_release_retired" });
      return;
    }
    if (pending.has(id)) return;
    if (pending.size >= 16) {
      reply(id, { type: "error", error: "page_request_limit" });
      return;
    }
    const controller = new AbortController();
    pending.set(id, controller);
    bridge.pendingChanged?.(pending.size);
    try {
      let value: unknown;
      if (message.method === "scope") {
        const location = splitPageLocation(bridge.pathname);
        value = {
          ...bridge.scope,
          ...location,
          search: pageSearch(location.search, false, page.query_params ?? []),
          target: bridge.target,
          platform: bridge.target,
          locale: bridge.locale,
          commands: page.commands,
          deviceTools: page.device_tools,
        };
      } else if (message.method === "navigate") {
        const path = message.path;
        if (
          typeof path !== "string" ||
          path.length > 8192 ||
          /[\\\u0000-\u001f]/.test(path)
        )
          throw new Error("page_navigation_denied");
        const location = splitPageLocation(path);
        pageSearch(location.search, true);
        if (
          !(page.navigation_routes ?? page.routes).some(
            (route) =>
              routeRank(route, location.pathname, bridge.scope) !== null,
          )
        )
          throw new Error("page_navigation_denied");
        bridge.navigate(path, { replace: message.replace === true });
      } else {
        const name = message.name,
          payload = message.payload;
        if (
          typeof name !== "string" ||
          (payload !== undefined &&
            (!payload ||
              typeof payload !== "object" ||
              Array.isArray(payload) ||
              new TextEncoder().encode(JSON.stringify(payload)).length > 65536))
        )
          throw new Error("page_request_invalid");
        let operation: Operation;
        if (message.method === "invoke" && page.commands.includes(name))
          operation = bridge.invoke;
        else if (
          message.method === "device" &&
          page.device_tools.includes(name) &&
          bridge.target === "desktop-renderer" &&
          bridge.device
        )
          operation = bridge.device;
        else throw new Error("page_capability_unavailable");
        const progress =
          message.stream === true
            ? (event: unknown) => {
                if (!controller.signal.aborted)
                  reply(id, { type: "event", value: event });
              }
            : undefined;
        value = await operation(
          name,
          payload as Record<string, unknown> | undefined,
          controller.signal,
          progress,
        );
      }
      if (!controller.signal.aborted) reply(id, { type: "result", value });
    } catch (error) {
      if (!controller.signal.aborted)
        reply(id, {
          type: "error",
          error: error instanceof Error ? error.message : "page_request_failed",
        });
    } finally {
      pending.delete(id);
      if (!closed) bridge.pendingChanged?.(pending.size);
    }
  }

  port.onmessage = (event) => {
    if (event.data?.type === "page.loaded") bridge.status(true);
    else if (event.data?.type === "page.failed") bridge.status(false);
    else void handle(event.data);
  };
  port.postMessage({ type: "ready" });
  return () => {
    closed = true;
    for (const call of pending.values()) call.abort();
    pending.clear();
    port.close();
  };
}

/** Read the package command's bounded NDJSON stream until its terminal record. */
export { readPackageCommandStream } from "./packageCommandStream";
