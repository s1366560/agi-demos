// Installed only inside the opaque-origin package document.
(() => {
  const channel = new MessageChannel();
  const calls = new Map();
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
      navigate: (path, options) => request("navigate", { path, replace: options?.replace === true }),
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
      device: (name, payload = {}, options = {}) =>
        request("device", { name, payload }, options),
    }),
  });
  parent.postMessage("memstack.page.guest", "*", [channel.port2]);
})();
