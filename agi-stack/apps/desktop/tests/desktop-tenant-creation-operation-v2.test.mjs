import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopTenantCreationAuthorityUnavailableErrorV2,
  createDesktopTenantCreationOperationsV2,
} = require(`${ROOT}/src/plugins/desktopTenantCreationAuthorityModuleV2.js`);
const { TenantCreationError } = require(`${ROOT}/src/features/tenant-creation/tenantCreationClient.js`);
const { DEFAULT_CONFIG } = require(`${ROOT}/src/types.js`);

const config = (overrides = {}) => ({
  ...DEFAULT_CONFIG, apiBaseUrl: 'https://cloud.memstack.test', apiKey: 'session',
  mode: 'cloud', tenantId: '', projectId: '', workspaceId: '', workspaceRoot: '', ...overrides,
});
const record = () => Object.freeze({
  id: 'tenant-2', name: 'New Tenant', slug: 'new-tenant', description: '', owner_id: 'user-1',
  plan: 'free', max_projects: 1, max_users: 1, max_storage: 0,
  created_at: '2026-09-04T00:00:00Z', updated_at: null,
});

test('Tenant Creation freezes input and pins one root generation lease', async () => {
  const lifecycle = [];
  const received = [];
  const operations = createDesktopTenantCreationOperationsV2(() => ({
    async acquireServiceOperationLease(request) {
      lifecycle.push(['acquire', request]);
      return { status: 'accepted', digest: 'tenant-create', useService(operation) {
        return operation(Object.freeze({ bindOperation(boundConfig) {
          received.push(boundConfig);
          return Object.freeze({ async create(input, signal) { received.push(input, signal); return record(); } });
        } }));
      }, async release() { lifecycle.push(['release']); } };
    },
  }));
  const runtime = config();
  const draft = { name: ' New Tenant ', description: ' ', plan: 'free' };
  const controller = new AbortController();
  const pending = operations.createTenant({ config: runtime, input: draft, signal: controller.signal });
  runtime.apiKey = 'mutated'; draft.name = 'mutated';
  const result = await pending;
  assert.equal(Object.isFrozen(result), true);
  assert.deepEqual(lifecycle, [
    ['acquire', { service: 'service:desktop-renderer.tenant-creation-authority', version: '1.0.0', scope: { kind: 'root' } }],
    ['release'],
  ]);
  assert.equal(received[0].apiKey, 'session');
  assert.deepEqual(received[1], { name: 'New Tenant', description: '', plan: 'free' });
  assert.equal(received[2], controller.signal);
});

test('Local and invalid drafts fail before generation acquisition', () => {
  let acquired = 0;
  const operations = createDesktopTenantCreationOperationsV2(() => ({
    async acquireServiceOperationLease() { acquired += 1; assert.fail('must not acquire'); },
  }));
  assert.throws(() => operations.createTenant({ config: config({ mode: 'local' }), input: { name: 'X', description: '', plan: 'free' } }),
    (error) => error instanceof TenantCreationError && error.reasonCode === 'local_tenant_creation_not_applicable');
  assert.throws(() => operations.createTenant({ config: config(), input: { name: ' ', description: '', plan: 'free' } }),
    (error) => error instanceof TenantCreationError && error.reasonCode === 'tenant_creation_name_required');
  assert.equal(acquired, 0);
});

test('missing and malformed services fail closed and preserve primary errors', async () => {
  assert.throws(() => createDesktopTenantCreationOperationsV2(() => null).createTenant({ config: config(), input: { name: 'X', description: '', plan: 'free' } }),
    (error) => error instanceof DesktopTenantCreationAuthorityUnavailableErrorV2);
  const primary = new Error('primary');
  await assert.rejects(createDesktopTenantCreationOperationsV2(() => ({
    async acquireServiceOperationLease() { return { status: 'accepted', digest: 'x', useService(operation) { return operation({ bindOperation: () => ({ create: async () => { throw primary; } }) }); }, async release() { throw new Error('release'); } }; },
  })).createTenant({ config: config(), input: { name: 'X', description: '', plan: 'free' } }), primary);
  await assert.rejects(createDesktopTenantCreationOperationsV2(() => ({
    async acquireServiceOperationLease() { return { status: 'accepted', digest: 'x', useService(operation) { return operation({}); }, async release() {} }; },
  })).createTenant({ config: config(), input: { name: 'X', description: '', plan: 'free' } }),
    (error) => error instanceof RuntimeV2Error && error.code === 'desktop_tenant_creation_service_invalid');
});
