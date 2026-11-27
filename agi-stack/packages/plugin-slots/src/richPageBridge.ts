import type { PageScope, PageTarget, RichPage } from "./richPage";
import { pageSearch, splitPageLocation } from "./pageLocation";
import { PAGE_STORAGE_KEY, type PageStorage } from "./pageStorage";
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
  pointerCapture?(active: boolean): void;
  anchorSlot?(
    name: string,
    target: string,
    rect: number[] | null,
    search: string,
  ): void;
  reviewDevice?(signal: AbortSignal): Promise<void>;
  openPage?(pluginId: string, pageId: string, destination?: string): void;
  navigate(
    path: string,
    options?: { replace?: boolean; keepMounted?: boolean },
  ): void;
  /** Call the listener whenever the address of this page changes while it stays loaded. */
  contextChanged?(listener: () => void): () => void;
  /** What the page keeps between its loads, when the workbench document has a storage. */
  storage?: PageStorage;
  /** Open an address of the web for the page, until the page stops asking. */
  openUrl?(url: string, signal: AbortSignal): void | Promise<void>;
  /** Offer a file of the page to the user, under its name, until the page stops asking. */
  saveFile?(name: string, file: Blob, signal: AbortSignal): Promise<void>;
  /** Print an HTML document of the page to a PDF file offered to the user. */
  printPdf?(name: string, html: string, signal: AbortSignal): Promise<void>;
  voice?: {
    start(
      mode: "dictation" | "voice",
      conversation: string,
      signal: AbortSignal,
      emit: (event: unknown) => void,
    ): Promise<void>;
    mute(id: string, muted: boolean): void;
  };
  saveCsv?(text: string, signal: AbortSignal): Promise<void>;
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
  // A file a page hands over is text or base64, within these sizes.
  const FILE_NAME = /^[^\u0000-\u001f\u007f/\\]{1,128}$/;
  const FILE_TYPE =
    /^[A-Za-z0-9][A-Za-z0-9!#$&^_.+/-]*(?:; ?[A-Za-z0-9=_-]+)*$/;
  const FILE_TEXT_UNITS = 4 * 1024 * 1024;
  const FILE_BASE64_UNITS = 8 * 1024 * 1024;
  const FILE_HTML_UNITS = 2 * 1024 * 1024;

  function offeredName(name: unknown): string {
    if (typeof name !== "string" || !FILE_NAME.test(name))
      throw new Error("page_request_invalid");
    return name;
  }
  function reply(id: string, value: Record<string, unknown>) {
    if (!closed) port.postMessage({ id, ...value });
  }

  /** The file a page hands over, from the text or the bytes it named. */
  function offeredFile(content: unknown, mimeType: unknown): Blob {
    const type = mimeType ?? "text/plain;charset=utf-8";
    if (
      typeof content !== "object" ||
      !content ||
      Array.isArray(content) ||
      typeof type !== "string" ||
      type.length > 128 ||
      !FILE_TYPE.test(type)
    )
      throw new Error("page_request_invalid");
    const { text, bytes_base64 } = content as Record<string, unknown>;
    if (typeof bytes_base64 === "string") {
      if (
        bytes_base64.length > FILE_BASE64_UNITS ||
        bytes_base64.length % 4 !== 0
      )
        throw new Error("page_request_invalid");
      try {
        const binary = atob(bytes_base64);
        return new Blob(
          [Uint8Array.from(binary, (char) => char.charCodeAt(0))],
          { type },
        );
      } catch {
        throw new Error("page_request_invalid");
      }
    }
    if (typeof text !== "string" || text.length > FILE_TEXT_UNITS)
      throw new Error("page_request_invalid");
    return new Blob([text], { type });
  }
  // What the page reads as its context, from the address it is at now.
  const context = () => {
    const location = splitPageLocation(bridge.pathname);
    return {
      ...bridge.scope,
      ...location,
      search: pageSearch(location.search, false, page.query_params ?? []),
      target: bridge.target,
      platform: bridge.target,
      locale: bridge.locale,
      commands: page.commands,
      voiceAvailable: !!(
        page.voice_authorization &&
        bridge.voice &&
        bridge.scope.projectId
      ),
      deviceTools:
        bridge.target === "desktop-renderer" && bridge.device
          ? page.device_tools
          : [],
    };
  };

  // The page changes its storage as it runs, without waiting for an answer. A
  // change the workbench has no room for is dropped: the page reads it again
  // only at its next load.
  function store(data: Record<string, unknown>) {
    if (closed || !bridge.storage || bridge.isRetired?.()) return;
    const key = data.key;
    if (data.type === "storage.clear") bridge.storage.clear();
    else if (typeof key !== "string" || !PAGE_STORAGE_KEY.test(key)) return;
    else if (data.type === "storage.set")
      bridge.storage.write(
        key,
        typeof data.value === "string" ? data.value : "",
      );
    else bridge.storage.remove(key);
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
        value = context();
      } else if (message.method === "anchorSlot") {
        const { name, rect, search = "" } = message;
        if (
          typeof name !== "string" ||
          !page.anchored_slots ||
          !Object.hasOwn(page.anchored_slots, name) ||
          !bridge.anchorSlot ||
          typeof search !== "string" ||
          search.length > 2048 ||
          (search !== "" && !search.startsWith("?")) ||
          (rect !== null &&
            (!Array.isArray(rect) ||
              rect.length !== 4 ||
              !rect.every(
                (value) => typeof value === "number" && Number.isFinite(value),
              ) ||
              rect[2] < 0 ||
              rect[3] < 0))
        )
          throw new Error("page_slot_denied");
        bridge.anchorSlot(name, page.anchored_slots[name]!, rect, search);
      } else if (message.method === "voice" || message.method === "muteVoice") {
        if (
          !bridge.voice ||
          !page.voice_authorization ||
          !page.commands.includes(page.voice_authorization) ||
          !bridge.scope.projectId
        )
          throw new Error("page_capability_unavailable");
        if (message.method === "muteVoice") {
          if (
            typeof message.handle !== "string" ||
            typeof message.muted !== "boolean"
          )
            throw new Error("page_request_invalid");
          bridge.voice.mute(message.handle, message.muted);
        } else {
          if (
            (message.mode !== "dictation" && message.mode !== "voice") ||
            typeof message.conversation !== "string" ||
            !/^[A-Za-z0-9_-]{1,128}$/.test(message.conversation)
          )
            throw new Error("page_request_invalid");
          await bridge.voice.start(
            message.mode,
            message.conversation,
            controller.signal,
            (event) => {
              if (!controller.signal.aborted && !bridge.isRetired?.())
                reply(id, { type: "event", value: event });
            },
          );
        }
      } else if (message.method === "reviewDevice") {
        if (
          bridge.target !== "desktop-renderer" ||
          !bridge.device ||
          !page.device_tools.length ||
          !bridge.reviewDevice
        )
          throw new Error("page_capability_unavailable");
        await bridge.reviewDevice(controller.signal);
      } else if (message.method === "openPage") {
        const { pluginId, pageId, destination } = message;
        if (
          typeof pluginId !== "string" ||
          typeof pageId !== "string" ||
          pluginId.includes("/") ||
          pageId.includes("/") ||
          (destination !== undefined &&
            (typeof destination !== "string" ||
              destination.length > 8192 ||
              /[\\\u0000-\u001f]/.test(destination))) ||
          !page.page_links?.includes(pluginId + "/" + pageId) ||
          !bridge.openPage
        )
          throw new Error("page_navigation_denied");
        bridge.openPage(pluginId, pageId, destination);
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
        bridge.navigate(path, {
          replace: message.replace === true,
          keepMounted: message.keepMounted === true,
        });
      } else if (message.method === "openUrl") {
        let address: URL;
        try {
          address = new URL(message.url as string);
        } catch {
          throw new Error("page_navigation_denied");
        }
        // Only the open web. Another scheme, or an address that carries credentials, is not opened.
        if (
          typeof message.url !== "string" ||
          message.url.length > 8192 ||
          (address.protocol !== "https:" && address.protocol !== "http:") ||
          address.username ||
          address.password ||
          !bridge.openUrl
        )
          throw new Error("page_navigation_denied");
        await bridge.openUrl(address.href, controller.signal);
      } else if (message.method === "saveFile") {
        offeredName(message.name);
        const file = offeredFile(message.content, message.mimeType);
        if (!bridge.saveFile) throw new Error("page_export_unavailable");
        await bridge.saveFile(message.name as string, file, controller.signal);
      } else if (message.method === "printPdf") {
        const name = offeredName(message.name);
        if (
          typeof message.html !== "string" ||
          message.html.length > FILE_HTML_UNITS
        )
          throw new Error("page_request_invalid");
        if (!bridge.printPdf) throw new Error("page_export_unavailable");
        await bridge.printPdf(name, message.html, controller.signal);
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
        if (
          (message.method === "invoke" || message.method === "exportCsv") &&
          page.commands.includes(name)
        )
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
        if (message.method === "exportCsv") {
          if (controller.signal.aborted || bridge.isRetired?.())
            throw new Error("page_release_retired");
          if (
            !bridge.saveCsv ||
            !value ||
            typeof value !== "object" ||
            !("csv" in value) ||
            typeof value.csv !== "string"
          )
            throw new Error("page_export_unavailable");
          await bridge.saveCsv(value.csv, controller.signal);
          value = undefined;
        }
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
    if (
      event.data?.type === "page.pointerCapture" &&
      page.anchored_slots &&
      !bridge.isRetired?.()
    ) {
      if (typeof event.data.active === "boolean")
        bridge.pointerCapture?.(event.data.active);
    } else if (
      event.data?.type === "storage.set" ||
      event.data?.type === "storage.remove" ||
      event.data?.type === "storage.clear"
    ) {
      try {
        store(event.data as Record<string, unknown>);
      } catch {
        // Storage that cannot be written is lost at the next load, not reported.
      }
    } else if (event.data?.type === "page.loaded") bridge.status(true);
    else if (event.data?.type === "page.failed") bridge.status(false);
    else void handle(event.data);
  };
  port.postMessage({ type: "ready" });
  const stopContext = bridge.contextChanged?.(() => {
    if (!closed) port.postMessage({ type: "context", value: context() });
  });
  const root = typeof document !== "undefined" && document.documentElement;
  const viewport = root && root.ownerDocument.defaultView;
  const theme = () => {
    if (root)
      port.postMessage({
        type: "appearance",
        dark: root.dataset.theme === "dark" || root.classList.contains("dark"),
        highContrast: root.classList.contains("high-contrast"),
        hostViewportWidth: viewport ? viewport.innerWidth : undefined,
        lang: bridge.locale,
      });
  };
  // Every signed page mirrors the workbench theme and language, whatever surface it renders.
  const observer = root ? new MutationObserver(theme) : undefined;
  if (observer && root) {
    theme();
    if (viewport) viewport.addEventListener("resize", theme);
    observer.observe(root, {
      attributes: true,
      attributeFilter: ["class", "data-theme", "lang"],
    });
  }
  return () => {
    observer?.disconnect();
    if (observer && viewport) viewport.removeEventListener("resize", theme);
    closed = true;
    stopContext?.();
    for (const call of pending.values()) call.abort();
    pending.clear();
    port.close();
  };
}

/** Read the package command's bounded NDJSON stream until its terminal record. */
export { readPackageCommandStream } from "./packageCommandStream";
