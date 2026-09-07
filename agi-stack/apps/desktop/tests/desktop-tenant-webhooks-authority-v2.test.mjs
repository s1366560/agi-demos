import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantWebhooksAuthorityModuleV2.js`);

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
const webhook = (marker = 'hook') => ({
  id: marker,
  tenantId: 'tenant-1',
  name: 'Hook',
  url: 'https://hook.test',
  secret: null,
  events: ['agent.completed'],
  isActive: true,
  createdAt: null,
  updatedAt: null,
});
const snapshot = (marker) => {
  const data = { membershipRole: 'owner', webhooks: [webhook()], eventTypes: ['agent.completed'] };
  return {
    scope: scope(),
    scopeRevision: 2,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    allowedActions: ['view'],
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

test('catalog registers the exact Tenant Webhooks Provider', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === moduleV2.DESKTOP_TENANT_WEBHOOKS_AUTHORITY_MODULE_REF_V2
  );
  assert.equal(
    moduleV2.desktopTenantWebhooksAuthorityDefinitionV2.contractDigest,
    entry.contract_digest
  );
  assert.deepEqual(entry.contract.services.provides, [
    {
      service: moduleV2.DESKTOP_TENANT_WEBHOOKS_AUTHORITY_SERVICE_V2,
      version: '1.0.0',
    },
  ]);
});

test('CRUD holds exact tenant leases and freezes mutation inputs', async () => {
  const lifecycle = [];
  const client = Object.freeze({
    async load() {
      return snapshot('load');
    },
    async createWebhook(_scope, input) {
      lifecycle.push(['create', input]);
      return webhook('created');
    },
    async updateWebhook(_scope, id, input) {
      lifecycle.push(['update', id, input]);
      return webhook('updated');
    },
    async deleteWebhook(_scope, id) {
      lifecycle.push(['delete', id]);
    },
  });
  const operations = moduleV2.createDesktopTenantWebhooksOperationsV2(() =>
    actions(service(client), lifecycle)
  );
  await operations.loadTenantWebhooks({ config: config(), scope: scope() });
  await operations.createTenantWebhook({
    config: config(),
    scope: scope(),
    webhook: {
      name: 'Hook',
      url: 'https://hook.test',
      events: ['agent.completed'],
    },
  });
  await operations.updateTenantWebhook({
    config: config(),
    scope: scope(),
    webhookId: 'hook-1',
    webhook: {
      name: 'Hook',
      url: 'https://hook.test',
      events: ['agent.completed'],
      isActive: false,
    },
  });
  await operations.deleteTenantWebhook({ config: config(), scope: scope(), webhookId: 'hook-1' });
  assert.deepEqual(
    lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value.scope),
    Array(4).fill({ kind: 'tenant', tenant_id: 'tenant-1' })
  );
  assert.equal(Object.isFrozen(lifecycle.find(([kind]) => kind === 'create')[1].events), true);
});

test('malformed inputs and responses fail before or inside the lease', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantWebhooksOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return actions(
        service(
          Object.freeze({
            async load() {
              return {};
            },
            async createWebhook() {},
            async updateWebhook() {},
            async deleteWebhook() {},
          })
        )
      ).acquireServiceOperationLease({});
    },
  }));
  assert.throws(
    () =>
      operations.createTenantWebhook({
        config: config(),
        scope: scope(),
        webhook: {
          name: ' Hook ',
          url: 'https://hook.test',
          events: [],
        },
      }),
    (error) => error.code === 'desktop_tenant_webhooks_operation_input_invalid'
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => operations.loadTenantWebhooks({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_webhooks_operation_response_invalid'
  );
});

test('HMR pins in-flight work and operation errors outrank release errors', async () => {
  let finish;
  const client = (load) =>
    Object.freeze({
      load,
      async createWebhook() {},
      async updateWebhook() {},
      async deleteWebhook() {},
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
  const operations = moduleV2.createDesktopTenantWebhooksOperationsV2(() => current);
  const pending = operations.loadTenantWebhooks({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(client(async () => snapshot('new'))));
  finish(snapshot('old'));
  assert.equal((await pending).marker, 'old');
  assert.equal(
    (await operations.loadTenantWebhooks({ config: config(), scope: scope() })).marker,
    'new'
  );
  const primary = new Error('primary');
  const failing = moduleV2.createDesktopTenantWebhooksOperationsV2(() =>
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
    () => failing.loadTenantWebhooks({ config: config(), scope: scope() }),
    primary
  );
});
