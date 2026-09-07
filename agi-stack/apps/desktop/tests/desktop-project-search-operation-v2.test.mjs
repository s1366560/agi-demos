import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectSearchAuthorityUnavailableErrorV2,
  createDesktopProjectSearchOperationsV2,
  withDesktopProjectSearchAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectSearchAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46851',
    apiKey: 'project-search-session',
    localApiToken: 'project-search-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function requests() {
  return [
    {
      mode: 'semantic',
      query: 'architecture',
      strategy: 'hybrid',
      focalNodeUuid: null,
      reranker: null,
      limit: 20,
    },
    {
      mode: 'graphTraversal',
      startEntityUuid: 'entity-1',
      maxDepth: 3,
      relationshipTypes: ['USES'],
      limit: 20,
    },
    {
      mode: 'temporal',
      query: 'release',
      since: '2026-09-01',
      until: null,
      limit: 20,
    },
    {
      mode: 'faceted',
      query: 'plugin',
      entityTypes: ['Module'],
      tags: ['v2'],
      since: null,
      limit: 20,
      offset: 0,
    },
    {
      mode: 'community',
      communityUuid: 'community-1',
      includeEpisodes: true,
      limit: 20,
    },
  ];
}

const SEARCH_TYPES = {
  semantic: 'advanced',
  graphTraversal: 'graph_traversal',
  temporal: 'temporal',
  faceted: 'faceted',
  community: 'community',
};

function response(searchType = 'advanced', overrides = {}) {
  return {
    results: [
      {
        id: 'memory-1',
        title: 'Architecture',
        content: 'Generation-bound search',
        score: 0.9,
        source: 'memory',
        type: 'Memory',
        createdAt: '2026-09-02T00:00:00Z',
        tags: ['v2'],
      },
    ],
    total: 1,
    searchType,
    limit: 20,
    offset: null,
    facets: null,
    ...overrides,
  };
}

function serviceFixture(received = [], overrides = {}) {
  return Object.freeze({
    bindOperation(config) {
      received.push({ kind: 'bind', config });
      return Object.freeze({
        async searchProject(request, scope) {
          received.push({ kind: 'searchProject', request, scope });
          return (
            overrides.response ?? response(SEARCH_TYPES[request.mode])
          );
        },
      });
    },
  });
}

function acceptedActions(service, digest, lifecycle = []) {
  return {
    acquireServiceOperationLease: async (request) => {
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
        },
      };
    },
  };
}

function scope(overrides = {}) {
  return {
    tenantId: 'tenant-1',
    projectId: 'project-1',
    ...overrides,
  };
}

test('facade deep-freezes all five requests before exact project leases', async () => {
  const lifecycle = [];
  const received = [];
  const config = runtimeConfig();
  const operations = createDesktopProjectSearchOperationsV2(
    () => acceptedActions(serviceFixture(received), 'sha256:generation-1', lifecycle),
    () => config,
  );
  const input = requests();
  const pending = input.map((request) => operations.searchProject(request, scope()));
  config.tenantId = 'mutated-tenant';
  input[1].relationshipTypes[0] = 'MUTATED';
  input[3].tags[0] = 'mutated';
  const results = await Promise.all(pending);

  assert.equal(Object.isFrozen(operations), true);
  assert.equal(received.filter(({ kind }) => kind === 'bind').length, 5);
  for (const call of received.filter(({ kind }) => kind === 'searchProject')) {
    assert.equal(Object.isFrozen(call.request), true);
    assert.equal(Object.isFrozen(call.scope), true);
    assert.equal(call.scope.tenantId, 'tenant-1');
  }
  assert.deepEqual(
    received.find(({ request }) => request?.mode === 'graphTraversal').request.relationshipTypes,
    ['USES'],
  );
  assert.deepEqual(
    received.find(({ request }) => request?.mode === 'faceted').request.tags,
    ['v2'],
  );
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ request }) => request.scope),
    Array.from({ length: 5 }, () => ({
      kind: 'project',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
    })),
  );
  assert.equal(lifecycle.filter(({ type }) => type === 'release').length, 5);
  for (const result of results) {
    assert.equal(Object.isFrozen(result), true);
    assert.equal(Object.isFrozen(result.results), true);
    assert.equal(Object.isFrozen(result.results[0]), true);
    assert.equal(Object.isFrozen(result.results[0].tags), true);
  }
});

