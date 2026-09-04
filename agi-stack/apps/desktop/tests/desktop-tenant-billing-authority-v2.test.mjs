import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantBillingAuthorityModuleV2.js`);
const config = () => ({
  apiBaseUrl: 'https://api.test',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: 'key',
  localApiToken: 'local',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode: 'cloud',
  workspaceRoot: '',
});
const scope = () => ({ authority: 'cloud', tenantId: 'tenant-1' });
const tenant = () => ({ id: 'tenant-1', name: 'Tenant', plan: 'pro', storageLimit: 10 });
const snapshot = (marker) => {
  const data = {
    membershipRole: 'owner',
    tenant: tenant(),
    usage: { projects: 1, memories: 2, users: 3, storage: 4 },
    invoices: [],
  };
  return {
    scope: scope(),
    authority: 'cloud',
    availability: 'degraded',
    reasonCode: 'tenant_billing_invoice_download_file_ipc_unavailable',
    contractVersion: '4.0.0',
    allowedActions: ['view', 'upgrade-plan'],
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

test('catalog registers the exact Tenant Billing Provider', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === moduleV2.DESKTOP_TENANT_BILLING_AUTHORITY_MODULE_REF_V2
  );
  assert.equal(
    moduleV2.desktopTenantBillingAuthorityDefinitionV2.contractDigest,
    entry.contract_digest
  );
  assert.deepEqual(entry.contract.services.provides, [
    { service: moduleV2.DESKTOP_TENANT_BILLING_AUTHORITY_SERVICE_V2, version: '1.0.0' },
  ]);
});
test('load and owner mutation hold exact tenant leases and freeze the plan', async () => {
  const lifecycle = [];
  const client = Object.freeze({
    async load() {
      return snapshot('load');
    },
    async upgradePlan(_scope, plan) {
      lifecycle.push(['upgrade', plan]);
      return tenant();
    },
  });
  const operations = moduleV2.createDesktopTenantBillingOperationsV2(() =>
    actions(service(client), lifecycle)
  );
  assert.equal(
    (await operations.loadTenantBilling({ config: config(), scope: scope() })).marker,
    'load'
  );
  await operations.upgradeTenantBillingPlan({
    config: config(),
    scope: scope(),
    plan: 'enterprise',
  });
  assert.deepEqual(
    lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value.scope),
    [
      { kind: 'tenant', tenant_id: 'tenant-1' },
      { kind: 'tenant', tenant_id: 'tenant-1' },
    ]
  );
  assert.deepEqual(
    lifecycle.find(([kind]) => kind === 'upgrade'),
    ['upgrade', 'enterprise']
  );
});
test('invalid plan and malformed response fail closed', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantBillingOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return actions(
        service({
          async load() {
            return {};
          },
          async upgradePlan() {},
        })
      ).acquireServiceOperationLease({});
    },
  }));
  assert.throws(
    () => operations.upgradeTenantBillingPlan({ config: config(), scope: scope(), plan: 'trial' }),
    (error) => error.code === 'desktop_tenant_billing_operation_input_invalid'
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => operations.loadTenantBilling({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_billing_operation_response_invalid'
  );
});
test('HMR pins in-flight work and primary error outranks release error', async () => {
  let finish;
  const client = (load) =>
    Object.freeze({
      load,
      async upgradePlan() {
        return tenant();
      },
    });
  let current = actions(
    service(
      client(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          })
      )
    )
  );
  const operations = moduleV2.createDesktopTenantBillingOperationsV2(() => current);
  const pending = operations.loadTenantBilling({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(client(async () => snapshot('new'))));
  finish(snapshot('old'));
  assert.equal((await pending).marker, 'old');
  assert.equal(
    (await operations.loadTenantBilling({ config: config(), scope: scope() })).marker,
    'new'
  );
  const primary = new Error('primary');
  const failing = moduleV2.createDesktopTenantBillingOperationsV2(() =>
    actions(
      service(
        client(async () => {
          throw primary;
        })
      ),
      [],
      new Error('release')
    )
  );
  await assert.rejects(
    () => failing.loadTenantBilling({ config: config(), scope: scope() }),
    primary
  );
});
