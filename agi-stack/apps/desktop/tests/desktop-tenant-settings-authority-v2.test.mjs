import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantSettingsAuthorityModuleV2.js`);

const config = () => ({
  apiBaseUrl: 'https://api.test',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: 'key',
  localApiToken: 'local',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  workspaceRoot: '',
  mode: 'cloud',
});
const scope = () => ({ authority: 'cloud', tenantId: 'tenant-1' });
const tenant = () => ({
  id: 'tenant-1',
  name: 'Tenant',
  slug: 'tenant',
  description: null,
  ownerId: 'owner-1',
  plan: 'pro',
  maxProjects: 2,
  maxUsers: 3,
  maxStorage: 4,
  createdAt: 'now',
  updatedAt: null,
});
const snapshot = (marker) => {
  const data = { membershipRole: 'owner', tenant: tenant(), stats: {} };
  return {
    scope: scope(),
    scopeRevision: 2,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    allowedActions: ['view', 'inspect-usage', 'update', 'delete'],
    data,
    ...data,
    marker,
  };
};
const service = (client) => Object.freeze({ bindOperation: () => client });
const actions = (value, lifecycle = [], releaseError) => ({
  async acquireServiceOperationLease(descriptor) {
    lifecycle.push(['acquire', descriptor]);
    return {
      status: 'accepted',
      useService: (use) => use(value),
      async release() {
        lifecycle.push(['release']);
        if (releaseError) throw releaseError;
      },
    };
  },
});

test('catalog registers the exact Tenant Settings Provider', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === moduleV2.DESKTOP_TENANT_SETTINGS_AUTHORITY_MODULE_REF_V2
  );
  assert.equal(
    moduleV2.desktopTenantSettingsAuthorityDefinitionV2.contractDigest,
    entry.contract_digest
  );
  assert.deepEqual(entry.contract.services.provides, [
    {
      service: moduleV2.DESKTOP_TENANT_SETTINGS_AUTHORITY_SERVICE_V2,
      version: '1.0.0',
    },
  ]);
});

test('load, update and delete hold exact tenant leases and freeze inputs', async () => {
  const lifecycle = [];
  const client = Object.freeze({
    async load() {
      return snapshot('load');
    },
    async updateTenant(_scope, update) {
      lifecycle.push(['update', update]);
      return tenant();
    },
    async deleteTenant() {
      lifecycle.push(['delete']);
    },
  });
  const operations = moduleV2.createDesktopTenantSettingsOperationsV2(() =>
    actions(service(client), lifecycle)
  );
  assert.equal(
    (await operations.loadTenantSettings({ config: config(), scope: scope() })).marker,
    'load'
  );
  await operations.updateTenantSettings({
    config: config(),
    scope: scope(),
    update: { name: 'Next' },
  });
  await operations.deleteTenant({ config: config(), scope: scope() });
  assert.deepEqual(
    lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value.scope),
    [
      { kind: 'tenant', tenant_id: 'tenant-1' },
      { kind: 'tenant', tenant_id: 'tenant-1' },
      { kind: 'tenant', tenant_id: 'tenant-1' },
    ]
  );
  assert.deepEqual(
    lifecycle.find(([kind]) => kind === 'update'),
    ['update', { name: 'Next' }]
  );
});

test('malformed inputs and responses fail closed', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantSettingsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return actions(
        service(
          Object.freeze({
            async load() {
              return {};
            },
            async updateTenant() {},
            async deleteTenant() {},
          })
        )
      ).acquireServiceOperationLease({});
    },
  }));
  assert.throws(
    () =>
      operations.updateTenantSettings({
        config: config(),
        scope: scope(),
        update: {},
      }),
    (error) => error.code === 'desktop_tenant_settings_operation_input_invalid'
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => operations.loadTenantSettings({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_settings_operation_response_invalid'
  );
});

test('HMR pins in-flight work and operation errors outrank release errors', async () => {
  let finish;
  let current = actions(
    service(
      Object.freeze({
        load: () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
        async updateTenant() {},
        async deleteTenant() {},
      })
    )
  );
  const operations = moduleV2.createDesktopTenantSettingsOperationsV2(() => current);
  const pending = operations.loadTenantSettings({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(
    service(
      Object.freeze({
        async load() {
          return snapshot('new');
        },
        async updateTenant() {},
        async deleteTenant() {},
      })
    )
  );
  finish(snapshot('old'));
  assert.equal((await pending).marker, 'old');
  assert.equal(
    (await operations.loadTenantSettings({ config: config(), scope: scope() })).marker,
    'new'
  );
  const primary = new Error('primary');
  const failing = moduleV2.createDesktopTenantSettingsOperationsV2(() =>
    actions(
      service(
        Object.freeze({
          async load() {
            throw primary;
          },
          async updateTenant() {},
          async deleteTenant() {},
        })
      ),
      [],
      new Error('release')
    )
  );
  await assert.rejects(
    () => failing.loadTenantSettings({ config: config(), scope: scope() }),
    primary
  );
});
