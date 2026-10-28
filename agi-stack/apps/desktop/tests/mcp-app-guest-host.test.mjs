import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const entryUrl = 'http://127.0.0.1:5173/mcp-app.html';
const protocolUrl = new URL('../src/features/chat/mcpAppGuestProtocol.ts', import.meta.url);
const hostUrl = new URL('../electron/main/mcpAppGuestHost.ts', import.meta.url);
const uuid = (index) => `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`;
const nonce = (index) => `mcpapp-${uuid(index)}`;
const config = () => ({
  toolName: 'guest-test',
  html: '<p>App instance</p>',
  sandbox: {
    url: 'http://127.0.0.1:43210/sandbox.html',
    permissions: 'allow-scripts allow-same-origin',
  },
});

function compile(url, load = require) {
  const module = { exports: {} };
  const code = ts.transpileModule(readFileSync(url, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  new Function('require', 'module', 'exports', code)(load, module, module.exports);
  return module.exports;
}

const protocol = compile(protocolUrl);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function harness({ load } = {}) {
  const views = [];
  const sessions = [];
  const retirements = [];
  const installedProtocols = [];
  let nextId = 100;
  class Contents extends EventEmitter {
    constructor() {
      super();
      this.id = nextId++;
      this.mainFrame = {
        url: entryUrl,
        frameTreeNodeId: this.id,
        frames: [
          {
            frameTreeNodeId: this.id + 1000,
            frames: [{ frameTreeNodeId: this.id + 2000, frames: [] }],
          },
        ],
      };
      this.destroyed = false;
      this.sent = [];
      this.loaded = [];
      this.zoom = 1;
    }
    isDestroyed() {
      return this.destroyed;
    }
    setWindowOpenHandler(handler) {
      this.windowOpenHandler = handler;
    }
    getZoomFactor() {
      return this.zoom;
    }
    setZoomFactor(value) {
      this.zoom = value;
    }
    send(channel, payload) {
      this.sent.push({ channel, payload });
    }
    async loadURL(url) {
      this.loaded.push(url);
      if (load) await load(this, url);
      this.mainFrame.url = url;
    }
    close() {
      if (this.destroyed) return;
      this.destroyed = true;
      this.emit('destroyed');
    }
  }
  const createParent = () => ({
    destroyed: false,
    webContents: new Contents(),
    isDestroyed() {
      return this.destroyed;
    },
    getContentSize() {
      return [1000, 800];
    },
    contentView: {
      children: [],
      addChildView(view) {
        this.children.push(view);
      },
      removeChildView(view) {
        this.children = this.children.filter((candidate) => candidate !== view);
      },
    },
  });
  let currentParent = createParent();
  const parent = currentParent;
  const electron = {
    WebContentsView: class {
      constructor(options) {
        this.options = options;
        this.webContents = new Contents();
        this.visible = false;
        this.bounds = null;
        views.push(this);
      }
      setVisible(value) {
        this.visible = value;
      }
      getVisible() {
        return this.visible;
      }
      setBounds(value) {
        this.bounds = value;
      }
    },
    session: {
      fromPartition(partition, options) {
        const value = Object.assign(new EventEmitter(), { partition, options, handlers: {} });
        for (const name of [
          'PermissionRequest',
          'PermissionCheck',
          'DevicePermission',
          'DisplayMediaRequest',
          'BluetoothPairing',
        ]) {
          value[`set${name}Handler`] = (handler) => {
            value.handlers[name] = handler;
          };
        }
        sessions.push(value);
        return value;
      },
    },
  };
  const { McpAppGuestHost } = compile(hostUrl, (specifier) => {
    if (specifier === 'electron') return electron;
    if (specifier.endsWith('/mcpAppGuestProtocol')) return protocol;
    return require(specifier);
  });
  const host = new McpAppGuestHost({
    getWindow: () => currentParent,
    preload: '/fixture/mcp-app-guest.cjs',
    entryUrl: () => entryUrl,
    installProtocol: (value) => installedProtocols.push(value),
    retireMount: async (value) => {
      retirements.push(value);
    },
  });
  const open = (index = 1, overrides = {}) =>
    host.open({
      key: 'app-one',
      tabId: nonce(100),
      frameName: nonce(index),
      config: config(),
      ...overrides,
    });
  const event = (index = views.length - 1) => ({
    sender: views[index].webContents,
    senderFrame: views[index].webContents.mainFrame,
  });
  const request = (identity, index = 1, overrides = {}) => ({
    ...identity,
    kind: 'request',
    requestId: uuid(index),
    method: 'callTool',
    params: { name: 'increment', arguments: {} },
    ...overrides,
  });
  return {
    host,
    views,
    sessions,
    parent,
    retirements,
    installedProtocols,
    open,
    event,
    request,
    createParent,
    replaceParent(value = createParent()) {
      currentParent = value;
      return value;
    },
  };
}

async function startGuest(h, identity) {
  await h.host.start(identity);
  const index = h.views.findIndex((view) =>
    view.webContents.sent.some(
      (item) =>
        item.payload?.kind === 'activate' && item.payload.value.guestId === identity.guestId,
    ),
  );
  await h.host.receive(h.event(index), 'ready', identity);
  h.host.registered(identity);
}

test('guests have separate nonpersistent sessions and deny all ambient device permissions', () => {
  const h = harness();
  h.open();
  h.open(2, { key: 'app-two', tabId: nonce(101) });
  assert.equal(h.sessions.length, 2);
  assert.notEqual(h.sessions[0].partition, h.sessions[1].partition);
  for (const [index, isolated] of h.sessions.entries()) {
    assert.ok(!isolated.partition.startsWith('persist:'));
    assert.deepEqual(isolated.options, { cache: false });
    assert.equal(h.installedProtocols[index], isolated);
    const prefs = h.views[index].options.webPreferences;
    assert.equal(prefs.session, isolated);
    assert.equal(prefs.preload, '/fixture/mcp-app-guest.cjs');
    assert.equal(prefs.sandbox, true);
    assert.equal(prefs.contextIsolation, true);
    assert.equal(prefs.webSecurity, true);
    assert.equal(prefs.nodeIntegration, false);
    assert.equal(prefs.nodeIntegrationInSubFrames, false);
    for (const permission of ['media', 'geolocation', 'hid', 'serial', 'usb', 'clipboard-read']) {
      let granted;
      isolated.handlers.PermissionRequest(null, permission, (value) => {
        granted = value;
      });
      assert.equal(granted, false);
      assert.equal(isolated.handlers.PermissionCheck(null, permission), false);
      assert.equal(isolated.handlers.DevicePermission({ deviceType: permission }), false);
    }
    let display;
    isolated.handlers.DisplayMediaRequest({}, (value) => {
      display = value;
    });
    assert.deepEqual(display, {});
    let pairing;
    isolated.handlers.BluetoothPairing({}, (value) => {
      pairing = value;
    });
    assert.deepEqual(pairing, { confirmed: false });
  }
  h.host.clear();
});

test('guest popup, navigation, webview and Bluetooth selection cannot escape the surface', () => {
  const h = harness();
  h.open();
  const contents = h.views[0].webContents;
  assert.deepEqual(contents.windowOpenHandler({ url: 'https://example.test/' }), {
    action: 'deny',
  });
  for (const event of ['will-navigate', 'will-attach-webview']) {
    let prevented = false;
    contents.emit(event, {
      preventDefault() {
        prevented = true;
      },
    });
    assert.equal(prevented, true);
  }
  let prevented = false;
  let selected;
  contents.emit(
    'select-bluetooth-device',
    {
      preventDefault() {
        prevented = true;
      },
    },
    [{}],
    (value) => {
      selected = value;
    },
  );
  assert.equal(prevented, true);
  assert.equal(selected, '');
  h.host.clear();
});

test('only the started guest main frame at the fixed entry URL may initialize or call back', async () => {
  const h = harness();
  const identity = h.open();
  assert.throws(() => h.host.owner(identity), /not_ready/);
  await assert.rejects(h.host.receive(h.event(), 'initialize'), /sender_invalid/);
  await startGuest(h, identity);
  assert.equal(h.host.owner(identity), h.views[0].webContents);
  assert.deepEqual(await h.host.receive(h.event(), 'initialize'), {
    ...identity,
    config: config(),
  });
  await assert.rejects(
    h.host.receive({ ...h.event(), senderFrame: { url: entryUrl } }, 'initialize'),
    /sender_invalid/,
  );
  await assert.rejects(
    h.host.receive(
      { sender: h.parent.webContents, senderFrame: h.parent.webContents.mainFrame },
      'initialize',
    ),
    /sender_invalid/,
  );
  h.views[0].webContents.mainFrame.url = 'https://example.test/replaced-document';
  await assert.rejects(h.host.receive(h.event(), 'initialize'), /sender_invalid/);
  h.host.clear();
});

test('callbacks preserve identity and parameters, settle once, and reject replayed responses', async () => {
  const h = harness();
  const identity = h.open();
  await startGuest(h, identity);
  const call = h.request(identity);
  const completion = h.host.receive(h.event(), 'request', call);
  assert.deepEqual(h.parent.webContents.sent.at(-1), {
    channel: protocol.MCP_APP_GUEST_EVENT,
    payload: call,
  });
  const result = { content: [{ type: 'text', text: 'count=1' }] };
  h.host.respond({ ...identity, requestId: call.requestId, ok: true, result });
  assert.deepEqual(await completion, result);
  assert.throws(
    () => h.host.respond({ ...identity, requestId: call.requestId, ok: true, result }),
    /request_expired/,
  );
  h.host.clear();
});

test('unsupported methods and cross-guest or stale identities never reach the root callback', async () => {
  const h = harness();
  const first = h.open();
  await startGuest(h, first);
  const second = h.open(2, { key: 'app-two', tabId: nonce(101) });
  await startGuest(h, second);
  const previousCount = h.parent.webContents.sent.length;
  await assert.rejects(h.host.receive(h.event(0), 'request', h.request(first)), /sender_invalid/);
  await assert.rejects(h.host.receive(h.event(1), 'request', h.request(first)), /expired/);
  await assert.rejects(
    h.host.receive(h.event(1), 'request', h.request(second, 1, { method: 'cloud_request' })),
    /method_invalid/,
  );
  await assert.rejects(
    h.host.receive(h.event(1), 'request', h.request(second, 1, { tabId: nonce(999) })),
    /expired/,
  );
  assert.equal(h.parent.webContents.sent.length, previousCount);
  h.host.clear();
});

test('SDK cancellation cancels exactly one root request and rejects its late result', async () => {
  const h = harness();
  const identity = h.open();
  await startGuest(h, identity);
  const first = h.request(identity, 1);
  const second = h.request(identity, 2);
  const pendingFirst = h.host.receive(h.event(), 'request', first);
  const failedFirst = assert.rejects(pendingFirst, /request_cancelled/);
  const pendingSecond = h.host.receive(h.event(), 'request', second);
  await h.host.receive(h.event(), 'cancel', { ...identity, requestId: first.requestId });
  await failedFirst;
  assert.deepEqual(h.parent.webContents.sent.at(-1).payload, {
    ...identity,
    kind: 'cancel',
    requestId: first.requestId,
  });
  assert.throws(
    () => h.host.respond({ ...identity, requestId: first.requestId, ok: true }),
    /request_expired/,
  );
  h.host.respond({ ...identity, requestId: second.requestId, ok: true, result: 'second only' });
  assert.equal(await pendingSecond, 'second only');
  h.host.clear();
});

test('pending callback count is bounded and duplicate request IDs are rejected', async () => {
  const h = harness();
  const identity = h.open();
  await startGuest(h, identity);
  const completions = [];
  for (let i = 1; i <= 32; i += 1) {
    const pending = h.host.receive(h.event(), 'request', h.request(identity, i));
    completions.push(assert.rejects(pending, /request_cancelled/));
  }
  await assert.rejects(
    h.host.receive(h.event(), 'request', h.request(identity, 33)),
    /requests_busy/,
  );
  await assert.rejects(
    h.host.receive(h.event(), 'request', h.request(identity, 1)),
    /requests_busy/,
  );
  assert.equal(
    h.parent.webContents.sent.filter((item) => item.payload.kind === 'request').length,
    32,
  );
  h.host.release(identity);
  await Promise.all(completions);
  assert.equal(
    h.parent.webContents.sent.filter((item) => item.payload.kind === 'cancel').length,
    32,
  );
  h.host.clear();
});

test('switching away and back retains the same guest document but refreshes its mount authority', async () => {
  const h = harness();
  const first = h.open();
  await startGuest(h, first);
  const original = h.views[0];
  original.webContents.appState = { count: 7 };
  h.host.layout({ ...first, sequence: 0, bounds: { x: 20, y: 30, width: 400, height: 300 } });
  h.host.release(first);
  assert.equal(original.visible, false);
  assert.equal(h.parent.contentView.children.includes(original), false);
  const next = h.open(2);
  await h.host.start(next);
  assert.equal(h.views.length, 1);
  assert.equal(next.guestId, first.guestId);
  assert.notEqual(next.frameName, first.frameName);
  assert.equal(original.webContents.loaded.length, 1);
  assert.equal(original.webContents.appState.count, 7);
  assert.deepEqual(original.webContents.sent.at(-1).payload, {
    kind: 'activate',
    value: { ...next, config: config() },
  });
  assert.throws(() => h.host.owner(first), /expired/);
  assert.throws(() => h.open(1), /mount_cancelled/);
  h.host.release(first);
  assert.equal(h.host.owner(next), original.webContents);
  assert.deepEqual(h.retirements[0], { tabId: first.tabId, frameName: first.frameName });
  h.host.clear();
});

test('monotonic layout updates use native zoom and stale updates cannot reveal a hidden guest', async () => {
  const h = harness();
  h.parent.webContents.zoom = 1.5;
  const identity = h.open();
  await startGuest(h, identity);
  h.host.layout({
    ...identity,
    sequence: 1,
    bounds: { x: 10.2, y: 12.6, width: 400.7, height: 300.3 },
  });
  const view = h.views[0];
  assert.deepEqual(view.bounds, { x: 16, y: 19, width: 600, height: 450 });
  assert.equal(view.webContents.zoom, 1.5);
  assert.equal(view.visible, true);
  h.host.layout({ ...identity, sequence: 3, bounds: null });
  h.host.layout({ ...identity, sequence: 2, bounds: { x: 0, y: 0, width: 500, height: 500 } });
  assert.equal(view.visible, false);
  assert.equal(h.parent.contentView.children.length, 0);
  h.host.layout({ ...identity, sequence: 4, bounds: { x: 0, y: 0, width: NaN, height: 500 } });
  assert.equal(view.visible, false);
  h.host.clear();
});

test('pruning a closed tab and clearing authority destroy views and cancel pending callbacks', async () => {
  const h = harness();
  const first = h.open();
  await startGuest(h, first);
  const firstCall = h.host.receive(h.event(), 'request', h.request(first));
  const firstRejected = assert.rejects(firstCall, /request_cancelled/);
  h.host.prune({ keys: [] });
  await firstRejected;
  assert.equal(h.views[0].webContents.destroyed, true);
  assert.throws(() => h.host.owner(first), /expired/);
  const next = h.open(2);
  await h.host.start(next);
  const nextCall = h.host.receive(h.event(), 'request', h.request(next));
  const nextRejected = assert.rejects(nextCall, /request_cancelled/);
  h.host.clear();
  await nextRejected;
  assert.equal(h.views[1].webContents.destroyed, true);
  assert.throws(() => h.host.respond({ ...next, requestId: uuid(1), ok: true }), /expired/);
  assert.throws(() => h.open(2), /mount_cancelled/);
  h.host.clear();
});

test('a guest crash cancels callbacks and a later reopen creates a new rendering surface', async () => {
  const h = harness();
  const first = h.open();
  await startGuest(h, first);
  const pending = h.host.receive(h.event(), 'request', h.request(first));
  const failed = assert.rejects(pending, /request_cancelled/);
  h.views[0].webContents.emit('render-process-gone', {}, { reason: 'crashed' });
  await failed;
  assert.throws(() => h.host.owner(first), /expired/);
  const replacement = h.open(2);
  await h.host.start(replacement);
  assert.notEqual(replacement.guestId, first.guestId);
  assert.equal(h.views.length, 2);
  h.host.clear();
});

test('parent replacement invalidates initialization as well as callbacks and layout', async () => {
  const h = harness();
  const identity = h.open();
  await startGuest(h, identity);
  h.replaceParent();
  assert.throws(() => h.host.owner(identity), /expired/);
  assert.throws(() => h.host.layout({ ...identity, sequence: 1, bounds: null }), /expired/);
  await assert.rejects(
    h.host.receive(h.event(), 'request', h.request(identity)),
    /expired|sender_invalid/,
  );
  await assert.rejects(h.host.receive(h.event(), 'initialize'), /expired|sender_invalid/);
  h.host.clear();
});

test('rapid reactivation during initial loading shares one document load', async () => {
  const loading = deferred();
  const h = harness({ load: () => loading.promise });
  const first = h.open();
  const firstStart = h.host.start(first);
  const firstRetired = assert.rejects(firstStart, /expired/);
  h.host.release(first);
  const next = h.open(2);
  const nextStart = h.host.start(next);
  const observedLoads = h.views[0].webContents.loaded.length;
  loading.resolve();
  await Promise.all([firstRetired, nextStart]);
  assert.equal(
    observedLoads,
    1,
    'switching while loadURL is pending must not reload the App document',
  );
  await h.host.receive(h.event(), 'ready', next);
  h.host.registered(next);
  assert.equal(h.host.owner(next), h.views[0].webContents);
  h.host.clear();
});

test('automation callbacks wait for the initialized document and authenticated attach', async () => {
  const h = harness();
  const identity = h.open();
  await h.host.start(identity);
  assert.throws(() => h.host.owner(identity), /not_ready/);
  const pending = h.host.receive(h.event(), 'request', h.request(identity));
  assert.equal(
    h.parent.webContents.sent.filter((item) => item.payload.kind === 'request').length,
    0,
  );
  await h.host.receive(h.event(), 'ready', identity);
  assert.equal(h.host.owner(identity), h.views[0].webContents);
  h.host.registered(identity);
  const request = h.parent.webContents.sent.find((item) => item.payload.kind === 'request').payload;
  h.host.respond({ ...request, ok: true, result: 'attached' });
  assert.equal(await pending, 'attached');
  h.host.clear();
});

test('same-document navigation keeps state but a registered App document reload retires authority', async () => {
  const h = harness();
  const identity = h.open();
  await startGuest(h, identity);
  const view = h.views[0];
  const frame = view.webContents.mainFrame.frames[0].frames[0];
  view.webContents.emit('did-start-navigation', {
    isMainFrame: false,
    isSameDocument: true,
    frame,
  });
  assert.equal(view.webContents.isDestroyed(), false);
  const pending = h.host.receive(h.event(), 'request', h.request(identity));
  const cancelled = assert.rejects(pending, /cancelled/);
  view.webContents.emit('did-start-navigation', {
    isMainFrame: false,
    isSameDocument: false,
    frame,
  });
  await cancelled;
  assert.equal(view.webContents.isDestroyed(), true);
  assert.throws(() => h.host.owner(identity), /expired/);
  assert.ok(h.parent.webContents.sent.some((item) => item.payload.kind === 'retired'));
});

test('an explicitly changed document creates a fresh surface while tool notifications retain it', async () => {
  const h = harness();
  const identity = h.open();
  await startGuest(h, identity);
  const owner = h.host.owner(identity);
  h.host.update({ ...identity, config: { ...config(), toolResult: { content: [] } } });
  assert.equal(h.host.owner(identity), owner);
  h.host.release(identity);
  const changed = h.open(2, { config: { ...config(), html: '<p>Replacement</p>' } });
  await startGuest(h, changed);
  assert.notEqual(h.host.owner(changed), owner);
  assert.equal(owner.isDestroyed(), true);
  assert.equal(h.views.length, 2);
  h.host.clear();
});

test('SDK setup failures reach the host before automation attachment can complete', async () => {
  const h = harness();
  const identity = h.open();
  await h.host.start(identity);
  const pending = h.host.receive(
    h.event(),
    'request',
    h.request(identity, 1, {
      method: 'error',
      params: { message: 'sandbox initialization failed' },
    }),
  );
  const request = h.parent.webContents.sent.find((item) => item.payload.kind === 'request').payload;
  assert.equal(request.method, 'error');
  h.host.respond({ ...request, ok: true, result: {} });
  await pending;
  assert.throws(() => h.host.owner(identity), /not_ready/);
  h.host.clear();
});

test('every guest session blocks unscoped browser downloads before any save or prompt', () => {
  const h = harness();
  h.open();
  h.open(2, { key: 'app-two', tabId: nonce(101) });
  for (const isolated of h.sessions) {
    let prevented = 0;
    isolated.emit(
      'will-download',
      {
        preventDefault() {
          prevented++;
        },
      },
      { url: 'https://example.test/download' },
    );
    assert.equal(prevented, 1);
  }
  h.host.clear();
});
