import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  createDesktopRuntimeInstancesOperationsV2,
  withDesktopRuntimeInstancesAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopRuntimeInstancesAuthorityModuleV2.js');
const { createDesktopRuntimeInstancesHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopRuntimeInstancesHttpProjectionV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function config(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'session',
    localApiToken: 'launch',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}
const scope = (authority = 'cloud') => ({ authority, tenantId: 'tenant-1' });
const instance = (id = 'instance-1') => ({
  id,
  name: 'Primary',
  status: 'running',
  healthStatus: 'healthy',
  imageVersion: null,
  replicas: 1,
  availableReplicas: 1,
  clusterId: null,
  createdAt: null,
  updatedAt: null,
  projection: 'cloud',
});
const page = () => ({ instances: [instance()], total: 1, page: 1, pageSize: 20 });
const capability = (operationScope = scope()) => ({
  availability: 'degraded',
  reason_code:
    operationScope.authority === 'local'
      ? 'local_instance_sidecar_projection_partial'
      : 'runtime_instances_nested_routes_partial',
  service_version: '0.1.0',
  contract_version: '3.0.0',
  allowed_actions:
    operationScope.authority === 'local'
      ? ['view', 'list', 'refresh', 'search', 'filter-status']
      : ['view', 'list', 'refresh', 'search', 'filter-status', 'paginate', 'restart', 'delete'],
  scope: { tenant_id: operationScope.tenantId, project_id: null, workspace_id: null, instance_id: null },
  authority_revision: null,
});

function service(events, overrides = {}) {
  return Object.freeze({
    bindOperation(operationConfig, operationScope) {
      events.push(['bind', operationConfig, operationScope]);
      return Object.freeze({
        async list(query, signal) {
          events.push(['list', query, signal]);
          return overrides.page ?? page();
        },
        async restart(id, signal) {
          events.push(['restart', id, signal]);
          return overrides.mutationResult;
        },
        async delete(id, signal) {
          events.push(['delete', id, signal]);
          return overrides.mutationResult;
        },
        async probe(signal) {
          events.push(['probe', signal]);
          return overrides.capability ?? capability(operationScope);
        },
      });
    },
  });
}

function actions(authorityService, lifecycle = [], releaseError = null) {
  return {
    async acquireServiceOperationLease(request) {
      lifecycle.push(['acquire', request]);
      let released = false;
      return {
        status: 'accepted',
        digest: 'digest-runtime-instances',
        useService(operation) {
          if (released) throw new Error('lease_released');
          return operation(authorityService);
        },
        async release() {
          if (released) return;
          released = true;
          lifecycle.push(['release']);
          if (releaseError) throw releaseError;
        },
      };
    },
  };
}

test('Runtime Instances freezes inputs and acquires one tenant lease per operation', async () => {
  const events = [];
  const lifecycle = [];
  const runtimeConfig = config();
  const operationScope = scope();
  const query = { page: 1, pageSize: 20, search: '', status: 'all' };
  const operations = createDesktopRuntimeInstancesOperationsV2(() =>
    actions(service(events), lifecycle),
  );
  const pending = operations.listRuntimeInstances({ config: runtimeConfig, scope: operationScope, query });
  runtimeConfig.tenantId = 'changed';
  operationScope.tenantId = 'changed';
  query.page = 2;
  const result = await pending;
  await operations.restartRuntimeInstance({ config: config(), scope: scope(), instanceId: 'instance-1' });
  await operations.deleteRuntimeInstance({ config: config(), scope: scope(), instanceId: 'instance-1' });
  await operations.probeRuntimeInstances({ config: config(), scope: scope() });

  assert.equal(Object.isFrozen(result), true);
  assert.equal(Object.isFrozen(result.instances), true);
  assert.equal(Object.isFrozen(result.instances[0]), true);
  assert.equal(lifecycle.filter(([type]) => type === 'acquire').length, 4);
  assert.equal(lifecycle.filter(([type]) => type === 'release').length, 4);
  for (const [, request] of lifecycle.filter(([type]) => type === 'acquire')) {
    assert.deepEqual(request, {
      service: 'service:desktop-renderer.runtime-instances-authority',
      version: '1.0.0',
      scope: { kind: 'tenant', tenant_id: 'tenant-1' },
    });
  }
});

test('invalid scope, query, identifiers and unknown fields fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopRuntimeInstancesOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      assert.fail('invalid input must not acquire');
    },
  }));
  for (const input of [
    { config: config({ mode: 'remote' }), scope: scope() },
    { config: config(), scope: scope('local') },
    { config: config(), scope: scope(), query: { pageSize: 101 } },
    { config: config(), scope: scope(), extra: true },
  ]) {
    assert.throws(
      () => operations.listRuntimeInstances(input),
      (error) => error instanceof RuntimeV2Error &&
        error.code === 'desktop_runtime_instances_operation_input_invalid',
    );
  }
  assert.throws(
    () => operations.restartRuntimeInstance({ config: config(), scope: scope(), instanceId: ' bad' }),
    (error) => error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_instances_operation_input_invalid',
  );
  assert.equal(acquisitions, 0);
});

