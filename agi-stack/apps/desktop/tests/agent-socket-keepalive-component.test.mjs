import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const webRequire = createRequire(
  new URL("../../../../web/package.json", import.meta.url),
);
const { Window } = await import(
  pathToFileURL(webRequire.resolve("happy-dom")).href
);
const window = new Window({ url: "http://localhost/" });
for (const key of [
  "window",
  "document",
  "navigator",
  "HTMLElement",
  "Element",
  "Node",
]) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value: key === "window" ? window : window[key],
  });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require("react");
const { act } = React;
const { createRoot } = require("react-dom/client");
const {
  useAgentSocket,
} = require("/tmp/agistack-desktop-test-dist/apps/desktop/src/hooks/useAgentSocket.js");
const config = {
  mode: "cloud",
  apiBaseUrl: "https://cloud.memstack.test",
  apiKey: "fixture-only",
  localApiToken: "",
  tenantId: "tenant",
  projectId: "project",
  workspaceId: "workspace",
};
const acquireLease = () => ({
  kind: "generation",
  digest: "fixture-digest",
  release: async () => {},
});
function Probe() {
  useAgentSocket(config, true, 1, null, acquireLease);
  return null;
}

test("native agent hook delegates keepalive to main even when renderer receives no events", async (t) => {
  const calls = [];
  let listener;
  window.__MEMSTACK_DESKTOP__ = {
    runtime: "electron",
    core: {
      invoke: async (command, args) => {
        calls.push({ command, args });
      },
    },
    events: {
      onCloudSocketEvent: (callback) => {
        listener = callback;
        return () => {};
      },
    },
  };
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(React.createElement(Probe)));
    const socketId = calls.find((call) => call.command === "cloud_socket_open")
      .args.socketId;
    t.mock.timers.enable({ apis: ["setInterval", "Date"], now: 0 });
    await act(async () =>
      listener({ socketId, type: "open", protocol: "memstack.auth" }),
    );
    calls.length = 0;
    await act(async () => t.mock.timers.tick(120_000));
    assert.deepEqual(
      calls,
      [],
      "renderer must not send duplicate heartbeats or close a healthy main-owned socket",
    );
  } finally {
    await act(async () => root.unmount());
    container.remove();
    delete window.__MEMSTACK_DESKTOP__;
  }
  assert.equal(
    calls.at(-1).command,
    "cloud_socket_close",
    "scope disposal must still close the socket",
  );
});

test("raw cloud WebSocket retains renderer heartbeat and closes a silent server", async (t) => {
  let socket;
  const previousWebSocket = globalThis.WebSocket;
  globalThis.WebSocket = class {
    readyState = 1;
    sent = [];
    closed = [];
    constructor() {
      socket = this;
    }
    send(data) {
      this.sent.push(JSON.parse(data));
    }
    close(code = 1000, reason = "") {
      this.closed.push({ code, reason });
      this.readyState = 3;
    }
  };
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(React.createElement(Probe)));
    t.mock.timers.enable({ apis: ["setInterval", "Date"], now: 0 });
    await act(async () => socket.onopen());
    socket.sent.length = 0;
    await act(async () => t.mock.timers.tick(20_000));
    assert.deepEqual(socket.sent, [{ type: "heartbeat" }]);
    await act(async () => t.mock.timers.tick(50_000));
    assert.ok(
      socket.closed.some(
        (event) =>
          event.code === 4000 &&
          event.reason === "Agent WebSocket heartbeat timeout",
      ),
    );
  } finally {
    await act(async () => root.unmount());
    container.remove();
    globalThis.WebSocket = previousWebSocket;
  }
});