test(
  'invalid config, request, scope, signal and response fail before authority escape',
  async () => {
    let acquisitions = 0;
    const neverActions = {
      acquireServiceOperationLease: async () => {
        acquisitions += 1;
        throw new Error('unexpected_acquire');
      },
    };
    const cases = [
      [runtimeConfig({ tenantId: '' }), requests()[0], scope()],
      [runtimeConfig(), { ...requests()[0], limit: 0 }, scope()],
      [runtimeConfig(), requests()[0], scope({ tenantId: 'tenant-2' })],
      [runtimeConfig(), requests()[0], {}],
      [runtimeConfig(), { ...requests()[1], relationshipTypes: [1] }, scope()],
      [runtimeConfig(), requests()[0], scope({ signal: {} })],
    ];
    for (const [config, request, operationScope] of cases) {
      const operations = createDesktopProjectSearchOperationsV2(
        () => neverActions,
        () => config,
      );
      await assert.rejects(
        operations.searchProject(request, operationScope),
        (error) =>
          error instanceof RuntimeV2Error &&
          [
            'desktop_project_search_input_invalid',
            'desktop_project_search_scope_mismatch',
          ].includes(error.code),
      );
    }

    const controller = new AbortController();
    controller.abort(new Error('project_search_aborted'));
    const aborted = createDesktopProjectSearchOperationsV2(
      () => neverActions,
      () => runtimeConfig(),
    );
    await assert.rejects(
      aborted.searchProject(
        requests()[0],
        scope({ signal: controller.signal }),
      ),
      /project_search_aborted/u,
    );
    assert.equal(acquisitions, 0);

    const invalidResponse = createDesktopProjectSearchOperationsV2(
      () =>
        acceptedActions(
          serviceFixture([], {
            response: response('advanced', {
              results: [{ id: 'missing-fields' }],
            }),
          }),
          'sha256:invalid-response',
        ),
      () => runtimeConfig(),
    );
    await assert.rejects(
      invalidResponse.searchProject(requests()[0], scope()),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_search_response_invalid',
    );
  },
);

test('missing service, invalid shape and escaped authority fail closed', async () => {
  const unavailable = createDesktopProjectSearchOperationsV2(
    () => null,
    () => runtimeConfig(),
  );
  await assert.rejects(
    unavailable.searchProject(requests()[0], scope()),
    (error) =>
      error instanceof DesktopProjectSearchAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  const rejected = createDesktopProjectSearchOperationsV2(
    () => ({
      acquireServiceOperationLease: async () => ({
        status: 'rejected',
        reasonCode: 'desktop_renderer_service_resolve_failed',
        runtimeCode: 'missing_service',
      }),
    }),
    () => runtimeConfig(),
  );
  await assert.rejects(
    rejected.searchProject(requests()[0], scope()),
    (error) =>
      error instanceof DesktopProjectSearchAuthorityUnavailableErrorV2 &&
      error.runtimeCode === 'missing_service',
  );
  const invalid = createDesktopProjectSearchOperationsV2(
    () => acceptedActions({ bindOperation: () => ({}) }, 'sha256:invalid'),
    () => runtimeConfig(),
  );
  await assert.rejects(
    invalid.searchProject(requests()[0], scope()),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_search_service_invalid',
  );

  let escaped;
  await withDesktopProjectSearchAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    {
      config: runtimeConfig(),
      request: requests()[0],
      scope: scope(),
    },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  await assert.rejects(
    escaped.searchProject(requests()[0], scope()),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_search_operation_released',
  );
});

test('operation error outranks release error and HMR pins each request generation', async () => {
  const releaseFailureActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) =>
        operation({
          bindOperation: () => ({
            searchProject: async () => {
              throw new Error('project_search_operation_failed');
            },
          }),
        }),
      release: async () => {
        throw new Error('project_search_release_failed');
      },
    }),
  };
  const releaseFailure = createDesktopProjectSearchOperationsV2(
    () => releaseFailureActions,
    () => runtimeConfig(),
  );
  await assert.rejects(
    releaseFailure.searchProject(requests()[0], scope()),
    /project_search_operation_failed/u,
  );

  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const oldService = {
    bindOperation: () => ({ searchProject: async () => oldResponse }),
  };
  let actions = acceptedActions(oldService, 'sha256:old', lifecycle);
  const operations = createDesktopProjectSearchOperationsV2(
    () => actions,
    () => runtimeConfig(),
  );
  const oldPending = operations.searchProject(requests()[0], scope());
  actions = acceptedActions(
    serviceFixture([], { response: response('advanced', { total: 2 }) }),
    'sha256:new',
    lifecycle,
  );
  const next = await operations.searchProject(requests()[0], scope());
  resolveOld(response('advanced', { total: 1 }));
  const old = await oldPending;
  assert.equal(next.total, 2);
  assert.equal(old.total, 1);
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    [
      'acquire:sha256:old',
      'acquire:sha256:new',
      'release:sha256:new',
      'release:sha256:old',
    ],
  );
});
