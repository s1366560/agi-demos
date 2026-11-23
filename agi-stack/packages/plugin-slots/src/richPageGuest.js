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
  const scope = () => request("scope");
  Object.defineProperty(window, "memstack", {
    value: Object.freeze({
      scope,
      getContext: scope,
      navigate: (path) => request("navigate", { path }),
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
      device: (name, payload = {}, options = {}) =>
        request("device", { name, payload }, options),
    }),
  });
  parent.postMessage("memstack.page.guest", "*", [channel.port2]);
})();
