import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const cache = new Map();
function load(url) {
  if (cache.has(url.href)) return cache.get(url.href);
  const mod = { exports: {} };
  cache.set(url.href, mod.exports);
  const source = ts.transpileModule(readFileSync(url, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  new Function('require', 'module', 'exports', source)(
    (name) => {
      if (name === '@agistack/plugin-runtime')
        return {
          RuntimeV2Error: class extends Error {},
          PLUGIN_MODULE_CATALOG_V2: {
            modules: [
              {
                module_ref: 'builtin://memstack/desktop/browser-bridge-management-authority',
                contract_digest: 'source-test-only',
              },
            ],
          },
        };
      return name.startsWith('.') ? load(new URL(`${name}.ts`, url)) : require(name);
    },
    mod,
    mod.exports,
  );
  return mod.exports;
}
const core = load(
  new URL('../src/plugins/desktopBrowserBridgeManagementAuthorityModuleV2.ts', import.meta.url),
);
const config = { mode: 'local', tenantId: '', projectId: '', workspaceId: '' };
const status = () => ({
  running: true,
  api_base_url: 'http://localhost',
  api_token: 'test-token-never-return',
  workspace_root: '/workspace',
  tool_count: 0,
  tools: [],
  runtime_providers: [],
  config: {
    workspace_root: '/workspace',
    preserved_kernel_field: 'keep',
    browser_bridge: {
      enabled: false,
      port: 0,
      extension_ids: [],
      full_cdp_access_enabled: false,
    },
  },
});
const bridge = {
  enabled: false,
  port: 0,
  brokerConnected: false,
  extensionId: null,
  extensionVersion: null,
  hostVersion: '1',
  protocolMin: 1,
  protocolMax: 1,
  manifests: [],
  registryPath: '/tmp/registry',
  extensionIds: [],
};
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};
const tick = () => new Promise((resolve) => setImmediate(resolve));
function fixture(invoke, options = {}) {
  global.window = { __MEMSTACK_DESKTOP__: { runtime: 'electron', core: { invoke } } };
  let service;
  const events = [];
  core.applyDesktopBrowserBridgeManagementAuthorityV2(
    {
      provide: (_, value) => {
        service = value;
      },
    },
    { strategy: 'native-browser-bridge' },
  );
  const operations = core.createDesktopBrowserBridgeManagementOperationsV2(() => ({
    acquireServiceOperationLease: async (request) => {
      events.push('acquire');
      assert.deepEqual(request.scope, { kind: 'root' });
      if (options.disabled) return { status: 'rejected', reasonCode: 'missing_service' };
      if (options.acquire) await options.acquire;
      return {
        status: 'accepted',
        useService: (callback) => {
          options.callback = callback;
          return callback(options.service ?? service);
        },
        release: async () => {
          events.push('release');
          if (options.releaseError) throw options.releaseError;
        },
      };
    },
  }));
  return {
    events,
    client: core.createDesktopBrowserBridgeManagementClientV2(operations, config),
    options,
  };
}
test('snapshot uses native commands and excludes credentials and unrelated kernel config', async () => {
  const commands = [];
  const { client, events } = fixture(async (command) => {
    commands.push(command);
    return command === 'local_runtime_status' ? status() : bridge;
  });
  const result = await client.loadSnapshot();
  assert.deepEqual(commands, ['local_runtime_status', 'browser_bridge_status']);
  assert.deepEqual(events, ['acquire', 'release']);
  assert.deepEqual(Object.keys(result.runtimeStatus.config), ['browser_bridge']);
  assert.equal(JSON.stringify(result).includes('test-token-never-return'), false);
  assert.equal(JSON.stringify(result).includes('preserved_kernel_field'), false);
});
test('disabled authority and unavailable native runtime fail closed without IPC', async () => {
  let calls = 0;
  const f = fixture(
    async () => {
      calls++;
    },
    { disabled: true },
  );
  await assert.rejects(f.client.install(), /missing_service/);
  assert.equal(calls, 0);
  const g = fixture(async () => {
    calls++;
  });
  delete global.window;
  await assert.rejects(g.client.install(), /native_unavailable/);
  assert.equal(calls, 0);
  assert.deepEqual(g.events, ['acquire', 'release']);
});
test('cancel during native read waits settlement and forbids subsequent configure', async () => {
  const wait = deferred(),
    abort = new AbortController(),
    commands = [];
  const f = fixture(async (command) => {
    commands.push(command);
    return wait.promise;
  });
  const pending = f.client.setEnabled(true, abort.signal);
  await tick();
  abort.abort();
  await tick();
  assert.deepEqual(f.events, ['acquire']);
  wait.resolve(status());
  await assert.rejects(pending, { name: 'AbortError' });
  assert.deepEqual(commands, ['local_runtime_status']);
  assert.deepEqual(f.events, ['acquire', 'release']);
});
test('cancel while install is executing drains native result before lease release', async () => {
  const wait = deferred(),
    abort = new AbortController();
  const f = fixture(() => wait.promise);
  const pending = f.client.install(abort.signal);
  await tick();
  abort.abort();
  await tick();
  assert.deepEqual(f.events, ['acquire']);
  wait.resolve({ installed: [], skipped: [] });
  await assert.rejects(pending, { name: 'AbortError' });
  assert.deepEqual(f.events, ['acquire', 'release']);
});
test('independent clients and generations serialize config read modify write preserving both toggles', async () => {
  let current = status();
  const first = deferred(),
    commands = [];
  let reads = 0;
  const invoke = async (command, args) => {
    commands.push(command);
    if (command === 'local_runtime_status') {
      reads++;
      if (reads === 1) await first.promise;
      return structuredClone(current);
    }
    current = { ...current, config: args.config };
    return structuredClone(current);
  };
  const a = fixture(invoke),
    b = fixture(invoke);
  const p = a.client.setEnabled(true),
    q = b.client.setFullCdpEnabled(true);
  await tick();
  assert.equal(reads, 1);
  first.resolve();
  await Promise.all([p, q]);
  assert.equal(current.config.browser_bridge.enabled, true);
  assert.equal(current.config.browser_bridge.full_cdp_access_enabled, true);
  assert.equal(current.config.preserved_kernel_field, 'keep');
  assert.deepEqual(commands, [
    'local_runtime_status',
    'local_runtime_configure',
    'local_runtime_status',
    'local_runtime_configure',
  ]);
});
test('install and uninstall share queue and cancelled queued operation emits no command', async () => {
  const wait = deferred(),
    commands = [],
    abort = new AbortController();
  const f = fixture(async (command) => {
    commands.push(command);
    return wait.promise;
  });
  const p = f.client.install(),
    q = f.client.uninstall(abort.signal);
  await tick();
  abort.abort();
  assert.deepEqual(commands, ['browser_bridge_install']);
  wait.resolve({ installed: [], skipped: [] });
  await p;
  await assert.rejects(q, { name: 'AbortError' });
  assert.equal(commands.length, 1);
});
test('native rejection remains primary even when release rejects and queue recovers', async () => {
  const native = new Error('native failed'),
    f = fixture(
      async () => {
        throw native;
      },
      { releaseError: new Error('release failed') },
    );
  await assert.rejects(f.client.install(), (e) => e === native);
  const next = fixture(async () => ({ removed: ['Chrome'] }));
  assert.deepEqual(await next.client.uninstall(), { removed: ['Chrome'] });
});
test('late acquired lease and escaped callback cannot issue native commands', async () => {
  const wait = deferred(),
    abort = new AbortController();
  let calls = 0;
  const f = fixture(
    async () => {
      calls++;
      return { removed: [] };
    },
    { acquire: wait.promise },
  );
  const p = f.client.uninstall(abort.signal);
  abort.abort();
  wait.resolve();
  await assert.rejects(p, { name: 'AbortError' });
  assert.equal(calls, 0);
  await assert.rejects(
    f.options.callback({
      bindOperation() {
        throw new Error('must not bind');
      },
    }),
    /operation_released/,
  );
});
test('invalid boolean and pre-aborted input acquire no lease', async () => {
  const f = fixture(async () => {
    throw new Error('no native');
  });
  const abort = new AbortController();
  abort.abort();
  await assert.rejects(f.client.setEnabled('true'), /contract_invalid/);
  await assert.rejects(f.client.install(abort.signal), { name: 'AbortError' });
  assert.deepEqual(f.events, []);
});
test('malformed native responses fail rather than manufacture successful data', async () => {
  const f = fixture(async () => ({}));
  await assert.rejects(f.client.loadSnapshot(), /contract_invalid/);
  await assert.rejects(f.client.install(), /contract_invalid/);
});

test('replacement provider response is validated and strips non-contract secret fields inside lease', async () => {
  const service = {
    bindOperation: () => ({
      execute: async () => ({ removed: ['Chrome'], api_token: 'must-not-return' }),
    }),
  };
  const f = fixture(async () => assert.fail('no IPC'), { service });
  assert.deepEqual(await f.client.uninstall(), { removed: ['Chrome'] });
  const invalid = fixture(async () => assert.fail('no IPC'), {
    service: { bindOperation: () => ({ execute: async () => ({ removed: 'bad' }) }) },
  });
  await assert.rejects(invalid.client.uninstall(), /contract_invalid/);
  assert.deepEqual(invalid.events, ['acquire', 'release']);
});
