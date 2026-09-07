import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopUnifiedRuntimesAuthorityModuleV2.js`);

const config = (mode = 'cloud') => ({ mode, apiBaseUrl: 'https://api.test', deviceAuthorizationBaseUrl: 'https://api.test', apiKey: 'key', localApiToken: 'local', tenantId: 'tenant-1', projectId: 'project-1', workspaceId: 'workspace-1', workspaceRoot: '/workspace' });
const scope = (mode = 'cloud') => ({ authority: mode, tenantId: 'tenant-1', projectId: 'project-1' });
const poolService = Object.freeze({ bindOperation: () => Object.freeze({ getStatus: async () => ({ status: 'healthy', totalInstances: 0, activeInstances: 0, idleInstances: 0, maxInstances: 1, updatedAt: '2026-01-01T00:00:00Z' }), listInstances: async () => ({ items: [], page: 1, pageSize: 100, total: 0, totalPages: 0 }) }) });

function actions(service, events = [], releaseError) {
  return { async acquireServiceOperationLease(descriptor) { events.push(['acquire', descriptor]); return { status: 'accepted', useService: async (use) => use(service), release: async () => { events.push(['release']); if (releaseError) throw releaseError; } }; } };
}

test('catalog contract requires the same-generation runtime pool provider', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find((item) => item.module_ref === moduleV2.DESKTOP_UNIFIED_RUNTIMES_AUTHORITY_MODULE_REF_V2);
  assert.equal(moduleV2.desktopUnifiedRuntimesAuthorityDefinitionV2.contractDigest, entry.contract_digest);
  const provided = [];
  moduleV2.applyDesktopUnifiedRuntimesAuthorityV2({ require(alias, version) { assert.equal(alias, 'runtime_pool'); assert.equal(version, '1.0.0'); return poolService; }, provide(key, value) { provided.push([key, value]); } }, { strategy: 'desktop-api-fetch' });
  assert.equal(provided[0][0], moduleV2.DESKTOP_UNIFIED_RUNTIMES_AUTHORITY_SERVICE_V2);
  assert.throws(() => moduleV2.applyDesktopUnifiedRuntimesAuthorityV2({ require() { return poolService; }, provide() {} }, { strategy: 'bad' }));
});

test('probe is generation leased and preserves Cloud and Local scope', async () => {
  const events = [];
  const service = Object.freeze({ bindOperation() { throw new Error('not used'); }, probe(value) { return Object.freeze({ availability: 'degraded', reason_code: value.mode === 'cloud' ? 'global_pool_capacity_not_available_in_tenant_scope' : 'local_pool_not_applicable_sidecar_projection', service_version: '0.1.0', contract_version: '3.0.0', allowed_actions: [], scope: { tenant_id: value.tenantId, project_id: value.mode === 'local' ? value.projectId : null, workspace_id: null, instance_id: null }, authority_revision: null }); } });
  const operations = moduleV2.createDesktopUnifiedRuntimesOperationsV2(() => actions(service, events));
  assert.equal((await operations.probe({ config: config(), scope: scope() })).availability, 'degraded');
  assert.deepEqual(events[0][1].scope, { kind: 'tenant', tenant_id: 'tenant-1' });
  assert.equal(events.at(-1)[0], 'release');
});

test('HMR pins operations and release errors do not replace primary failures', async () => {
  let finish;
  const old = Object.freeze({ bindOperation: () => Object.freeze({ getPoolStatus: () => new Promise((resolve) => { finish = resolve; }) }), probe() {} });
  const next = Object.freeze({ bindOperation: () => Object.freeze({ getPoolStatus: async () => 'next' }), probe() {} });
  let current = actions(old);
  const operations = moduleV2.createDesktopUnifiedRuntimesOperationsV2(() => current);
  const pending = operations.getPoolStatus({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(next);
  finish('old');
  assert.equal(await pending, 'old');
  assert.equal(await operations.getPoolStatus({ config: config(), scope: scope() }), 'next');
  const primary = new Error('primary');
  const release = new Error('release');
  const failing = moduleV2.createDesktopUnifiedRuntimesOperationsV2(() => actions(Object.freeze({ bindOperation: () => Object.freeze({ getPoolStatus: async () => { throw primary; } }), probe() {} }), [], release));
  await assert.rejects(() => failing.getPoolStatus({ config: config(), scope: scope() }), primary);
});
