import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const moduleV2 = require(`${ROOT}/src/plugins/desktopTenantEventsAuthorityModuleV2.js`);

const config = (mode = 'cloud') => ({
  apiBaseUrl: 'https://api.test',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: 'key',
  localApiToken: 'local',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  workspaceRoot: '',
  mode,
});
const scope = (authority = 'cloud') => ({ authority, tenantId: 'tenant-1' });
const snapshot = (value) => {
  const data = {
    membershipRole: 'admin',
    events: [],
    eventTypes: [],
    total: 0,
    page: 1,
    pageSize: 20,
  };
  return {
    scope: scope(),
    scopeRevision: 1,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    contractVersion: '4.0.0',
    allowedActions: ['view'],
    data,
    ...data,
    value,
  };
};
const service = (load) => Object.freeze({ bindOperation: () => Object.freeze({ load }) });
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

test('generated contract registers the exact tenant Events service', () => {
  const entry = runtime.PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === moduleV2.DESKTOP_TENANT_EVENTS_AUTHORITY_MODULE_REF_V2
  );
  assert.equal(
    moduleV2.desktopTenantEventsAuthorityDefinitionV2.contractDigest,
    entry.contract_digest
  );
  assert.deepEqual(entry.contract.services.provides, [
    {
      service: moduleV2.DESKTOP_TENANT_EVENTS_AUTHORITY_SERVICE_V2,
      version: '1.0.0',
    },
  ]);
  assert.throws(() =>
    moduleV2.applyDesktopTenantEventsAuthorityV2({ provide() {} }, { strategy: 'legacy' })
  );
});

test('load freezes scope and holds one tenant lease through completion', async () => {
  const lifecycle = [];
  const operations = moduleV2.createDesktopTenantEventsOperationsV2(() =>
    actions(
      service(async (_scope, options) => {
        lifecycle.push(['load', options.filters]);
        return snapshot('ok');
      }),
      lifecycle
    )
  );
  const filters = { eventType: 'run.completed', page: 2, pageSize: 10 };
  const result = await operations.loadTenantEvents({
    config: config(),
    scope: scope(),
    filters,
  });
  filters.page = 9;
  assert.equal(result.value, 'ok');
  assert.deepEqual(lifecycle[0][1].scope, {
    kind: 'tenant',
    tenant_id: 'tenant-1',
  });
  assert.deepEqual(lifecycle[1][1], {
    eventType: 'run.completed',
    page: 2,
    pageSize: 10,
  });
  assert.equal(lifecycle.at(-1)[0], 'release');
});

test('HMR pins old generation and primary failure outranks release failure', async () => {
  let finish;
  let current = actions(
    service(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    )
  );
  const operations = moduleV2.createDesktopTenantEventsOperationsV2(() => current);
  const pending = operations.loadTenantEvents({
    config: config(),
    scope: scope(),
  });
  while (!finish) await new Promise((resolve) => setImmediate(resolve));
  current = actions(service(async () => snapshot('new')));
  finish(snapshot('old'));
  assert.equal((await pending).value, 'old');
  assert.equal(
    (await operations.loadTenantEvents({ config: config(), scope: scope() })).value,
    'new'
  );
  const primary = new Error('primary');
  const release = new Error('release');
  const failing = moduleV2.createDesktopTenantEventsOperationsV2(() =>
    actions(
      service(async () => {
        throw primary;
      }),
      [],
      release
    )
  );
  await assert.rejects(
    () => failing.loadTenantEvents({ config: config(), scope: scope() }),
    primary
  );
});

test('invalid input and response fail closed before a generation can escape', async () => {
  let acquisitions = 0;
  const operations = moduleV2.createDesktopTenantEventsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      return actions(
        service(async () => ({ availability: 'available' }))
      ).acquireServiceOperationLease({});
    },
  }));
  assert.throws(
    () =>
      operations.loadTenantEvents({
        config: { ...config(), unexpected: true },
        scope: scope(),
      }),
    (error) => error.code === 'desktop_tenant_events_operation_input_invalid'
  );
  assert.equal(acquisitions, 0);
  await assert.rejects(
    () => operations.loadTenantEvents({ config: config(), scope: scope() }),
    (error) => error.code === 'desktop_tenant_events_operation_response_invalid'
  );
  assert.equal(acquisitions, 1);
});
