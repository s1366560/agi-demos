import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantAuditAuthorityModuleV2.js`);
const config = () => ({ apiBaseUrl: 'https://api.test', deviceAuthorizationBaseUrl: 'https://api.test', apiKey: 'key', localApiToken: 'local', tenantId: 'tenant-1', projectId: 'project-1', workspaceId: '', mode: 'cloud', workspaceRoot: '' });
const scope = () => ({ authority: 'cloud', tenantId: 'tenant-1' });
const snapshot = (marker) => { const data = { membershipRole: 'owner', entries: [], total: 1, limit: 20, offset: 0, runtimeSummary: { total: 0, actionCounts: {}, executorCounts: {}, familyCounts: {}, isolationModeCounts: {}, latestTimestamp: null }, query: { limit: 20, offset: 0 } }; return { scope: scope(), authority: 'cloud', availability: 'available', reasonCode: null, contractVersion: '4.0.0', allowedActions: ['view', 'export'], authorityRevision: 1, data, ...data, marker }; };
const exported = () => ({ suggestedName: 'audit-logs.csv', mimeType: 'text/csv', blob: new Blob(['ok'], { type: 'text/csv' }) });
const service = (client) => Object.freeze({ bindOperation: () => client });
const actions = (value, lifecycle = [], releaseError) => ({ async acquireServiceOperationLease(descriptor) { lifecycle.push(['acquire', descriptor]); return { status: 'accepted', useService: (use) => use(value), async release() { lifecycle.push(['release']); if (releaseError) throw releaseError; } }; } });

test('catalog registers the exact Tenant Audit Provider', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find((item) => item.module_ref === moduleV2.DESKTOP_TENANT_AUDIT_AUTHORITY_MODULE_REF_V2);
  assert.equal(moduleV2.desktopTenantAuditAuthorityDefinitionV2.contractDigest, entry.contract_digest);
  assert.deepEqual(entry.contract.services.provides, [{ service: moduleV2.DESKTOP_TENANT_AUDIT_AUTHORITY_SERVICE_V2, version: '1.0.0' }]);
});
test('load and binary export hold exact tenant leases', async () => {
  const lifecycle = [];
  const client = { async load() { return snapshot('load'); }, async exportLogs() { return exported(); } };
  const operations = moduleV2.createDesktopTenantAuditOperationsV2(() => actions(service(client), lifecycle));
  assert.equal((await operations.loadTenantAudit({ config: config(), scope: scope() })).marker, 'load');
  assert.equal((await operations.exportTenantAuditLogs({ config: config(), scope: scope(), format: 'csv' })).blob.size, 2);
  assert.deepEqual(lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value.scope), [{ kind: 'tenant', tenant_id: 'tenant-1' }, { kind: 'tenant', tenant_id: 'tenant-1' }]);
});
test('invalid query and malformed binary response fail closed', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantAuditOperationsV2(() => ({ async acquireServiceOperationLease() { acquisitions += 1; return actions(service({ async load() { return {}; }, async exportLogs() { return {}; } })).acquireServiceOperationLease({}); } }));
  assert.throws(() => operations.loadTenantAudit({ config: config(), scope: scope(), query: { limit: 0 } }), (error) => error.code === 'desktop_tenant_audit_operation_input_invalid');
  assert.equal(acquisitions, 0);
  await assert.rejects(() => operations.exportTenantAuditLogs({ config: config(), scope: scope(), format: 'csv' }), (error) => error.code === 'desktop_tenant_audit_operation_response_invalid');
});
test('HMR pins binary work and primary error outranks release error', async () => {
  let finish;
  const client = (load) => ({ load, async exportLogs() { return exported(); } });
  let current = actions(service(client(() => new Promise((resolve) => { finish = resolve; }))));
  const operations = moduleV2.createDesktopTenantAuditOperationsV2(() => current);
  const pending = operations.loadTenantAudit({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(client(async () => snapshot('new')))); finish(snapshot('old'));
  assert.equal((await pending).marker, 'old'); assert.equal((await operations.loadTenantAudit({ config: config(), scope: scope() })).marker, 'new');
  const primary = new Error('primary');
  const failing = moduleV2.createDesktopTenantAuditOperationsV2(() => actions(service(client(async () => { throw primary; })), [], new Error('release')));
  await assert.rejects(() => failing.loadTenantAudit({ config: config(), scope: scope() }), primary);
});
