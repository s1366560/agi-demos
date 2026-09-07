import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectMemoriesAuthorityUnavailableErrorV2,
  createDesktopProjectMemoriesOperationsV2,
  createDesktopProjectMemoriesClientV2,
  withDesktopProjectMemoriesAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectMemoriesAuthorityModuleV2.js');
const { createDesktopProjectMemoriesHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectMemoriesHttpProjectionV2.js',
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
    page: 1,
    pageSize: 50,
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
    acceptedActions(serviceFixture(received), 'digest-memories', lifecycle),
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
        error.code === 'desktop_project_memories_operation_input_invalid',
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
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
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
      error.reasonCode === 'missing_service',
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
        acceptedActions(service, 'invalid-shape'),
      ).loadProjectMemories({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_memories_service_invalid',
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
        acceptedActions(serviceFixture([], { result: invalidResult }), 'invalid-result'),
      ).loadProjectMemories({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_memories_service_contract_invalid',
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
    },
  );
  await assert.rejects(
    escaped.load(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_memories_operation_released',
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectMemoriesAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopProjectMemoriesAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      (authority) => authority.load(),
    ),
    (error) => error === release,
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

test('local projection discovers native scope and rejects crossed generation or project results', async () => {
  const originalFetch = globalThis.fetch;
  const native = { tenant_id: 'tenant-1', project_id: 'project-1', context_revision: 7,
    profile_id: 'native-profile', generation: 4, digest: 'native-digest' };
  const config = runtimeConfig({ mode: 'local', apiBaseUrl: 'http://127.0.0.1:43123' });
  let wrong = null;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    requests.push({ input: String(input), init });
    assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer memories-session');
    assert.doesNotMatch(JSON.stringify(init), /memories-launch/u);
    const pathname = new URL(String(input)).pathname;
    if (pathname === '/api/v1/knowledge/context') {
      return jsonResponse({ contract_version: '1.0.0', scope: native });
    }
    assert.equal(pathname, '/api/v1/knowledge/query');
    assert.deepEqual(JSON.parse(init.body), { scope: native,
      query: { operation: 'list', offset: 50, limit: 50 } });
    return jsonResponse({ contract_version: '1.0.0',
      scope: { ...native, ...(wrong === 'generation' ? { generation: 5 } : {}) },
      result: { offset: 50, limit: 50, has_more: false, items: [{ id: 'local-memory',
        project_id: wrong === 'project' ? 'other-project' : 'project-1', title: 'Local memory',
        content: 'Local content', content_type: 'text', version: 1, status: 'enabled',
        created_at_ms: 0 }] } });
  };
  try {
    const authority = createDesktopProjectMemoriesHttpAuthorityV2(config, scope('local'));
    const value = await authority.load(undefined, { page: 2 });
    assert.equal(value.authority, 'local');
    assert.equal(value.total, null);
    assert.equal(value.hasMore, false);
    assert.equal(value.scopeRevision, 7);
    assert.equal(value.memories[0].createdAt, '1970-01-01T00:00:00.000Z');
    assert.equal(value.memories[0].processingStatus, 'unavailable');
    const { requireDesktopProjectMemoriesSnapshotV2: validate } = require(
      COMPILED_ROOT + '/src/plugins/desktopProjectMemoriesOperationContractV2.js');
    assert.deepEqual(validate(value, scope('local'), { page: 2 }), value);
    for (const changed of [{ total: 1 }, { hasMore: true }, { hasMore: undefined }]) {
      assert.throws(() => validate({ ...value, ...changed }, scope('local'), { page: 2 }));
    }
    for (wrong of ['generation', 'project']) {
      await assert.rejects(authority.load(undefined, { page: 2 }), (error) => error.status === 409);
    }
    assert.equal(requests.length, 6);
    globalThis.fetch = async () => jsonResponse({ reason_code: 'knowledge_release_closed' }, 503);
    await assert.rejects(authority.load(), (error) => error.status === 503);
  } finally { globalThis.fetch = originalFetch; }
});

test('Memories client carries pagination through the leased authority and vault main policy to HTTP', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const lifecycle = [];
  const controller = new AbortController();
  const network = async (input, init) => {
    const url = new URL(String(input));
    calls.push({ url, signal: init.signal });
    if (url.pathname === '/api/v1/workspace-context') {
      return jsonResponse({
        context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 8 },
      });
    }
    return jsonResponse({ memories: [], total: 76, page: 3, page_size: 25 });
  };
  const { executeVaultBoundCloudRequest } = require(COMPILED_ROOT + '/electron/main/cloudRequestPolicy.js');
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input));
    const response = await executeVaultBoundCloudRequest({ method: init.method, path: url.pathname + url.search }, {
      loadTrustedSession: async () => ({
        version: 1, api_base_url: 'https://cloud.memstack.test', runtime_mode: 'cloud',
        credential_kind: 'cloud_bearer', credential: 'vault-only-pagination-fixture', expires_at: '2099-01-01T00:00:00Z',
      }),
      fetch: network,
      signal: init.signal,
    });
    return jsonResponse(response.body, response.status);
  };
  try {
    const operations = createDesktopProjectMemoriesOperationsV2(() =>
      acceptedActions(
        Object.freeze({ bindOperation: createDesktopProjectMemoriesHttpAuthorityV2 }),
        'pagination-generation',
        lifecycle,
      ),
    );
    const client = createDesktopProjectMemoriesClientV2(operations, runtimeConfig());
    const snapshot = await client.load(scope(), {
      page: 3,
      pageSize: 25,
      signal: controller.signal,
    });
    assert.equal(snapshot.page, 3);
    assert.equal(snapshot.pageSize, 25);
    assert.equal(snapshot.total, 76);
    assert.equal(calls.at(-1).url.search, '?project_id=project-1&page=3&page_size=25');
    assert.equal(calls.filter(({ url }) => url.pathname === '/api/v1/workspace-context').length, 2);
    assert.ok(calls.every((call) => call.signal === controller.signal));
    assert.deepEqual(
      lifecycle.map(({ type }) => type),
      ['acquire', 'release'],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Memories pagination rejects invalid input before lease acquisition and rejects a service returning another page', async () => {
  let acquisitions = 0;
  const operations = createDesktopProjectMemoriesOperationsV2(() => {
    acquisitions++;
    return acceptedActions(serviceFixture([]), 'pagination');
  });
  for (const pagination of [
    { page: 0 },
    { page: 1.5 },
    { page: Infinity },
    { pageSize: 0 },
    { pageSize: 101 },
    { page: null },
  ]) {
    assert.throws(
      () =>
        operations.loadProjectMemories({ config: runtimeConfig(), scope: scope(), ...pagination }),
      (error) => error.code === 'desktop_project_memories_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
  await assert.rejects(
    operations.loadProjectMemories({ config: runtimeConfig(), scope: scope(), page: 2 }),
    (error) => error.code === 'desktop_project_memories_service_contract_invalid',
  );
});

test('Memories HTTP rejects mismatched paging metadata and cross-project rows, and cancels between scope and list', async () => {
  const originalFetch = globalThis.fetch;
  let payload;
  let onScope = () => {};
  let requests = 0;
  globalThis.fetch = async (input) => {
    requests++;
    if (new URL(String(input)).pathname === '/api/v1/workspace-context') {
      onScope();
      return jsonResponse({
        context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 8 },
      });
    }
    return jsonResponse(payload);
  };
  try {
    const authority = createDesktopProjectMemoriesHttpAuthorityV2(runtimeConfig(), scope());
    for (const invalid of [
      { memories: [], total: 10, page: 1, page_size: 5 },
      { memories: [], total: 10, page: 2, page_size: 50 },
      { memories: [{ project_id: 'project-2' }], total: 10, page: 2, page_size: 5 },
    ]) {
      payload = invalid;
      await assert.rejects(authority.load(undefined, { page: 2, pageSize: 5 }), (error) =>
        ['project_memories_page_contract_invalid', 'project_memory_scope_conflict'].includes(
          error.payload?.reason_code,
        ),
      );
    }
    const controller = new AbortController();
    onScope = () => controller.abort();
    const before = requests;
    await assert.rejects(authority.load(controller.signal, { page: 2 }), { name: 'AbortError' });
    assert.equal(requests, before + 1, 'cancelled scope must never issue the list request');
  } finally {
    globalThis.fetch = originalFetch;
  }
});
