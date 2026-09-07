import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantAcpAuthorityModuleV2.js`);
const config = () => ({ apiBaseUrl: 'https://api.test', deviceAuthorizationBaseUrl: 'https://api.test', apiKey: 'key', localApiToken: 'local', tenantId: 'tenant-1', projectId: '', workspaceId: '', mode: 'cloud', workspaceRoot: '' });
const scope = () => ({ authority: 'cloud', tenantId: 'tenant-1' });
const agent = () => ({ id: 'agent-1', agentKey: 'agent-key', name: 'Agent', transport: 'stdio', command: 'agent', url: null, enabled: true, available: true, missingEnv: [] });
const snapshot = (marker) => { const data = { membershipRole: 'owner', status: { enabled: true }, runnerPools: [] }; return { scope: scope(), scopeRevision: 1, authority: 'cloud', availability: 'available', reasonCode: null, contractVersion: '4.0.0', allowedActions: ['view'], data, ...data, marker }; };
const client = (load = async () => snapshot('load')) => ({ load, async createAgent() { return agent(); }, async updateAgent() { return agent(); }, async deleteAgent() {}, async testAgent() { return { ok: true }; } });
const service = (value) => Object.freeze({ bindOperation: () => value });
const actions = (value, lifecycle = [], releaseError) => ({ async acquireServiceOperationLease(descriptor) { lifecycle.push(['acquire', descriptor]); return { status: 'accepted', useService: (use) => use(value), async release() { lifecycle.push(['release']); if (releaseError) throw releaseError; } }; } });

test('catalog registers the exact Tenant ACP Provider', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find((item) => item.module_ref === moduleV2.DESKTOP_TENANT_ACP_AUTHORITY_MODULE_REF_V2);
  assert.equal(moduleV2.desktopTenantAcpAuthorityDefinitionV2.contractDigest, entry.contract_digest);
  assert.deepEqual(entry.contract.services.provides, [{ service: moduleV2.DESKTOP_TENANT_ACP_AUTHORITY_SERVICE_V2, version: '1.0.0' }]);
});
test('all ACP operations use exact tenant leases and freeze nested input', async () => {
  const lifecycle = []; let observed;
  const authority = client(); authority.createAgent = async (_scope, input) => { observed = input; return agent(); };
  const operations = moduleV2.createDesktopTenantAcpOperationsV2(() => actions(service(authority), lifecycle));
  const nested = { name: 'Agent', transport: 'stdio', agentKey: 'agent-key', args: ['run'], env: { TOKEN: { source: 'vault' } }, headers: { Authorization: 'secret-ref' }, requiredLabels: { os: 'linux' }, cwdPolicy: { roots: ['/workspace'] } };
  await operations.loadTenantAcp({ config: config(), scope: scope() });
  await operations.createTenantAcpAgent({ config: config(), scope: scope(), agent: nested });
  await operations.updateTenantAcpAgent({ config: config(), scope: scope(), agentKey: 'agent-key', agent: nested });
  await operations.deleteTenantAcpAgent({ config: config(), scope: scope(), agentKey: 'agent-key' });
  await operations.testTenantAcpAgent({ config: config(), scope: scope(), agentKey: 'agent-key', test: { cwd: '/workspace', prompt: 'ping' } });
  assert.equal(Object.isFrozen(observed.env.TOKEN), true); assert.equal(Object.isFrozen(observed.cwdPolicy.roots), true);
  assert.deepEqual(lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value.scope), Array(5).fill({ kind: 'tenant', tenant_id: 'tenant-1' }));
});
test('invalid nested input and malformed response fail before or at the boundary', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantAcpOperationsV2(() => ({ async acquireServiceOperationLease() { acquisitions += 1; return actions(service(client(async () => ({})))).acquireServiceOperationLease({}); } }));
  assert.throws(() => operations.createTenantAcpAgent({ config: config(), scope: scope(), agent: { agentKey: 'key', name: 'Agent', transport: 'stdio', env: { value: Number.NaN } } }), (error) => error.code === 'desktop_tenant_acp_operation_input_invalid');
  assert.equal(acquisitions, 0);
  await assert.rejects(() => operations.loadTenantAcp({ config: config(), scope: scope() }), (error) => error.code === 'desktop_tenant_acp_operation_response_invalid');
});
test('HMR pins work and primary failure outranks release failure', async () => {
  let finish; let current = actions(service(client(() => new Promise((resolve) => { finish = resolve; }))));
  const operations = moduleV2.createDesktopTenantAcpOperationsV2(() => current);
  const pending = operations.loadTenantAcp({ config: config(), scope: scope() }); while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(client(async () => snapshot('new')))); finish(snapshot('old'));
  assert.equal((await pending).marker, 'old'); assert.equal((await operations.loadTenantAcp({ config: config(), scope: scope() })).marker, 'new');
  const primary = new Error('primary'); const failing = moduleV2.createDesktopTenantAcpOperationsV2(() => actions(service(client(async () => { throw primary; })), [], new Error('release')));
  await assert.rejects(() => failing.loadTenantAcp({ config: config(), scope: scope() }), primary);
});
