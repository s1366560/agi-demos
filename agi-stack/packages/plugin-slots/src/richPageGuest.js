// Installed only inside the opaque-origin package document.
(() => {
  const channel = new MessageChannel();
  const calls = new Map();
  const contexts = new Set();
  let ready = false;
  const queued = [];
  function send(message) {
    if (ready) channel.port1.postMessage(message);
    else queued.push(message);
  }
  // In Electron a captured pointer can cross into another renderer process.
  // Ask the shell to pass hits through its sibling panes until capture ends.
  let captured = null;
  function reportCapture(event) {
    if (captured !== null) return;
    if (event.composedPath().some(node => node.hasPointerCapture?.(event.pointerId))) {
      captured = event.pointerId;
      send({ type: "page.pointerCapture", active: true });
    }
  }
  function releaseCapture(event) {
    if (captured === null || (event.pointerId !== undefined && captured !== event.pointerId)) return;
    captured = null;
    send({ type: "page.pointerCapture", active: false });
  }
  addEventListener("pointerdown", reportCapture);
  addEventListener("gotpointercapture", reportCapture);
  for (const event of ["pointerup", "pointercancel", "lostpointercapture", "blur"])
    addEventListener(event, releaseCapture, true);
  let failed = false;
  function pageError() {
    if (!failed) send({ type: "page.failed" });
    failed = true;
  }
  addEventListener("error", pageError);
  addEventListener("unhandledrejection", pageError);
  // This document has no tab of its own: a link of the page to the web is opened by the workbench.
  addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return;
    const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!link || link.target !== "_blank") return;
    let address;
    try {
      address = new URL(link.href);
    } catch {
      return;
    }
    if (address.protocol !== "https:" && address.protocol !== "http:") return;
    event.preventDefault();
    request("openUrl", { url: address.href }).catch(() => {});
  });
  addEventListener(
    "load",
    () => {
      if (!failed) send({ type: "page.loaded" });
    },
    { once: true },
  );
  function request(method, fields = {}, options = {}) {
    if (options.signal?.aborted)
      return Promise.reject(new DOMException("Aborted", "AbortError"));
    if (calls.size >= 16)
      return Promise.reject(new Error("page_request_limit"));
    const id = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      const abort = () => {
        calls.delete(id);
        send({ id, method: "cancel" });
        reject(new DOMException("Aborted", "AbortError"));
      };
      options.signal?.addEventListener("abort", abort, { once: true });
      calls.set(id, {
        resolve,
        reject,
        event: options.onEvent,
        cleanup: () => options.signal?.removeEventListener("abort", abort),
      });
      send({ id, method, ...fields });
    });
  }
  channel.port1.onmessage = ({ data }) => {
    if (data?.type === "ready" && !ready) {
      ready = true;
      for (const message of queued.splice(0))
        channel.port1.postMessage(message);
      return;
    }
    if (data?.type === "appearance") {
      const root = document.documentElement;
      root.classList.toggle("dark", data.dark);
      root.classList.toggle("high-contrast", data.highContrast);
      root.dataset.theme = data.dark ? "dark" : "light";
      root.style.colorScheme = root.dataset.theme;
      root.lang = data.lang;
      // Workbench controls share the shell's responsive breakpoints even in a narrow iframe.
      if (Number.isFinite(data.hostViewportWidth)) {
        const breakpoints = { sm: 640, md: 768, lg: 1024, xl: 1280, "2xl": 1536 };
        root.dataset.hostBreakpoints = Object.entries(breakpoints)
          .filter(([, width]) => data.hostViewportWidth >= width)
          .map(([name]) => name)
          .join(" ");
      }
      return;
    }
    if (data?.type === "context") {
      // A listener that fails is reported as any other error of the page, once this message is done.
      try {
        for (const listener of contexts) listener(data.value);
      } catch (error) {
        setTimeout(() => {
          throw error;
        });
      }
      return;
    }
    const call = calls.get(data?.id);
    if (!call) return;
    if (data.type === "event") {
      call.event?.(data.value);
      return;
    }
    calls.delete(data.id);
    call.cleanup();
    if (data.type === "result") call.resolve(data.value);
    else call.reject(new Error(data.error || "page_request_failed"));
  };
  const resources = JSON.parse(document.getElementById("memstack-resources")?.textContent || "{}");
  // A page keeps small state in the storage of the workbench, as its own localStorage.
  // The document carries what was stored when the page loaded, so reading answers at
  // once; each change is passed on. The bounds are those of the bridge of the workbench.
  const PAGE_STORAGE_KEY = /^[^\u0000-\u001f\u007f]{1,256}$/;
  const PAGE_STORAGE_TOTAL = 4194304;
  const stored = new Map(
    Object.entries(JSON.parse(document.getElementById("memstack-storage")?.textContent || "{}") || {})
  );
  function area(values, kept) {
    return {
      get length() {
        return values.size;
      },
      key: (index) => [...values.keys()][index] ?? null,
      getItem: (key) => (values.has(String(key)) ? values.get(String(key)) : null),
      setItem(key, value) {
        const name = String(key), text = String(value);
        const others = [...values].reduce((sum, [other, held]) => sum + (other === name ? 0 : held.length), 0);
        if (others + text.length > PAGE_STORAGE_TOTAL)
          throw new DOMException("The page has no room for more.", "QuotaExceededError");
        values.set(name, text);
        // A name the workbench does not keep lasts as long as this document.
        if (kept && PAGE_STORAGE_KEY.test(name)) send({ type: "storage.set", key: name, value: text });
      },
      removeItem(key) {
        const name = String(key);
        if (!values.delete(name)) return;
        if (kept) send({ type: "storage.remove", key: name });
      },
      clear() {
        if (!values.size) return;
        values.clear();
        if (kept) send({ type: "storage.clear" });
      },
    };
  }
  // This document is of an origin the browser does not know, so its storage is this one.
  const persist = area(stored, true);
  for (const [name, object] of [["localStorage", persist], ["sessionStorage", area(new Map(), false)]])
    Object.defineProperty(window, name, { configurable: true, enumerable: true, get: () => object });
  const scope = () => request("scope");
  Object.defineProperty(window, "memstack", {
    value: Object.freeze({
      scope,
      getContext: scope,
      reviewDevice: () => request("reviewDevice"),
      voice: (mode, conversation, options) => request("voice", { mode, conversation }, options),
      muteVoice: (handle, muted) => request("muteVoice", { handle, muted }),
      anchorSlot(name, element, search = "", onError) {
        let active = true, scheduled = 0, previous = "";
        const update = () => {
          scheduled = 0;
          if (!active) return;
          const { left, top, width, height } = element.getBoundingClientRect();
          const rect = [left, top, width, height];
          const signature = rect.join(",");
          if (signature === previous) return;
          previous = signature;
          request("anchorSlot", { name, search, rect }).catch(error => {
            if (active) onError?.(error.message);
          });
        };
        const schedule = () => { if (!scheduled) scheduled = requestAnimationFrame(update); };
        const observer = new ResizeObserver(schedule);
        observer.observe(element);
        addEventListener("scroll", schedule, true);
        addEventListener("resize", schedule);
        update();
        return () => {
          active = false;
          observer.disconnect();
          cancelAnimationFrame(scheduled);
          removeEventListener("scroll", schedule, true);
          removeEventListener("resize", schedule);
          request("anchorSlot", { name, rect: null }).catch(() => {});
        };
      },
      assetUrl(path) {
        if (!Object.hasOwn(resources, path)) throw new Error("page_resource_unavailable");
        return resources[path];
      },
      openPage: (pluginId, pageId, destination) => request("openPage", { pluginId, pageId, destination }),
      openUrl: (url) => request("openUrl", { url }),
      navigate: (path, options) =>
        request("navigate", {
          path,
          replace: options?.replace === true,
          keepMounted: options?.keepMounted === true,
        }),
      onContextChange(listener) {
        contexts.add(listener);
        return () => contexts.delete(listener);
      },
      invoke: (name, payload, options = {}) =>
        request(
          "invoke",
          {
            name,
            ...(payload === undefined ? {} : { payload }),
            stream: typeof options.onEvent === "function",
          },
          options,
        ),
      exportCsv: (name, payload, options = {}) => request("exportCsv", { name, payload }, options),
      saveFile: (name, content, mimeType, options = {}) =>
        request("saveFile", { name, content, mimeType }, options),
      printPdf: (name, html, options = {}) => request("printPdf", { name, html }, options),
      device: (name, payload = {}, options = {}) =>
        request("device", { name, payload }, options),
    }),
  });
  parent.postMessage("memstack.page.guest", "*", [channel.port2]);
})();
