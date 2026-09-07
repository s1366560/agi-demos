import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test, afterEach } from 'node:test';
const require = createRequire(import.meta.url),
  ts = require('typescript');
const root = new URL('../src/', import.meta.url);
const cache = new Map();
function load(relative) {
  if (cache.has(relative)) return cache.get(relative);
  const url = new URL(relative, root),
    module = { exports: {} };
  cache.set(relative, module.exports);
  const code = ts.transpileModule(readFileSync(url, 'utf8'), {
    fileName: url.pathname,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  new Function('require', 'module', 'exports', code)(
    (name) => {
      if (!name.startsWith('.')) return require(name);
      const relative = new URL(name + '.ts', url).pathname.split('/src/')[1];
      if (relative === 'features/sandbox/nativeSandboxDesktopGrantV2.ts') return load(relative);
      return require('/tmp/agistack-desktop-test-dist/src/' + relative.replace(/\.ts$/, '.js'));
    },
    module,
    module.exports,
  );
  return module.exports;
}
const { openNativeSandboxDesktopGrantV2: open } = load(
  'features/sandbox/nativeSandboxDesktopGrantV2.ts',
);
const authorityModule = load('plugins/desktopProjectSandboxSurfaceAuthorityModuleV2.ts');
const config = {
  mode: 'cloud',
  apiBaseUrl: 'https://api.test/base',
  apiKey: '',
  localApiToken: '',
  tenantId: 't',
  projectId: 'p',
  workspaceId: 'w',
  workspaceRoot: '',
  deviceAuthorizationBaseUrl: 'https://api.test',
};
const descriptor = {
  contract_version: 1,
  project_id: 'p',
  protocol: 'kasmvnc-1',
  proxy_url: '/api/v1/projects/p/sandbox/desktop/proxy/vnc.html',
  auth_mode: 'scoped_http_only_cookie',
};
const frameUrl = 'https://api.test' + descriptor.proxy_url;
const grant = { grantId: 'grant-id', frameName: 'frame-name', frameUrl };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};
const tick = () => new Promise(setImmediate);
function bridge(invoke) {
  globalThis.window = { __MEMSTACK_DESKTOP__: { runtime: 'electron', core: { invoke } } };
}
afterEach(() => delete globalThis.window);

test('browser and Local do not use native grants; Electron missing invoke fails closed', async () => {
  assert.equal(await open(config, descriptor), null);
  bridge(() => {
    throw Error('no Local IPC');
  });
  assert.equal(await open({ ...config, mode: 'local' }, descriptor), null);
  globalThis.window = { __MEMSTACK_DESKTOP__: { runtime: 'electron' } };
  await assert.rejects(open(config, descriptor), /bridge_unavailable/);
});
test('validated native grant uses canonical frame URL and idempotent release', async () => {
  const calls = [];
  bridge(async (command, input) => {
    calls.push({ command, input });
    return grant;
  });
  const value = await open(config, descriptor);
  assert.equal(value.frameName, 'frame-name');
  assert.equal(value.frameUrl, frameUrl);
  const first = value.release(),
    second = value.release();
  assert.equal(first, second);
  await first;
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0].input.descriptor, descriptor);
  assert.equal(calls[0].input.tenantId, 't');
  assert.deepEqual(calls[1].input, { requestId: calls[0].input.requestId, grantId: 'grant-id' });
  assert.ok(!JSON.stringify(calls).includes('apiKey'));
});
test('abort closes pending request before open resolves and closes the late grant without publishing it', async () => {
  const pending = deferred(),
    calls = [];
  bridge(async (command, input) => {
    calls.push({ command, input });
    if (command.endsWith('_open')) return pending.promise;
  });
  const controller = new AbortController();
  const result = open(config, descriptor, controller.signal);
  controller.abort();
  await tick();
  assert.equal(calls[1].command, 'sandbox_desktop_grant_close');
  assert.deepEqual(calls[1].input, { requestId: calls[0].input.requestId });
  pending.resolve(grant);
  await assert.rejects(result, { name: 'AbortError' });
  assert.deepEqual(calls[2].input, { requestId: calls[0].input.requestId, grantId: 'grant-id' });
});
test('already aborted request does not open a native grant', async () => {
  const calls = [];
  bridge(async (...args) => calls.push(args));
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(open(config, descriptor, controller.signal), { name: 'AbortError' });
  assert.deepEqual(calls, []);
});
for (const invalid of [
  { ...grant, frameUrl: frameUrl + '?token=not-allowed' },
  { ...grant, frameUrl: 'https://other.test/path' },
  { ...grant, frameName: '' },
  { ...grant, extra: true },
])
  test('invalid grant response closes authority and never exposes a raw iframe URL', async () => {
    const calls = [];
    bridge(async (command, input) => {
      calls.push({ command, input });
      if (command.endsWith('_open')) return invalid;
    });
    await assert.rejects(open(config, descriptor), /response_invalid/);
    assert.equal(calls.at(-1).command, 'sandbox_desktop_grant_close');
  });
