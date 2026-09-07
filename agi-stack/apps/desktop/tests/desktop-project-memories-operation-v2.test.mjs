import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectMemoriesAuthorityUnavailableErrorV2,
  createDesktopProjectMemoriesOperationsV2,
  withDesktopProjectMemoriesAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectMemoriesAuthorityModuleV2.js');
const { createDesktopProjectMemoriesHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectMemoriesHttpProjectionV2.js'
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'memories-session',
    localApiToken: 'memories-launch',
    mode: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function scope(authority = 'cloud', overrides = {}) {
  return {
    authority,
    tenantId: 'tenant-1',
    projectId: 'project-1',
    ...overrides,
  };
}

function memory(id = 'memory-1', projectId = 'project-1') {
  return {
    id,
    projectId,
    title: `Memory ${id}`,
    content: 'Grounded memory content',
    contentType: 'text',
    version: 3,
    status: 'ENABLED',
    processingStatus: 'COMPLETED',
    createdAt: '2026-09-03T00:00:00Z',
    updatedAt: null,
  };
}

function result(operationScope = scope(), id = 'memory-1') {
  return {
    scope: operationScope,
    scopeRevision: 37,
    authority: 'cloud',
    availability: 'degraded',
    reasonCode: 'desktop_project_memories_actions_partial',
    allowedActions: ['view', 'list'],
    memories: [memory(id)],
    total: 1,
  };
}

function serviceFixture(received, overrides = {}) {
  return Object.freeze({
    bindOperation(config, operationScope) {
      received.push({ type: 'bind', config, scope: operationScope });
      return Object.freeze({
        async load(signal) {
          received.push({ type: 'load', signal });
          return overrides.result ?? result(operationScope);
        },
      });
    },
  });
}

function acceptedActions(service, digest, lifecycle = [], releaseError = null) {
  return {
    async acquireServiceOperationLease(request) {
      lifecycle.push({ type: 'acquire', digest, request });
      let released = false;
      return {
        status: 'accepted',
        digest,
        useService(operation) {
          if (released) throw new Error('lease_released');
          return operation(service);
        },
        async release() {
          if (released) return;
          released = true;
          lifecycle.push({ type: 'release', digest });
          if (releaseError) throw releaseError;
        },
      };
    },
  };
}

test('Memories load freezes input and holds one exact project generation lease', async () => {
  const received = [];
  const lifecycle = [];
  const config = runtimeConfig();
  const operationScope = scope();
  const controller = new AbortController();
  const operations = createDesktopProjectMemoriesOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-memories', lifecycle)
  );
  const pending = operations.loadProjectMemories({
    config,
    scope: operationScope,
    signal: controller.signal,
  });
  config.tenantId = 'mutated';
  operationScope.projectId = 'mutated';

  const snapshot = await pending;
  for (const value of [
    snapshot,
    snapshot.scope,
    snapshot.allowedActions,
    snapshot.memories,
    snapshot.memories[0],
  ]) {
    assert.equal(Object.isFrozen(value), true);
  }
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-memories',
      request: {
        service: 'service:desktop-renderer.project-memories-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-memories' },
  ]);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[1], { type: 'load', signal: controller.signal });
});

