import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
function harness(overrides = {}, page = false) {
  const slots = [];
  let cursor = 0;
  let effects = [];
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useState(value) {
      const i = cursor++;
      slots[i] ??= { value: typeof value === 'function' ? value() : value };
      return [
        slots[i].value,
        (v) => {
          slots[i].value = typeof v === 'function' ? v(slots[i].value) : v;
        },
      ];
    },
    useRef(value) {
      return (slots[cursor++] ??= { current: value });
    },
    useMemo(fn, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps)) slots[i] = { deps, value: fn() };
      return slots[i].value;
    },
    useCallback(fn, deps) {
      return react.useMemo(() => fn, deps);
    },
    useEffect(effect, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps))
        effects.push(() => {
          slots[i]?.cleanup?.();
          slots[i] = { deps, effect, cleanup: effect() };
        });
    },
  };
  react.useLayoutEffect = react.useEffect;
  const cache = new Map();
  const window = {
    __MEMSTACK_DESKTOP__: { core: { invoke: async () => ({ config: {} }) } },
    setInterval: () => 1,
    clearInterval() {},
  };
  function load(url) {
    if (cache.has(url.href)) return cache.get(url.href);
    const module = { exports: {} };
    cache.set(url.href, module.exports);
    const code = ts.transpileModule(readFileSync(url, 'utf8'), {
      fileName: url.pathname,
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    new Function('require', 'module', 'exports', 'window', 'setTimeout', 'clearTimeout', code)(
      (name) => {
        if (name === 'react') return react;
        if (name === 'react/jsx-runtime')
          return {
            jsx: (type, props) => ({ type, props }),
            jsxs: (type, props) => ({ type, props }),
          };
        if (name === '../../i18n') return { useI18n: () => ({ t: (key) => key }) };
        if (name.endsWith('.css')) return {};
        if (
          name === './useBrowserIntegrationManagementV2' ||
          name === './useBrowserBridgeManagementV2'
        )
          return load(new URL(`${name}.ts`, url));
        return new Proxy({}, { get: (_, key) => key });
      },
      module,
      module.exports,
      window,
      () => 1,
      () => {},
    );
    return module.exports;
  }
  const calls = { lists: 0, saves: [], deletes: [], bridgeLoads: 0 };
  // This fixture keeps the real page and both hooks. Management lifecycle races
  // remain covered by browser-bridge-management-lifecycle.test.mjs.
  const browserBridgeManagementClientV2 = {
    async loadSnapshot(signal) {
      assert.ok(signal instanceof AbortSignal);
      calls.bridgeLoads++;
      return {
        runtimeStatus: { config: { browser_bridge: { enabled: false } } },
        bridgeStatus: { enabled: false, brokerConnected: false, port: 0 },
      };
    },
    async setEnabled() {
      assert.fail('unexpected bridge toggle in audit rendering test');
    },
    async setFullCdpEnabled() {
      assert.fail('unexpected CDP toggle in audit rendering test');
    },
    async install() {
      assert.fail('unexpected install in audit rendering test');
    },
    async uninstall() {
      assert.fail('unexpected uninstall in audit rendering test');
    },
  };
  const client = {
    async listBrowserOriginGrants() {
      return [];
    },
    async revokeBrowserOriginGrant() {},
    async listBrowserCapabilityGrants() {
      return [];
    },
    async revokeBrowserCapabilityGrant() {},
    async listBrowserSiteCredentials() {
      calls.lists++;
      return [];
    },
    async upsertBrowserSiteCredential(...args) {
      calls.saves.push(args);
      return {};
    },
    async deleteBrowserSiteCredential(...args) {
      calls.deletes.push(args);
      return {};
    },
    async listBrowserAuditEntries() {
      return [];
    },
    ...overrides,
  };
  let config = { mode: 'local', tenantId: 'tenant-one', projectId: 'project-one' };
  let currentClient = client;
  const hook = page
    ? load(new URL('../src/features/settings/BrowserIntegrationSettingsPage.tsx', import.meta.url))
        .BrowserIntegrationSettingsPage
    : load(
        new URL('../src/features/settings/useBrowserIntegrationManagementV2.ts', import.meta.url),
      ).useBrowserIntegrationManagementV2;
  function render(next = {}) {
    config = next.config ?? config;
    currentClient = next.client ?? currentClient;
    cursor = 0;
    effects = [];
    const result = page
      ? hook({ config, browserIntegrationClientV2: currentClient, browserBridgeManagementClientV2 })
      : hook(currentClient, config);
    for (const effect of effects) effect();
    return result;
  }
  return {
    render,
    calls,
    client,
    unmount() {
      for (const slot of slots) slot?.cleanup?.();
    },
    replay() {
      for (const slot of slots)
        if (slot?.effect) {
          slot.cleanup?.();
          slot.cleanup = slot.effect();
        }
    },
  };
}
const flush = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};
function draft(h, value) {
  const result = h.render();
  result.setCredentialOrigin('https://example.test');
  result.setCredentialUsername('test-user');
  result.setCredentialPassword(value);
  return h.render();
}
for (const outcome of ['resolve', 'reject']) {
  test(`old credential save ${outcome} cannot clear or overwrite the next context draft`, async () => {
    const wait = deferred();
    let signal;
    const h = harness({
      async upsertBrowserSiteCredential(input, value) {
        signal = value;
        return wait.promise;
      },
    });
    h.render();
    await flush();
    const pending = draft(h, 'old-synthetic-password').saveSiteCredential();
    h.render({ config: { mode: 'local', tenantId: 'tenant-two', projectId: 'project-two' } });
    const next = draft(h, 'new-synthetic-password');
    assert.equal(signal.aborted, true);
    if (outcome === 'resolve') wait.resolve({});
    else wait.reject(new Error('old failure'));
    await pending;
    const result = h.render();
    assert.equal(result.credentialPassword, next.credentialPassword);
    assert.equal(result.credentialOrigin, 'https://example.test');
    assert.equal(result.siteCredentialsError, null);
    assert.equal(result.credentialSaving, false);
  });
}
test('unmount aborts saving and prevents its follow-up credential reload', async () => {
  const wait = deferred();
  let signal;
  const h = harness({
    async upsertBrowserSiteCredential(input, value) {
      signal = value;
      return wait.promise;
    },
  });
  h.render();
  await flush();
  const pending = draft(h, 'synthetic-password').saveSiteCredential();
  const before = h.calls.lists;
  h.unmount();
  wait.resolve({});
  await pending;
  assert.equal(signal.aborted, true);
  assert.equal(h.calls.lists, before);
});
test('current credential save passes password only to mutation, clears draft and reloads metadata', async () => {
  const h = harness();
  h.render();
  await flush();
  await draft(h, 'synthetic-password').saveSiteCredential();
  assert.deepEqual(h.calls.saves[0][0], {
    origin: 'https://example.test',
    username: 'test-user',
    password: 'synthetic-password',
  });
  assert.ok(h.calls.saves[0][1] instanceof AbortSignal);
  assert.equal(h.render().credentialPassword, '');
  assert.equal(h.calls.lists, 2);
});
test('StrictMode replay ignores the old response and still loads the new lifetime', async () => {
  const requests = [];
  const h = harness({
    listBrowserSiteCredentials(signal) {
      const wait = deferred();
      requests.push({ signal, ...wait });
      return wait.promise;
    },
  });
  h.render();
  h.replay();
  assert.equal(requests.length, 2);
  assert.equal(requests[0].signal.aborted, true);
  requests[1].resolve([{ credential_id: 'new' }]);
  await flush();
  requests[0].resolve([{ credential_id: 'old' }]);
  await flush();
  assert.deepEqual(h.render().siteCredentials, [{ credential_id: 'new' }]);
});
test('a stale audit filter response cannot replace a newer filter result', async () => {
  const requests = [];
  const h = harness({
    listBrowserAuditEntries(input, signal) {
      const wait = deferred();
      requests.push({ ...wait, input, signal });
      return wait.promise;
    },
  });
  h.render();
  const first = h.render().refreshAuditEntries('https://first.test');
  const second = h.render().refreshAuditEntries('https://second.test');
  requests[2].resolve([{ outcome: 'denied', origin: 'https://second.test' }]);
  await second;
  requests[1].resolve([]);
  await first;
  requests[0].resolve([]);
  await flush();
  assert.equal(h.render().auditEntries[0].outcome, 'denied');
});
for (const [outcome, color] of [
  ['denied', 'red'],
  ['declined', 'red'],
  ['consent_required', 'amber'],
]) {
  test(`the real page renders ${outcome} without rejecting the audit list`, async () => {
    const h = harness(
      {
        async listBrowserAuditEntries() {
          return [
            {
              id: 'audit-one',
              outcome,
              origin: 'https://example.test',
              created_at: '2026-09-05T00:00:00Z',
              action: 'navigate',
            },
          ];
        },
      },
      true,
    );
    h.render();
    await flush();
    const tree = h.render();
    const badges = [];
    function visit(node) {
      if (!node || typeof node !== 'object') return;
      if (node.type === 'Badge') badges.push(node.props);
      for (const value of Object.values(node)) {
        if (Array.isArray(value)) value.forEach(visit);
        else visit(value);
      }
    }
    visit(tree);
    assert.equal(h.calls.bridgeLoads, 1);
    h.unmount();
    assert.ok(
      badges.some(
        (badge) =>
          badge.color === color && badge.children === `settings.browserAuditOutcome.${outcome}`,
      ),
    );
  });
}
