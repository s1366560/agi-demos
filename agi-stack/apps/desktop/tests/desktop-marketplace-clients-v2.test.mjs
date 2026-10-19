import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopPluginMarketplaceOperationsV2,
  withDesktopPluginMarketplaceCatalogOperationV2,
  withDesktopPluginMarketplaceManagementOperationV2,
  DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2,
  DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopPluginMarketplaceAuthorityModulesV2.js');

const config = Object.freeze({
  mode: 'local', apiBaseUrl: 'http://localhost:10101', apiKey: '', localApiToken: 'fixture-token',
  deviceAuthorizationBaseUrl: '', tenantId: 'tenant-a', projectId: 'project-a',
  workspaceId: '', workspaceRoot: '',
});

function runtime() {
  const calls = [];
  const leases = [];
  const releases = [];
  const disabled = new Set();
  const methods = (names) => Object.fromEntries(names.map((name) => [name, async (...args) => {
    calls.push({ name, args });
    return { operation: name };
  }]));
  const catalog = {
    instances: methods(['list']),
    marketplaceV3: methods(['catalog', 'sources', 'installations', 'oauthStatus', 'cache']),
    localPlugins: methods(['list']),
  };
  const management = {
    instances: methods(['apply']),
    marketplaceV3: methods(['addSource', 'removeSource', 'preflight', 'install', 'action', 'oauthAction', 'cleanupCache']),
    localPlugins: methods(['inspect', 'install', 'control']),
  };
  const actions = {
    acquireServiceOperationLease: async (request) => {
      leases.push(request.service);
      if (disabled.has(request.service)) return { status: 'rejected', reasonCode: 'missing_service' };
      const authority = request.service === DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2 ? catalog : management;
      return {
        status: 'admitted',
        useService: (run) => run({ bindOperation: (snapshot) => {
          assert.deepEqual(snapshot, config);
          assert.equal(Object.isFrozen(snapshot), true);
          return authority;
        } }),
        release: async () => { releases.push(request.service); },
      };
    },
  };
  return { calls, leases, releases, disabled, actions, catalog, management };
}

test('every V3 and local signed method acquires the owning service and forwards cancellation', async () => {
  const host = runtime();
  const operations = createDesktopPluginMarketplaceOperationsV2(() => host.actions);
  const marketplace = operations.marketplaceClient(config);
  const local = operations.localPluginClient(config);
  const instances = operations.instanceClient(config);
  const signal = new AbortController().signal;
  const cases = [
    [instances, 'list', [signal], 'catalog'],
    [instances, 'apply', [3, [{entry_id: 'feature', enabled: false}], signal], 'management'],
    [marketplace, 'catalog', [signal], 'catalog'],
    [marketplace, 'sources', [signal], 'catalog'],
    [marketplace, 'installations', [signal], 'catalog'],
    [marketplace, 'oauthStatus', ['installation', 'service', signal], 'catalog'],
    [marketplace, 'cache', [signal], 'catalog'],
    [marketplace, 'addSource', [{ name: 'fixture' }, signal], 'management'],
    [marketplace, 'removeSource', ['source', signal], 'management'],
    [marketplace, 'preflight', [{ id: 'plugin' }, signal], 'management'],
    [marketplace, 'install', [{ id: 'preflight' }, 'idempotency', signal], 'management'],
    [marketplace, 'action', [{ id: 'installation' }, 'disable', {}, 'idempotency', signal], 'management'],
    [marketplace, 'oauthAction', ['installation', 'service', 'cancel', {}, 'idempotency', signal], 'management'],
    [marketplace, 'cleanupCache', ['idempotency', signal], 'management'],
    [local, 'list', [signal], 'catalog'],
    [local, 'inspect', ['archive', signal], 'management'],
    [local, 'install', [{}, 'archive', ['tool.fixture'], signal], 'management'],
    [local, 'control', ['disable', {}, signal], 'management'],
  ];
  for (const [client, method, args, owner] of cases) {
    assert.deepEqual(await client[method](...args), { operation: method });
    assert.equal(host.calls.at(-1).name, method);
    assert.deepEqual(host.calls.at(-1).args, args);
    const service = owner === 'catalog' ? DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2 : DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2;
    assert.equal(host.leases.at(-1), service);
    assert.equal(host.releases.at(-1), service);
  }
  assert.equal(host.releases.length, cases.length);
});

test('retained UI clients cannot dispatch when their provider is disabled, and recover through the new provider', async () => {
  const host = runtime();
  let actions = host.actions;
  const client = createDesktopPluginMarketplaceOperationsV2(() => actions).marketplaceClient(config);
  host.disabled.add(DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2);
  await assert.rejects(client.action({ id: 'installation' }, 'disable'), /missing_service/);
  assert.equal(host.calls.length, 0);
  await client.catalog();
  assert.equal(host.calls.length, 1);
  actions = null;
  assert.throws(() => client.catalog(), /desktop_renderer_generation_actions_unavailable/);
  actions = host.actions;
  host.disabled.clear();
  await client.action({ id: 'installation' }, 'disable');
  assert.equal(host.calls.at(-1).name, 'action');
});

test('nested V3 and local clients escape no authority after lease release', async () => {
  const host = runtime();
  for (const [run, nested, method, args] of [
    [withDesktopPluginMarketplaceCatalogOperationV2, 'instances', 'list', []],
    [withDesktopPluginMarketplaceManagementOperationV2, 'instances', 'apply', [1, []]],
    [withDesktopPluginMarketplaceCatalogOperationV2, 'marketplaceV3', 'catalog', []],
    [withDesktopPluginMarketplaceCatalogOperationV2, 'localPlugins', 'list', []],
    [withDesktopPluginMarketplaceManagementOperationV2, 'marketplaceV3', 'cleanupCache', []],
    [withDesktopPluginMarketplaceManagementOperationV2, 'localPlugins', 'inspect', ['archive']],
  ]) {
    const escaped = await run(host.actions, config, (authority) => authority[nested]);
    assert.throws(() => escaped[method](...args), /operation has been released/);
  }
  assert.equal(host.calls.length, 0);
  assert.equal(host.releases.length, 6);
});

test('ordinary provider disable drains an already admitted mutation and rejects the next mutation', async () => {
  const host = runtime();
  let settle;
  host.management.marketplaceV3.action = () => new Promise((resolve) => { settle = resolve; });
  const client = createDesktopPluginMarketplaceOperationsV2(() => host.actions).marketplaceClient(config);
  const pending = client.action({ id: 'installation' }, 'disable');
  await Promise.resolve();
  host.disabled.add(DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2);
  await assert.rejects(client.action({ id: 'installation' }, 'enable'), /missing_service/);
  assert.equal(host.releases.length, 0);
  settle({ status: 'disabled' });
  assert.deepEqual(await pending, { status: 'disabled' });
  assert.equal(host.releases.length, 1);
});
