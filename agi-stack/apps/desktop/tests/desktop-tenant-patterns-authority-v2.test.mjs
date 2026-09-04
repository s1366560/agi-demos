import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantPatternsAuthorityModuleV2.js`);

const config = () => ({
  apiBaseUrl: 'https://api.test',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: 'key',
  localApiToken: 'local',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  workspaceRoot: '',
  mode: 'cloud',
});
const scope = () => ({ authority: 'cloud', tenantId: 'tenant-1' });
const snapshot = (marker) => {
  const data = { membershipRole: 'admin', patterns: [], total: 0, page: 1, pageSize: 50 };
  return {
    scope: scope(),
    scopeRevision: 2,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    allowedActions: ['view', 'list', 'delete'],
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

test('catalog registers the exact Tenant Patterns Provider', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === moduleV2.DESKTOP_TENANT_PATTERNS_AUTHORITY_MODULE_REF_V2
  );
  assert.equal(
    moduleV2.desktopTenantPatternsAuthorityDefinitionV2.contractDigest,
    entry.contract_digest
  );
  assert.deepEqual(entry.contract.services.provides, [
    {
      service: moduleV2.DESKTOP_TENANT_PATTERNS_AUTHORITY_SERVICE_V2,
      version: '1.0.0',
    },
  ]);
});

test('load and delete hold exact tenant leases and freeze inputs', async () => {
  const lifecycle = [];
  const client = Object.freeze({
    async load() {
      return snapshot('load');
    },
    async deletePattern(_scope, patternId) {
      lifecycle.push(['delete', patternId]);
    },
  });
  const operations = moduleV2.createDesktopTenantPatternsOperationsV2(() =>
    actions(service(client), lifecycle)
  );
  assert.equal(
    (await operations.loadTenantPatterns({ config: config(), scope: scope() })).marker,
    'load'
  );
  await operations.deleteTenantPattern({
    config: config(),
    scope: scope(),
    patternId: 'pattern-1',
  });
  assert.deepEqual(
    lifecycle.filter(([kind]) => kind === 'acquire').map(([, value]) => value.scope),
    [
      { kind: 'tenant', tenant_id: 'tenant-1' },
      { kind: 'tenant', tenant_id: 'tenant-1' },
    ]
  );
  assert.deepEqual(
    lifecycle.find(([kind]) => kind === 'delete'),
    ['delete', 'pattern-1']
  );
});

test('malformed inputs and responses fail closed', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantPatternsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return actions(
        service(
          Object.freeze({
            async load() {
              return {};
            },
            async deletePattern() {},
          })
        )
      ).acquireServiceOperationLease({});
    },
  }));
  assert.throws(
    () => operations.deleteTenantPattern({ config: config(), scope: scope(), patternId: ' ' }),
    (error) => error.code === 'desktop_tenant_patterns_operation_input_invalid'
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => operations.loadTenantPatterns({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_patterns_operation_response_invalid'
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
        async deletePattern() {},
      })
    )
  );
  const operations = moduleV2.createDesktopTenantPatternsOperationsV2(() => current);
  const pending = operations.loadTenantPatterns({ config: config(), scope: scope() });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(
    service(
      Object.freeze({
        async load() {
          return snapshot('new');
        },
        async deletePattern() {},
      })
    )
  );
  finish(snapshot('old'));
  assert.equal((await pending).marker, 'old');
  assert.equal(
    (await operations.loadTenantPatterns({ config: config(), scope: scope() })).marker,
    'new'
  );
  const primary = new Error('primary');
  const failing = moduleV2.createDesktopTenantPatternsOperationsV2(() =>
    actions(
      service(
        Object.freeze({
          async load() {
            throw primary;
          },
          async deletePattern() {},
        })
      ),
      [],
      new Error('release')
    )
  );
  await assert.rejects(
    () => failing.loadTenantPatterns({ config: config(), scope: scope() }),
    primary
  );
});
