import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../electron/main/mcpAppFrames.ts', import.meta.url), 'utf8');
const module = { exports: {} };
new Function('exports', 'module', ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText)(module.exports, module);
const { McpAppFrames } = module.exports;
const hostSource = readFileSync(new URL('../electron/main/mcpAppFrameHost.ts', import.meta.url), 'utf8');
const hostModule = { exports: {} };
new Function('exports', 'module', 'require', ts.transpileModule(hostSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText)(hostModule.exports, hostModule, createRequire(import.meta.url));
const { McpAppFrameHost } = hostModule.exports;
const tabId = 'mcpapp-12345678-1234-1234-1234-123456789012';
const frameName = 'mcpapp-22345678-1234-1234-1234-123456789012';
const realChromium = { skip: process.env.AGISTACK_MCP_APP_FRAME_CHROMIUM_TESTS !== '1', timeout: 15_000 };

function fixture(oopif = false) {
  const calls = [];
  let liveName = frameName;
  const frame = { id: 'app-frame', parentId: 'sandbox-frame', loaderId: 'app-document', url: 'about:srcdoc' };
  const outer = { frame: { id: 'sandbox-frame', parentId: 'host-frame', loaderId: 'sandbox-document', name: frameName, url: 'https://sandbox.invalid/' }, childFrames: [{ frame }] };
  const tree = { frame: { id: 'host-frame', loaderId: 'host-document', url: 'file://host/index.html' }, childFrames: [outer] };
  const targets = [{ type: 'iframe', targetId: 'app-frame', parentFrameId: 'sandbox-frame' }];
  if (oopif) targets.push({ type: 'iframe', targetId: 'sandbox-frame', parentFrameId: 'host-frame' });
  const owner = { id: 1, isDestroyed: () => false,
    debugger: { isAttached: () => true, attach: () => {}, async sendCommand(method, params, session) {
      calls.push({ method, params, session });
      if (method === 'Page.getFrameTree') return { frameTree: session === 'only-app-session' ? { frame } : session === 'only-sandbox-session' ? { frame: outer.frame } : oopif ? { frame: tree.frame } : tree };
      if (method === 'DOM.getDocument') return { root: { nodeId: 1 } };
      if (method === 'DOM.querySelectorAll') return { nodeIds: params.selector.includes(liveName) ? [2] : [] };
      if (method === 'DOM.describeNode') return { node: { frameId: outer.frame.id } };
      if (method === 'Target.getTargets') return { targetInfos: targets };
      if (method === 'Target.attachToTarget') return { sessionId: params.targetId === 'sandbox-frame' ? 'only-sandbox-session' : 'only-app-session' };
      if (method === 'Page.createIsolatedWorld') return { executionContextId: 17 };
      if (method === 'Runtime.evaluate') return { result: { value: 'owned app DOM' } };
      throw Error(`unexpected: ${method}`);
    } },
  };
  return { calls, frame, outer, tree, targets, owner, registry: new McpAppFrames(() => true), rename: name => { liveName = name; } };
}

test('cancel before frame registration tombstones only the exact mount nonce', async () => {
  const f = fixture();
  f.registry.cancel({ tabId, frameName });
  await assert.rejects(f.registry.register(f.owner, { tabId, frameName }), /cancelled/u);
  assert.equal(f.calls.length, 0, 'a cancelled mount must not start frame discovery');
  const newName = 'mcpapp-32345678-1234-1234-1234-123456789012';
  f.rename(newName);
  assert.deepEqual(await f.registry.register(f.owner, { tabId, frameName: newName }), { tabId, frameName: newName });
  f.registry.cancel({ tabId, frameName });
  f.registry.remove({ tabId, frameName });
  assert.equal(await f.registry.execute({ tabId, mountNonce: newName, expression: '42' }), 'owned app DOM');
});

test('late registration cannot revive a cancelled mount or overwrite the StrictMode replacement', async () => {
  const f = fixture();
  const dispatch = f.owner.debugger.sendCommand.bind(f.owner.debugger);
  let complete;
  let ready;
  const waiting = new Promise(resolve => { ready = resolve; });
  f.owner.debugger.sendCommand = async (method, params, session) => {
    const result = await dispatch(method, params, session);
    if (method === 'Page.getFrameTree' && session === 'only-app-session' && !complete) {
      await new Promise(resolve => { complete = resolve; ready(); });
    }
    return result;
  };
  const oldRegistration = f.registry.register(f.owner, { tabId, frameName });
  await waiting;
  f.registry.cancel({ tabId, frameName });
  const newName = 'mcpapp-32345678-1234-1234-1234-123456789012';
  f.rename(newName);
  await f.registry.register(f.owner, { tabId, frameName: newName });
  complete();
  await assert.rejects(oldRegistration, /cancelled/u);
  f.registry.cancel({ tabId, frameName });
  f.registry.remove({ tabId, frameName });
  assert.equal(await f.registry.execute({ tabId, mountNonce: newName, expression: '42' }), 'owned app DOM');
});

test('clearing the registry rejects a registration that was still resolving its frame', async () => {
  const f = fixture();
  const dispatch = f.owner.debugger.sendCommand.bind(f.owner.debugger);
  let complete;
  let ready;
  const waiting = new Promise(resolve => { ready = resolve; });
  f.owner.debugger.sendCommand = async (method, params, session) => {
    const result = await dispatch(method, params, session);
    if (method === 'Page.getFrameTree' && session === 'only-app-session' && !complete) {
      await new Promise(resolve => { complete = resolve; ready(); });
    }
    return result;
  };
  const registration = f.registry.register(f.owner, { tabId, frameName });
  await waiting;
  f.registry.clear();
  complete();
  await assert.rejects(registration, /expired/u);
  await assert.rejects(f.registry.execute({ tabId, mountNonce: frameName, expression: '42' }), /unavailable/u);
});

test('temporary exact-mount removal permits retry while cancellation permanently rejects it', async () => {
  const f = fixture();
  await f.registry.register(f.owner, { tabId, frameName });
  f.registry.remove({ tabId, frameName });
  await assert.rejects(f.registry.execute({ tabId, mountNonce: frameName, expression: '42' }), /unavailable/u);
  await f.registry.register(f.owner, { tabId, frameName });
  f.registry.cancel({ tabId, frameName });
  await assert.rejects(f.registry.register(f.owner, { tabId, frameName }), /cancelled/u);
});

test('queued operations for an old mount cannot evaluate or capture a replacement frame', async () => {
  const f = fixture();
  let screenshots = 0;
  f.owner.executeJavaScriptInIsolatedWorld = async () => ({ x: 0, y: 0, width: 20, height: 20 });
  f.owner.capturePage = async () => {
    screenshots += 1;
    return { toPNG: () => Buffer.from('image'), getSize: () => ({ width: 20, height: 20 }) };
  };
  await f.registry.register(f.owner, { tabId, frameName });
  const queued = [
    { tabId, mountNonce: frameName, operation: 'playwright.locator', expression: 'document.querySelector("button").click()' },
    { tabId, mountNonce: frameName, operation: 'tab.screenshot' },
  ];
  f.registry.cancel({ tabId, frameName });
  const newName = 'mcpapp-32345678-1234-1234-1234-123456789012';
  f.rename(newName);
  await f.registry.register(f.owner, { tabId, frameName: newName });
  f.calls.length = 0;
  for (const request of queued) await assert.rejects(f.registry.execute(request), /expired/u);
  assert.equal(f.calls.length, 0, 'old queued requests must fail before any CDP command');
  assert.equal(screenshots, 0);
  assert.equal(await f.registry.execute({ tabId, mountNonce: newName, expression: '42' }), 'owned app DOM');
});

test('renderer clear returns pending and retryable mounts for exact sidecar retirement', async () => {
  const f = fixture();
  await f.registry.register(f.owner, { tabId, frameName });
  f.registry.remove({ tabId, frameName });
  assert.deepEqual(f.registry.clear(), [{ tabId, frameName }]);
  assert.deepEqual(f.registry.clear(), []);
});

function sidecarMounts() {
  const calls = [];
  const cancelled = new Set();
  let current;
  return {
    calls,
    get current() { return current; },
    async invoke(input) {
      calls.push(input);
      if (input.operation === 'detach') {
        cancelled.add(input.mountNonce);
        if (current === input.mountNonce) current = undefined;
        return {};
      }
      if (cancelled.has(input.mountNonce)) throw Error('mcp_app_mount_cancelled');
      if (current && current !== input.mountNonce) throw Error('mcp_app_mount_already_bound');
      current = input.mountNonce;
      return { tabId: input.tabId, pending: false };
    },
  };
}

test('host renderer retirement detaches the sidecar mount before a replacement registers', async () => {
  const f = fixture();
  const sidecar = sidecarMounts();
  const host = new McpAppFrameHost(f.registry, input => sidecar.invoke(input));
  await host.register(f.owner, { tabId, frameName });
  assert.equal(sidecar.current, frameName);
  await host.clear();
  assert.equal(sidecar.current, undefined);
  const newName = 'mcpapp-32345678-1234-1234-1234-123456789012';
  f.rename(newName);
  await host.register(f.owner, { tabId, frameName: newName });
  await host.unregister({ tabId, frameName });
  assert.equal(sidecar.current, newName);
  assert.equal(await f.registry.execute({ tabId, mountNonce: newName, expression: '42' }), 'owned app DOM');
});

test('late private attach completion after renderer clear cannot retain the old sidecar mount', async () => {
  const f = fixture();
  const sidecar = sidecarMounts();
  let complete;
  let ready;
  const started = new Promise(resolve => { ready = resolve; });
  const host = new McpAppFrameHost(f.registry, async input => {
    const result = await sidecar.invoke(input);
    if (input.operation === 'attach' && input.mountNonce === frameName) {
      await new Promise(resolve => { complete = resolve; ready(); });
    }
    return result;
  });
  const old = host.register(f.owner, { tabId, frameName });
  await started;
  await host.clear();
  const newName = 'mcpapp-32345678-1234-1234-1234-123456789012';
  f.rename(newName);
  await host.register(f.owner, { tabId, frameName: newName });
  complete();
  await assert.rejects(old, /expired/u);
  assert.equal(sidecar.current, newName);
  assert.equal(sidecar.calls.filter(call => call.operation === 'detach' && call.mountNonce === frameName).length, 2);
  assert.equal(await f.registry.execute({ tabId, mountNonce: newName, expression: '42' }), 'owned app DOM');
});

test('host clear retires an attach whose sidecar applied it before returning an error', async () => {
  const f = fixture();
  const sidecar = sidecarMounts();
  const host = new McpAppFrameHost(f.registry, async input => {
    const result = await sidecar.invoke(input);
    if (input.operation === 'attach') throw Error('attach response lost');
    return result;
  });
  await assert.rejects(host.register(f.owner, { tabId, frameName }), /response lost/u);
  assert.equal(sidecar.current, frameName);
  await host.clear();
  assert.equal(sidecar.current, undefined);
});

test('private host callbacks queued for an old nonce cannot dispatch any operation after remount', async () => {
  const f = fixture();
  const sidecar = sidecarMounts();
  const dispatches = [];
  const host = new McpAppFrameHost(f.registry, async input => {
    if (['attach', 'detach'].includes(input.operation)) return sidecar.invoke(input);
    dispatches.push(input);
    return {};
  });
  await host.register(f.owner, { tabId, frameName });
  const requests = ['tools/call', 'resources/read', 'resources/list', 'resources/templates/list', 'prompts/list', 'prompts/get']
    .map(operation => ({ tabId, mountNonce: frameName, operation, arguments: {} }));
  await host.unregister({ tabId, frameName });
  const newName = 'mcpapp-32345678-1234-1234-1234-123456789012';
  f.rename(newName);
  await host.register(f.owner, { tabId, frameName: newName });
  for (const request of requests) await assert.rejects(host.operation(request), /expired/u);
  assert.equal(dispatches.length, 0);
  await host.operation({ tabId, mountNonce: newName, operation: 'prompts/get', arguments: { mountNonce: frameName } });
  assert.equal(dispatches.length, 1);
  assert.equal(dispatches[0].mountNonce, newName);
});

test('MCP App operations target only the pinned child frame in an isolated CDP world', async () => {
  const f = fixture();
  await f.registry.register(f.owner, { tabId, frameName });
  assert.equal(await f.registry.execute({ tabId, mountNonce: frameName, operation: 'playwright.domSnapshot', expression: 'document.body.innerText' }), 'owned app DOM');
  const context = f.calls.find(item => item.method === 'Page.createIsolatedWorld');
  assert.equal(context.params.frameId, 'app-frame');
  assert.equal(context.session, 'only-app-session');
  const script = f.calls.find(item => item.method === 'Runtime.evaluate');
  assert.equal(script.params.contextId, 17);
  assert.equal(script.session, 'only-app-session');
  assert.ok(!f.calls.some(item => item.params?.frameId === 'host-frame'));
  f.registry.remove({ tabId, frameName });
  await assert.rejects(f.registry.execute({ tabId, mountNonce: frameName, expression: '42' }), /unavailable/u);
});

test('the host-owned iframe node identifies a frame renamed after navigation', async () => {
  const f = fixture(true);
  f.outer.frame.name = 'initial-sandbox-name';
  await f.registry.register(f.owner, { tabId, frameName });
  assert.equal(await f.registry.execute({ tabId, mountNonce: frameName, expression: 'document.body.innerText' }), 'owned app DOM');
  assert.equal(f.calls.find(item => item.method === 'Page.createIsolatedWorld').params.frameId, 'app-frame');
});

test('missing, substituted and navigated frames cannot reuse an App handle', async () => {
  const f = fixture();
  await assert.rejects(f.registry.register(f.owner, { tabId, frameName: tabId }), /not_ready/u);
  await f.registry.register(f.owner, { tabId, frameName });
  f.frame.url = 'https://another.invalid/';
  await assert.rejects(f.registry.execute({ tabId, mountNonce: frameName, expression: '42' }), /expired/u);
  assert.ok(!f.calls.some(item => item.method === 'Runtime.evaluate'));
  f.outer.childFrames = [];
  f.targets.length = 0;
  await assert.rejects(f.registry.register(f.owner, { tabId, frameName }), /not_ready/u);
});


test('navigation during a frame operation rejects its result', async () => {
  const f = fixture();
  const dispatch = f.owner.debugger.sendCommand.bind(f.owner.debugger);
  f.owner.debugger.sendCommand = async (method, params, session) => {
    const result = await dispatch(method, params, session);
    if (method === 'Runtime.evaluate') f.frame.id = 'replacement-frame';
    return result;
  };
  await f.registry.register(f.owner, { tabId, frameName });
  await assert.rejects(
    f.registry.execute({ tabId, mountNonce: frameName, operation: 'playwright.domSnapshot', expression: 'document.body.innerText' }),
    /expired/u,
  );
  assert.equal(f.calls.filter(item => item.method === 'Runtime.evaluate').length, 1);
});

test('App and sandbox document reloads expire handles even with unchanged frame ids and URLs', async () => {
  for (const target of ['frame', 'outer', 'host']) {
    const f = fixture();
    await f.registry.register(f.owner, { tabId, frameName });
    (target === 'frame' ? f.frame : target === 'outer' ? f.outer.frame : f.tree.frame).loaderId = 'replacement-document';
    await assert.rejects(f.registry.execute({ tabId, mountNonce: frameName, expression: '42' }), /expired/u);
    await assert.rejects(f.registry.register(f.owner, { tabId, frameName }), /already_bound/u);
    assert.ok(!f.calls.some(item => item.method === 'Runtime.evaluate'));
  }
});

test('documents without a loader cannot be registered', async () => {
  for (const target of ['frame', 'outer']) {
    const f = fixture();
    delete (target === 'frame' ? f.frame : f.outer.frame).loaderId;
    await assert.rejects(f.registry.register(f.owner, { tabId, frameName }), /not_ready/u);
  }
});

test('reload during isolated-world creation prevents evaluation in the replacement document', async () => {
  const f = fixture();
  const dispatch = f.owner.debugger.sendCommand.bind(f.owner.debugger);
  f.owner.debugger.sendCommand = async (method, params, session) => {
    const result = await dispatch(method, params, session);
    if (method === 'Page.createIsolatedWorld') f.frame.loaderId = 'replacement-document';
    return result;
  };
  await f.registry.register(f.owner, { tabId, frameName });
  await assert.rejects(f.registry.execute({ tabId, mountNonce: frameName, expression: '42' }), /expired/u);
  assert.ok(!f.calls.some(item => item.method === 'Runtime.evaluate'));
});

test('same-URL reload while an evaluation is pending discards the late result', async () => {
  const f = fixture();
  const dispatch = f.owner.debugger.sendCommand.bind(f.owner.debugger);
  f.owner.debugger.sendCommand = async (method, params, session) => {
    const result = await dispatch(method, params, session);
    if (method === 'Runtime.evaluate') f.frame.loaderId = 'replacement-document';
    return result;
  };
  await f.registry.register(f.owner, { tabId, frameName });
  await assert.rejects(f.registry.execute({ tabId, mountNonce: frameName, expression: '42' }), /expired/u);
  assert.equal(f.calls.filter(item => item.method === 'Runtime.evaluate').length, 1);
});

test('removal and replacement during evaluation invalidate the original in-flight binding', async () => {
  for (const replace of [false, true]) {
    const f = fixture();
    const dispatch = f.owner.debugger.sendCommand.bind(f.owner.debugger);
    f.owner.debugger.sendCommand = async (method, params, session) => {
      const result = await dispatch(method, params, session);
      if (method === 'Runtime.evaluate') {
        f.registry.remove({ tabId, frameName });
        if (replace) await f.registry.register(f.owner, { tabId, frameName });
      }
      return result;
    };
    await f.registry.register(f.owner, { tabId, frameName });
    await assert.rejects(f.registry.execute({ tabId, mountNonce: frameName, expression: '42' }), /expired/u);
  }
});

test('same-document registration remains idempotent during an in-flight operation', async () => {
  const f = fixture();
  const dispatch = f.owner.debugger.sendCommand.bind(f.owner.debugger);
  f.owner.debugger.sendCommand = async (method, params, session) => {
    const result = await dispatch(method, params, session);
    if (method === 'Runtime.evaluate') await f.registry.register(f.owner, { tabId, frameName });
    return result;
  };
  await f.registry.register(f.owner, { tabId, frameName });
  assert.equal(await f.registry.execute({ tabId, mountNonce: frameName, expression: '42' }), 'owned app DOM');
});

test('same-URL reload while capturing a screenshot discards the late image', async () => {
  const f = fixture();
  f.owner.executeJavaScriptInIsolatedWorld = async () => ({ x: 0, y: 0, width: 20, height: 20 });
  f.owner.capturePage = async () => {
    f.frame.loaderId = 'replacement-document';
    return { toPNG: () => Buffer.from('image'), getSize: () => ({ width: 20, height: 20 }) };
  };
  await f.registry.register(f.owner, { tabId, frameName });
  await assert.rejects(f.registry.execute({ tabId, mountNonce: frameName, operation: 'tab.screenshot' }), /expired/u);
});

test('cross-process sandbox and App frames resolve only through verified direct ancestry', async () => {
  const f = fixture(true);
  f.targets.push({ type: 'iframe', targetId: 'sibling-frame', parentFrameId: 'host-frame' });
  await f.registry.register(f.owner, { tabId, frameName });
  assert.equal(await f.registry.execute({ tabId, mountNonce: frameName, expression: '42' }), 'owned app DOM');
  assert.deepEqual(f.calls.filter(call => call.method === 'Target.attachToTarget').map(call => call.params.targetId), ['sandbox-frame', 'app-frame']);
  assert.equal(f.calls.find(call => call.method === 'Runtime.evaluate').session, 'only-app-session');
  f.frame.loaderId = 'next-app-document';
  await assert.rejects(f.registry.execute({ tabId, mountNonce: frameName, expression: '42' }), /expired/u);
});

test('a target with another parent cannot substitute for the named sandbox', async () => {
  const f = fixture(true);
  f.targets.find(target => target.targetId === 'sandbox-frame').parentFrameId = 'another-host';
  await assert.rejects(f.registry.register(f.owner, { tabId, frameName }), /invalid/u);
  assert.ok(!f.calls.some(call => call.method === 'Target.attachToTarget'));
});

test('real Chromium srcdoc reload keeps frame id and URL but expires its App handle', realChromium, async (t) => {
  const { chromium } = await import('@playwright/test');
  const browser = await chromium.launch({ headless: true });
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.setContent(`<iframe name="${frameName}" sandbox="allow-scripts allow-same-origin allow-forms" srcdoc="<iframe sandbox='allow-scripts allow-same-origin' srcdoc='&lt;button&gt;Owned&lt;/button&gt;'></iframe>"></iframe>`);
  await page.frameLocator('iframe').frameLocator('iframe').getByRole('button').waitFor();
  const cdp = await page.context().newCDPSession(page);
  const owner = {
    id: 2,
    isDestroyed: () => page.isClosed(),
    debugger: { isAttached: () => true, sendCommand: (method, params) => cdp.send(method, params) },
  };
  const registry = new McpAppFrames();
  await registry.register(owner, { tabId, frameName });
  assert.equal(await registry.execute({ tabId, mountNonce: frameName, expression: 'document.body.innerText' }), 'Owned');
  const before = (await cdp.send('Page.getFrameTree')).frameTree.childFrames[0].childFrames[0].frame;
  const inner = page.frames()[2];
  const navigated = page.waitForEvent('framenavigated', (frame) => frame === inner);
  await inner.evaluate(() => location.reload());
  await navigated;
  await inner.getByRole('button').waitFor();
  const after = (await cdp.send('Page.getFrameTree')).frameTree.childFrames[0].childFrames[0].frame;
  assert.equal(after.id, before.id);
  assert.equal(after.url, before.url);
  assert.notEqual(after.loaderId, before.loaderId);
  await assert.rejects(registry.execute({ tabId, mountNonce: frameName, expression: 'document.body.innerText' }), /expired/u);
});

test('real dynamically named OOPIF chain isolates siblings and expires on same-URL reload', realChromium, async (t) => {
  const { chromium } = await import('@playwright/test');
  const server = createServer((request, response) => {
    response.setHeader('Content-Type', 'text/html');
    response.end(request.url === '/sandbox'
      ? '<iframe sandbox="allow-scripts" srcdoc="<button>Owned</button>"></iframe>'
      : `<iframe name="initial-sandbox-name" sandbox="allow-scripts allow-same-origin allow-forms" src="http://localhost:${server.address().port}/sandbox"></iframe><iframe name="sibling" src="http://localhost:${server.address().port}/sandbox"></iframe>`);
  });
  await new Promise(resolve => server.listen(0, '0.0.0.0', resolve));
  let profile;
  let context;
  let socket;
  t.after(async () => {
    socket?.close();
    await context?.close();
    await new Promise(resolve => server.close(resolve));
    if (profile) await rm(profile, { recursive: true, force: true });
  });
  profile = await mkdtemp(join(tmpdir(), 'memstack-mcp-app-cdp-'));
  context = await chromium.launchPersistentContext(profile, {
    headless: true,
    args: ['--site-per-process', '--remote-debugging-port=0'],
  });
  const page = context.pages()[0];
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.frameLocator('iframe[name="initial-sandbox-name"]').frameLocator('iframe').getByRole('button').waitFor();
  await page.locator('iframe[name="initial-sandbox-name"]').evaluate((frame, name) => {
    frame.name = name;
  }, frameName);
  const [port, endpoint] = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).trim().split('\n');
  socket = new WebSocket(`ws://127.0.0.1:${port}${endpoint}`);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  let commandId = 0;
  const pending = new Map();
  const commands = [];
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data);
    const command = pending.get(message.id);
    if (!command) return;
    pending.delete(message.id);
    if (message.error) command.reject(new Error(message.error.message));
    else command.resolve(message.result);
  });
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++commandId;
    commands.push({ method, params, sessionId });
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params, sessionId }));
  });
  const { targetInfos } = await send('Target.getTargets');
  const host = targetInfos.find(target => target.type === 'page' && target.url === page.url());
  const { sessionId } = await send('Target.attachToTarget', { targetId: host.targetId, flatten: true });
  const owner = {
    id: 3,
    isDestroyed: () => page.isClosed(),
    debugger: { isAttached: () => true, sendCommand: (method, params, session) => send(method, params, session ?? sessionId) },
  };
  const hostTree = await owner.debugger.sendCommand('Page.getFrameTree');
  assert.equal(hostTree.frameTree.childFrames, undefined);
  const registry = new McpAppFrames();
  await registry.register(owner, { tabId, frameName });
  assert.equal(await registry.execute({ tabId, mountNonce: frameName, expression: 'document.body.innerText' }), 'Owned');
  const attached = commands.filter(command => command.method === 'Target.attachToTarget');
  assert.equal(attached.length, 3, 'only host, intended sandbox and intended App attach');
  const innerTarget = attached[2].params.targetId;
  const innerSession = commands.find(command => command.method === 'Runtime.evaluate').sessionId;
  const before = (await send('Page.getFrameTree', {}, innerSession)).frameTree.frame;
  const outerNode = await page.locator(`iframe[name="${frameName}"]`).elementHandle();
  const outer = await outerNode.contentFrame();
  assert.ok(outer);
  assert.equal(outer.name(), 'initial-sandbox-name');
  const inner = outer.childFrames()[0];
  const navigated = page.waitForEvent('framenavigated', frame => frame === inner);
  await inner.evaluate(() => location.reload());
  await navigated;
  await inner.getByRole('button').waitFor();
  const after = (await send('Page.getFrameTree', {}, innerSession)).frameTree.frame;
  assert.equal(after.id, innerTarget);
  assert.equal(after.id, before.id);
  assert.equal(after.url, before.url);
  assert.notEqual(after.loaderId, before.loaderId);
  await assert.rejects(registry.execute({ tabId, mountNonce: frameName, expression: 'document.body.innerText' }), /expired/u);
  registry.remove({ tabId, frameName });
  await registry.register(owner, { tabId, frameName });
  await page.evaluate((name) => {
    document.querySelector(`iframe[name="${name}"]`).name = 'previous';
    document.querySelector('iframe[name="sibling"]').name = name;
  }, frameName);
  await assert.rejects(registry.execute({ tabId, mountNonce: frameName, expression: 'document.body.innerText' }), /expired/u);
  assert.equal(commands.filter(command => command.method === 'Target.attachToTarget').length, 3,
    'expired handles must not attach to the sibling sandbox or App');
});


test('an unverified host WebContents cannot be used as an App screenshot surface', async () => {
  const f = fixture();
  const registry = new McpAppFrames();
  let captures = 0;
  f.owner.capturePage = async () => { captures++; throw new Error('host pixels must not be read'); };
  await registry.register(f.owner, { tabId, frameName });
  await assert.rejects(registry.execute({ tabId, mountNonce: frameName, operation: 'tab.screenshot' }), /capture_surface_unavailable/u);
  assert.equal(captures, 0);
});

test('a guest hidden while capture is in flight cannot return stale pixels', async () => {
  const f = fixture();
  let visible = true;
  const registry = new McpAppFrames(() => visible);
  f.owner.executeJavaScriptInIsolatedWorld = async () => ({ x: 0, y: 0, width: 20, height: 20 });
  f.owner.capturePage = async () => {
    visible = false;
    return { toPNG: () => Buffer.from('image'), getSize: () => ({ width: 20, height: 20 }) };
  };
  await registry.register(f.owner, { tabId, frameName });
  await assert.rejects(registry.execute({ tabId, mountNonce: frameName, operation: 'tab.screenshot' }), /capture_surface_unavailable/u);
});