test('service shape and returned contracts fail closed while primary errors beat release errors', async () => {
  const operations = createDesktopRuntimeInstancesOperationsV2(() =>
    actions(Object.freeze({ bindOperation: () => Object.freeze({ list: async () => page() }) })),
  );
  await assert.rejects(
    operations.listRuntimeInstances({ config: config(), scope: scope() }),
    (error) => error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_instances_service_invalid',
  );

  const primary = new Error('primary');
  const release = new Error('release');
  const primaryOperations = createDesktopRuntimeInstancesOperationsV2(() =>
    actions(service([], { page: Promise.reject(primary) }), [], release),
  );
  await assert.rejects(
    primaryOperations.listRuntimeInstances({ config: config(), scope: scope() }),
    primary,
  );
});

test('HMR pins an old request and resolves the next request from the replacement generation', async () => {
  let current = actions(service([], { page: { ...page(), instances: [instance('old')] } }));
  const operations = createDesktopRuntimeInstancesOperationsV2(() => current);
  const oldResult = await operations.listRuntimeInstances({ config: config(), scope: scope() });
  current = actions(service([], { page: { ...page(), instances: [instance('new')] } }));
  const newResult = await operations.listRuntimeInstances({ config: config(), scope: scope() });
  assert.equal(oldResult.instances[0].id, 'old');
  assert.equal(newResult.instances[0].id, 'new');
});

test('escaped authority is revoked after release', async () => {
  let escaped;
  await withDesktopRuntimeInstancesAuthorityOperationV2(
    actions(service([])),
    { kind: 'probe', config: config(), scope: scope() },
    async (authority) => {
      escaped = authority;
      await authority.probe();
    },
  );
  await assert.rejects(
    escaped.probe(),
    (error) => error instanceof RuntimeV2Error &&
      error.code === 'desktop_runtime_instances_operation_released',
  );
});

test('Cloud projection preserves exact query, mutations and safe response fields', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    if (init.method !== 'GET') return new Response(null, { status: 204 });
    return new Response(JSON.stringify({
      instances: [{
        id: 'instance-1', name: 'Primary', status: 'running', health_status: 'healthy',
        image_version: '2026.09', replicas: 2, available_replicas: 1,
        cluster_id: 'cluster-1', created_at: null, updated_at: null,
        secret: 'must-not-cross',
      }],
      total: 1, page: 2, page_size: 20,
    }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const authority = createDesktopRuntimeInstancesHttpAuthorityV2(config(), scope());
    const result = await authority.list({ page: 2, pageSize: 20, search: 'Primary', status: 'running' });
    await authority.restart('instance-1');
    await authority.delete('instance-1');
    assert.equal(JSON.stringify(result).includes('secret'), false);
    assert.match(calls[0].input, /instances\/\?page=2&page_size=20&search=Primary&status=running/u);
    assert.equal(calls[1].init.method, 'POST');
    assert.equal(calls[2].init.method, 'DELETE');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Local projection uses only sidecar status and rejects lifecycle mutations before transport', async () => {
  const originalWindow = globalThis.window;
  const commands = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command) {
          commands.push(command);
          return { running: true, tool_count: 12, runtime_providers: ['builtin'] };
        },
      },
    },
  };
  try {
    const localScope = scope('local');
    const authority = createDesktopRuntimeInstancesHttpAuthorityV2(
      config({ mode: 'local' }),
      localScope,
    );
    const result = await authority.list({ page: 1, pageSize: 20, search: 'sidecar', status: 'running' });
    assert.equal(result.instances[0].projection, 'local_sidecar');
    await assert.rejects(authority.restart('local-sidecar'), /local_instance_lifecycle_not_applicable/u);
    await assert.rejects(authority.delete('local-sidecar'), /local_instance_lifecycle_not_applicable/u);
    assert.deepEqual(commands, ['local_runtime_status']);
  } finally {
    globalThis.window = originalWindow;
  }
});
