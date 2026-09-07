import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantGovernanceAuthorityModuleV2.js`);
const config = () => ({ apiBaseUrl: 'https://api.test', deviceAuthorizationBaseUrl: 'https://api.test', apiKey: 'key', localApiToken: 'local', tenantId: 'tenant-1', projectId: '', workspaceId: '', mode: 'cloud', workspaceRoot: '' });
const scope = () => ({ authority: 'cloud', tenantId: 'tenant-1' });
const snapshot = (marker) => { const data = { membershipRole: 'owner', members: [], invitations: [], pendingInvitationTotal: 0 }; return { scope: scope(), authority: 'cloud', availability: 'available', reasonCode: null, contractVersion: '4.0.0', allowedActions: ['view', 'list'], data, ...data, marker }; };
const invitation = () => ({ id: 'invite-1', tenantId: 'tenant-1', email: 'member@example.com', role: 'member', status: 'pending', invitedBy: 'owner-1', expiresAt: '2026-09-06T00:00:00Z', createdAt: '2026-09-05T00:00:00Z' });
const service = (client) => Object.freeze({ bindOperation: () => client });
const actions = (value, lifecycle = [], releaseError) => ({ async acquireServiceOperationLease(descriptor) { lifecycle.push(['acquire', descriptor]); return { status: 'accepted', useService: (use) => use(value), async release() { lifecycle.push(['release']); if (releaseError) throw releaseError; } }; } });

test('catalog registers the exact Tenant Governance Provider', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find((item) => item.module_ref === moduleV2.DESKTOP_TENANT_GOVERNANCE_AUTHORITY_MODULE_REF_V2);
  assert.equal(moduleV2.desktopTenantGovernanceAuthorityDefinitionV2.contractDigest, entry.contract_digest);
  assert.deepEqual(entry.contract.services.provides, [{ service: moduleV2.DESKTOP_TENANT_GOVERNANCE_AUTHORITY_SERVICE_V2, version: '1.0.0' }]);
});
test('all governance operations hold exact tenant leases', async () => {
  const lifecycle = [];
  const client = { async load() { return snapshot('load'); }, async invite() { return invitation(); }, async changeRole() {}, async removeMember() {} };
  const operations = moduleV2.createDesktopTenantGovernanceOperationsV2(() => actions(service(client), lifecycle));
  await operations.loadTenantGovernance({ config: config(), scope: scope() });
  await operations.inviteTenantMember({ config: config(), scope: scope(), invitation: { email: 'member@example.com', role: 'member' } });
  await operations.changeTenantMemberRole({ config: config(), scope: scope(), userId: 'user-1', role: 'admin' });
  await operations.removeTenantMember({ config: config(), scope: scope(), userId: 'user-1' });
  assert.deepEqual(lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value.scope), Array(4).fill({ kind: 'tenant', tenant_id: 'tenant-1' }));
});
test('invalid input and malformed responses fail closed', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantGovernanceOperationsV2(() => ({ async acquireServiceOperationLease() { acquisitions += 1; return actions(service({ async load() { return {}; }, async invite() { return {}; }, async changeRole() {}, async removeMember() {} })).acquireServiceOperationLease({}); } }));
  assert.throws(() => operations.removeTenantMember({ config: config(), scope: scope(), userId: ' ' }), (error) => error.code === 'desktop_tenant_governance_operation_input_invalid');
  assert.equal(acquisitions, 0);
  await assert.rejects(() => operations.loadTenantGovernance({ config: config(), scope: scope() }), (error) => error.code === 'desktop_tenant_governance_operation_response_invalid');
});
test('HMR pins work and primary failure outranks release failure', async () => {
  let finish;
  const client = (load) => ({ load, async invite() { return invitation(); }, async changeRole() {}, async removeMember() {} });
  let current = actions(service(client(() => new Promise((resolve) => { finish = resolve; }))));
  const operations = moduleV2.createDesktopTenantGovernanceOperationsV2(() => current);
  const pending = operations.loadTenantGovernance({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(client(async () => snapshot('new')))); finish(snapshot('old'));
  assert.equal((await pending).marker, 'old'); assert.equal((await operations.loadTenantGovernance({ config: config(), scope: scope() })).marker, 'new');
  const primary = new Error('primary');
  const failing = moduleV2.createDesktopTenantGovernanceOperationsV2(() => actions(service(client(async () => { throw primary; })), [], new Error('release')));
  await assert.rejects(() => failing.loadTenantGovernance({ config: config(), scope: scope() }), primary);
});