test('invalid Memories scope, signal and unknown fields fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopProjectMemoriesOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      assert.fail('invalid input must not acquire');
    },
  }));
  for (const invalidInput of [
    { config: runtimeConfig({ mode: 'remote' }), scope: scope() },
    { config: runtimeConfig(), scope: scope('local') },
    { config: runtimeConfig(), scope: scope(), signal: {} },
    { config: runtimeConfig(), scope: scope(), extra: true },
  ]) {
    assert.throws(
      () => operations.loadProjectMemories(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_memories_operation_input_invalid'
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopProjectMemoriesOperationsV2(() => null).loadProjectMemories({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopProjectMemoriesAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable'
  );
});

test('missing or malformed Memories service, authority and snapshots fail closed', async () => {
  await assert.rejects(
    createDesktopProjectMemoriesOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return {
          status: 'rejected',
          reasonCode: 'missing_service',
          runtimeCode: 'missing_service',
        };
      },
    })).loadProjectMemories({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopProjectMemoriesAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service'
  );
  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({ bindOperation: () => Object.freeze({ load: null }) }),
    Object.freeze({
      bindOperation: () => Object.freeze({ load: async () => result(), extra: true }),
    }),
  ]) {
    await assert.rejects(
      createDesktopProjectMemoriesOperationsV2(() =>
        acceptedActions(service, 'invalid-shape')
      ).loadProjectMemories({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error && error.code === 'desktop_project_memories_service_invalid'
    );
  }
  const valid = result();
  for (const invalidResult of [
    { ...valid, availability: 'available', reasonCode: null },
    { ...valid, reasonCode: 'partial' },
    { ...valid, allowedActions: ['view', 'list', 'create'] },
    { ...valid, scopeRevision: -1 },
    { ...valid, scope: scope('cloud', { projectId: 'project-2' }) },
    { ...valid, memories: [{ ...valid.memories[0], projectId: 'project-2' }] },
    { ...valid, memories: [{ ...valid.memories[0], version: -1 }] },
    { ...valid, memories: [{ ...valid.memories[0], processingStatus: '' }] },
    { ...valid, memories: [valid.memories[0], valid.memories[0]], total: 2 },
    { ...valid, total: 0 },
    { ...valid, extra: true },
  ]) {
    await assert.rejects(
      createDesktopProjectMemoriesOperationsV2(() =>
        acceptedActions(serviceFixture([], { result: invalidResult }), 'invalid-result')
      ).loadProjectMemories({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_memories_service_contract_invalid'
    );
  }
});

test('HTTP projection keeps context and memory reads in one authority', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    requests.push({ input: String(input), init });
    const url = new URL(String(input));
    if (url.pathname === '/api/v1/workspace-context') {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 53,
        },
      });
    }
    if (url.pathname === '/api/v1/memories/') {
      return jsonResponse({
        memories: [
          {
            id: 'memory-1',
            project_id: 'project-1',
            title: 'Memory one',
            content: 'Content',
            content_type: 'text',
            version: 3,
            status: 'ENABLED',
            processing_status: 'COMPLETED',
            created_at: '2026-09-03T00:00:00Z',
            updated_at: null,
          },
        ],
        total: 1,
        page: 1,
        page_size: 50,
      });
    }
    throw new Error(`unexpected request: ${String(input)}`);
  };
  try {
    const authority = createDesktopProjectMemoriesHttpAuthorityV2(runtimeConfig(), scope());
    const snapshot = await authority.load();
    assert.equal(snapshot.scopeRevision, 53);
    assert.equal(snapshot.reasonCode, 'desktop_project_memories_actions_partial');
    assert.deepEqual(snapshot.allowedActions, ['view', 'list']);
    assert.equal(snapshot.memories[0].id, 'memory-1');
    assert.equal(requests.length, 2);
    const query = new URL(requests[1].input).searchParams;
    assert.equal(query.get('project_id'), 'project-1');
    assert.equal(query.get('page'), '1');
    assert.equal(query.get('page_size'), '50');
    for (const { init } of requests) {
      assert.equal(init.credentials, 'omit');
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer memories-session');
      assert.doesNotMatch(JSON.stringify(init), /memories-launch/u);
    }
    await assert.rejects(
      createDesktopProjectMemoriesHttpAuthorityV2(
        runtimeConfig({ mode: 'local' }),
        scope('local')
      ).load(),
      (error) =>
        error.status === 501 &&
        error.payload.reason_code === 'local_project_memories_authority_unavailable'
    );
    assert.equal(requests.length, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('escaped Memories authority is revoked and primary failure wins over release failure', async () => {
  let escaped;
  await withDesktopProjectMemoriesAuthorityOperationV2(
    acceptedActions(serviceFixture([]), 'digest-a'),
    { kind: 'load', config: runtimeConfig(), scope: scope() },
    (authority) => {
      escaped = authority;
      return authority.load();
    }
  );
  await assert.rejects(
    escaped.load(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_memories_operation_released'
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectMemoriesAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      }
    ),
    (error) => error === primary
  );
  await assert.rejects(
    withDesktopProjectMemoriesAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      (authority) => authority.load()
    ),
    (error) => error === release
  );
});

test('old Memories request stays pinned while replacement generation serves new requests', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], {
    result: result(scope(), 'old-memory'),
  });
  const gatedService = Object.freeze({
    bindOperation(...args) {
      const authority = oldService.bindOperation(...args);
      return Object.freeze({
        async load(...loadArgs) {
          await gate;
          return authority.load(...loadArgs);
        },
      });
    },
  });
  let actions = acceptedActions(gatedService, 'old');
  const operations = createDesktopProjectMemoriesOperationsV2(() => actions);
  const oldRequest = operations.loadProjectMemories({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(serviceFixture([], { result: result(scope(), 'new-memory') }), 'new');
  const newRequest = operations.loadProjectMemories({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();
  assert.equal((await oldRequest).memories[0].id, 'old-memory');
  assert.equal((await newRequest).memories[0].id, 'new-memory');
});

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