test('open failure is preserved when cleanup also rejects', async () => {
  bridge(async (command) => {
    throw Error(command.endsWith('_open') ? 'primary-open' : 'cleanup');
  });
  await assert.rejects(open(config, descriptor), /primary-open/);
});
function moduleFixture(release = async () => {}) {
  const events = [];
  const available = { availability: 'available', contract_version: 1, reason_code: null };
  const caps = {
    service_version: '0.1.0',
    contract_version: 2,
    terminal_interactive: available,
    terminal_resume: { ...available, contract_version: 2 },
    files: available,
    kasm_vnc: available,
  };
  const operations = authorityModule.createDesktopProjectSandboxSurfaceOperationsV2(() => ({
    async acquireServiceOperationLease() {
      events.push('lease-acquire');
      return {
        status: 'accepted',
        useService: async (use) =>
          use({
            bindOperation: () => ({
              async execute() {
                events.push('descriptor');
                return { status: 'ready', value: { descriptor, frame_url: frameUrl } };
              },
            }),
          }),
        async release() {
          events.push('lease-release');
          await release();
        },
      };
    },
  }));
  return {
    events,
    client: authorityModule.createDesktopProjectSandboxSurfaceClientV2(operations, config),
    caps,
  };
}
test('surface operation retains native grant and parent lease, closes grant before releasing parent', async () => {
  const f = moduleFixture();
  bridge(async (command) => {
    f.events.push(command);
    return grant;
  });
  const result = await f.client.openRemoteDesktop(f.caps, { resolution: '1920x1080' });
  assert.equal(result.value.frame_name, grant.frameName);
  assert.ok(!f.events.includes('lease-release'));
  await result.value.release();
  await result.value.release();
  assert.deepEqual(f.events, [
    'lease-acquire',
    'descriptor',
    'sandbox_desktop_grant_open',
    'sandbox_desktop_grant_close',
    'lease-release',
  ]);
});
test('native open rejection releases parent and cannot return web fallback', async () => {
  const f = moduleFixture();
  bridge(async (command) => {
    if (command.endsWith('_open')) throw Error('grant-denied');
  });
  await assert.rejects(
    f.client.openRemoteDesktop(f.caps, { resolution: '1920x1080' }),
    /grant-denied/,
  );
  assert.equal(f.events.at(-1), 'lease-release');
});
test('native close rejection still releases parent and preserves first cleanup error', async () => {
  const f = moduleFixture(async () => {
    throw Error('parent-release');
  });
  bridge(async (command) => {
    if (command.endsWith('_close')) throw Error('native-close');
    return grant;
  });
  const result = await f.client.openRemoteDesktop(f.caps, { resolution: '1920x1080' });
  await assert.rejects(result.value.release(), /native-close/);
  assert.equal(f.events.at(-1), 'lease-release');
});
test('surface cancellation drains the late grant before parent release', async () => {
  const pending = deferred(),
    f = moduleFixture();
  bridge(async (command) => {
    f.events.push(command);
    if (command.endsWith('_open')) return pending.promise;
  });
  const controller = new AbortController();
  const result = f.client.openRemoteDesktop(f.caps, { resolution: '1920x1080' }, controller.signal);
  await tick();
  controller.abort();
  await tick();
  assert.ok(!f.events.includes('lease-release'));
  pending.resolve(grant);
  await assert.rejects(result, { name: 'AbortError' });
  assert.equal(f.events.at(-1), 'lease-release');
  assert.equal(f.events.filter((x) => x === 'sandbox_desktop_grant_close').length, 2);
});
test('native frame name is applied to iframe identity and surface uses layout cleanup', () => {
  const surface = readFileSync(
    new URL('../src/features/sandbox/RemoteDesktopSurface.tsx', import.meta.url),
    'utf8',
  );
  const hook = readFileSync(
    new URL('../src/features/sandbox/useSandboxRuntimeSurface.ts', import.meta.url),
    'utf8',
  );
  assert.match(surface, /name=\{session.frame_name\}/u);
  assert.match(surface, /key=\{`\$\{session.frame_name \?\? 'web'\}/u);
  assert.match(hook, /useLayoutEffect\(\(\) =>/u);
});
