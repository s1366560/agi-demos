import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const root = new URL('../src/features/runtime/', import.meta.url);
function compile(
  name,
  imports = () => {
    throw new Error('unexpected import');
  },
) {
  const module = { exports: {} };
  const code = ts.transpileModule(readFileSync(new URL(name, root), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  new Function('require', 'module', 'exports', code)(imports, module, module.exports);
  return module.exports;
}
const settlement = compile('desktopWorkbenchSnapshotSettlementV2.ts');
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const tick = async () => {
  for (let i = 0; i < 6; i++) await Promise.resolve();
};
function factoryHarness(snapshot) {
  const dependencies = [];
  let captured;
  let automationConfig;
  const imports = (name) => {
    if (name === './desktopWorkbenchSnapshotSettlementV2') return settlement;
    if (name === './desktopWorkbenchSnapshotJourneyV2')
      return { createWorkbenchSnapshotJourneyV2: () => ({ probe: async () => ({}) }) };
    if (name === './workbenchCapabilityClient')
      return {
        createDesktopWorkbenchCapabilityClient: (automation, config, options) => {
          captured = { automation, config, options };
          return { loadSnapshot: (signal) => snapshot(captured, signal) };
        },
      };
    if (name === '../project-workspaces/projectWorkspacesV2Client')
      return { createProjectWorkspacesV2Client: (config, operations) => ({ config, operations }) };
    return new Proxy(
      {},
      {
        get: (_target, symbol) => {
          if (typeof symbol !== 'string' || !symbol.startsWith('create'))
            throw new Error(`unexpected ${String(symbol)}`);
          return (resolve, configResolver) => {
            const entry = { name: symbol, resolve };
            dependencies.push(entry);
            if (symbol === 'createDesktopAutomationOperationsV2') automationConfig = configResolver;
            return { execute: async (operation) => operation(resolve()) };
          };
        },
      },
    );
  };
  return {
    factory: compile('desktopWorkbenchSnapshotDependenciesV2.ts', imports)
      .createDesktopWorkbenchSnapshotDependenciesV2,
    dependencies,
    captured: () => captured,
    automationConfig: () => automationConfig(),
  };
}
test('all 50 child operation ports and Automation use captured parent actions and frozen config', async () => {
  const first = {};
  let actions = first;
  let resolves = 0;
  const h = factoryHarness(async ({ automation, options }) => {
    await automation.execute((seen) => assert.equal(seen, first));
    for (const [key, operation] of Object.entries(options)) {
      if (key === 'projectWorkspacesClient' || key === 'agentWorkspaceJourneyClient') continue;
      await operation.execute((seen) => assert.equal(seen, first));
    }
    return { ready: true };
  });
  const config = { mode: 'cloud', tenantId: 't1', projectId: 'p1' };
  const client = h.factory(config, () => {
    resolves++;
    return actions;
  });
  config.projectId = 'different';
  actions = {};
  assert.deepEqual(await client.loadSnapshot(), { ready: true });
  assert.equal(h.dependencies.length, 51);
  assert.equal(resolves, 1);
  for (const child of h.dependencies) assert.equal(child.resolve(), first, child.name);
  assert.equal(h.captured().config.projectId, 'p1');
  assert.ok(Object.isFrozen(h.captured().config));
  assert.equal(h.automationConfig(), h.captured().config);
  assert.equal(h.captured().options.projectWorkspacesClient.config, h.captured().config);
});
test('outer failure waits for all in-flight child operations before it escapes', async () => {
  const wait = deferred();
  const failure = new Error('branch rejected');
  let settled = false;
  const h = factoryHarness(async ({ options }) => {
    void options.tenantEventsOperationsV2.execute(() => wait.promise).catch(() => {});
    await tick();
    throw failure;
  });
  const promise = h.factory({}, () => ({})).loadSnapshot();
  void promise.then(
    () => {
      settled = true;
    },
    () => {
      settled = true;
    },
  );
  await tick();
  assert.equal(settled, false);
  wait.resolve('done');
  await assert.rejects(promise, (error) => error === failure);
  assert.equal(settled, true);
});
test('cancellation blocks the next child operation and factory binding cannot be reused after release', async () => {
  const controller = new AbortController();
  let calls = 0;
  const h = factoryHarness(async ({ options }) => {
    await options.tenantEventsOperationsV2.execute(() => {
      calls++;
      controller.abort();
    });
    await options.tenantGenesOperationsV2.execute(() => {
      calls++;
    });
  });
  const client = h.factory({}, () => ({}));
  await assert.rejects(client.loadSnapshot(controller.signal), { name: 'AbortError' });
  assert.equal(calls, 1);
  await assert.rejects(client.loadSnapshot(), /already_used/);
});
test('branch aggregation drains siblings before reporting failure or cancellation', async () => {
  for (const abort of [false, true]) {
    const wait = deferred();
    const controller = new AbortController();
    let settled = false;
    const failure = new Error('rejected');
    const promise = settlement.settleWorkbenchSnapshotBranchesV2(
      [Promise.reject(failure), wait.promise],
      controller.signal,
    );
    void promise.catch(() => {
      settled = true;
    });
    if (abort) controller.abort();
    await tick();
    assert.equal(settled, false);
    wait.resolve(42);
    await assert.rejects(promise, (error) =>
      abort ? error.name === 'AbortError' : error === failure,
    );
  }
});
test('branch aggregation preserves successful tuple order and rejects missing parent actions', async () => {
  assert.deepEqual(
    await settlement.settleWorkbenchSnapshotBranchesV2([Promise.resolve('a'), Promise.resolve(2)]),
    ['a', 2],
  );
  const h = factoryHarness(async () => ({}));
  assert.throws(() => h.factory({}, () => null), /parent_actions_required/);
});

test('real Journey stops before its next HTTP request when cancellation arrives during body decoding', async () => {
  const controller = new AbortController();
  let stream;
  const calls = [];
  const broker = {
    desktopApiAuthenticationAvailable: (config) => Boolean(config.apiKey),
    desktopApiFetch: async (_config, path, init) => {
      calls.push({ path, signal: init.signal });
      return new Response(
        new ReadableStream({
          start(value) {
            stream = value;
          },
        }),
        { headers: { 'content-type': 'application/json' } },
      );
    },
  };
  const api = {
    absoluteUrl: (base, path) => new URL(path, base).toString(),
    desktopApiCredential: (config) => config.apiKey,
    desktopLaunchCapability: () => null,
    DesktopApiError: class extends Error {
      constructor(message, status, payload) {
        super(message);
        this.status = status;
        this.payload = payload;
      }
    },
  };
  const journey = compile('../agent-workspace/agentWorkspaceJourneyAuthorityClient.ts', (name) =>
    name.endsWith('/api/client') ? api : broker,
  );
  const helper = compile('desktopWorkbenchSnapshotJourneyV2.ts', (name) => {
    if (name.endsWith('/cloudRequestBroker')) return broker;
    if (name.endsWith('/agentWorkspaceJourneyAuthorityClient')) return journey;
    if (name === './desktopWorkbenchSnapshotSettlementV2') return settlement;
    throw new Error(name);
  });
  const config = Object.freeze({
    mode: 'cloud',
    apiBaseUrl: 'https://cloud.invalid',
    apiKey: 'test-only',
    tenantId: 't1',
    projectId: 'p1',
    workspaceId: '',
  });
  const promise = helper.createWorkbenchSnapshotJourneyV2(config).probe(controller.signal);
  await tick();
  controller.abort();
  stream.enqueue(new TextEncoder().encode(JSON.stringify({ user_id: 'u1', is_active: true })));
  stream.close();
  await assert.rejects(promise, { name: 'AbortError' });
  assert.deepEqual(
    calls.map((call) => call.path),
    ['/api/v1/auth/me'],
  );
  assert.equal(calls[0].signal, controller.signal);
  await assert.rejects(
    helper.createWorkbenchSnapshotJourneyV2({ ...config, apiKey: '' }).probe(),
    /trusted_session_required/,
  );
  assert.equal(calls.length, 1);
});
