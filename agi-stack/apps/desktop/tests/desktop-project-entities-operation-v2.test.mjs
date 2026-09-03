import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectEntitiesAuthorityUnavailableErrorV2,
  createDesktopProjectEntitiesOperationsV2,
  withDesktopProjectEntitiesAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectEntitiesAuthorityModuleV2.js');
const { createDesktopProjectEntitiesHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectEntitiesHttpProjectionV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'entities-session',
    localApiToken: 'entities-launch',
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

function entity(id = 'entity-1', projectId = 'project-1') {
  return {
    id,
    name: `Entity ${id}`,
    entityType: 'Person',
    summary: 'Grounded summary',
    projectId,
    createdAt: null,
  };
}

function result(operationScope = scope()) {
  return {
    scope: operationScope,
    scopeRevision: 31,
    authority: 'cloud',
    availability: 'degraded',
    reasonCode: 'desktop_project_entities_actions_partial',
    allowedActions: ['view', 'list'],
    entities: [entity()],
    total: 1,
    entityTypes: [{ entityType: 'Person', count: 1 }],
  };
}

function relationships() {
  return [
    {
      edgeId: 'edge-1',
      relationType: 'KNOWS',
      direction: 'outgoing',
      fact: 'Entity one knows entity two',
      relatedEntity: entity('entity-2'),
    },
  ];
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
        async relationships(entityId, signal) {
          received.push({ type: 'relationships', entityId, signal });
          return overrides.relationships ?? relationships();
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

test('Entities load freezes input and holds one exact project generation lease', async () => {
  const received = [];
  const lifecycle = [];
  const config = runtimeConfig();
  const operationScope = scope();
  const controller = new AbortController();
  const operations = createDesktopProjectEntitiesOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-entities', lifecycle),
  );
  const pending = operations.loadProjectEntities({
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
    snapshot.entities,
    snapshot.entities[0],
    snapshot.entityTypes,
    snapshot.entityTypes[0],
  ]) {
    assert.equal(Object.isFrozen(value), true);
  }
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-entities',
      request: {
        service: 'service:desktop-renderer.project-entities-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-entities' },
  ]);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[1], { type: 'load', signal: controller.signal });
});

test('relationships canonicalize identity and use an independent project lease', async () => {
  const received = [];
  const lifecycle = [];
  const controller = new AbortController();
  const operations = createDesktopProjectEntitiesOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-relationships', lifecycle),
  );
  const value = await operations.loadProjectEntityRelationships({
    config: runtimeConfig(),
    scope: scope(),
    entityId: 'entity-1',
    signal: controller.signal,
  });

  assert.equal(Object.isFrozen(value), true);
  assert.equal(Object.isFrozen(value[0]), true);
  assert.equal(Object.isFrozen(value[0].relatedEntity), true);
  assert.deepEqual(received[1], {
    type: 'relationships',
    entityId: 'entity-1',
    signal: controller.signal,
  });
  assert.deepEqual(lifecycle.map(({ type }) => type), ['acquire', 'release']);
});

test('invalid scope, identity, signal and unknown fields fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopProjectEntitiesOperationsV2(() => ({
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
      () => operations.loadProjectEntities(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_entities_operation_input_invalid',
    );
  }
  for (const invalidInput of [
    { config: runtimeConfig(), scope: scope(), entityId: '' },
    { config: runtimeConfig(), scope: scope(), entityId: ' entity-1' },
    { config: runtimeConfig(), scope: scope(), entityId: 'entity-1', extra: true },
  ]) {
    assert.throws(
      () => operations.loadProjectEntityRelationships(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_entities_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopProjectEntitiesOperationsV2(() => null).loadProjectEntities({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopProjectEntitiesAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('missing or malformed service, authority and responses fail closed', async () => {
  await assert.rejects(
    createDesktopProjectEntitiesOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return { status: 'rejected', reasonCode: 'missing_service', runtimeCode: 'missing_service' };
      },
    })).loadProjectEntities({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopProjectEntitiesAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service',
  );
  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({ bindOperation: () => Object.freeze({ load: null, relationships: null }) }),
    Object.freeze({
      bindOperation: () => Object.freeze({ load: async () => result(), relationships: null }),
    }),
  ]) {
    await assert.rejects(
      createDesktopProjectEntitiesOperationsV2(() =>
        acceptedActions(service, 'invalid-shape'),
      ).loadProjectEntities({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_entities_service_invalid',
    );
  }
  const valid = result();
  for (const invalidResult of [
    { ...valid, availability: 'available', reasonCode: null },
    { ...valid, reasonCode: 'partial' },
    { ...valid, allowedActions: ['view', 'list', 'filter'] },
    { ...valid, scopeRevision: -1 },
    { ...valid, scope: scope('cloud', { projectId: 'project-2' }) },
    { ...valid, entities: [{ ...valid.entities[0], projectId: 'project-2' }] },
    { ...valid, total: 0 },
    { ...valid, entityTypes: [{ entityType: 'Person', count: -1 }] },
    { ...valid, extra: true },
  ]) {
    await assert.rejects(
      createDesktopProjectEntitiesOperationsV2(() =>
        acceptedActions(serviceFixture([], { result: invalidResult }), 'invalid-result'),
      ).loadProjectEntities({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_entities_service_contract_invalid',
    );
  }
  for (const invalidRelationships of [
    [{ ...relationships()[0], direction: 'sideways' }],
    [{ ...relationships()[0], relatedEntity: entity('entity-2', 'project-2') }],
    [{ ...relationships()[0], extra: true }],
  ]) {
    await assert.rejects(
      createDesktopProjectEntitiesOperationsV2(() =>
        acceptedActions(
          serviceFixture([], { relationships: invalidRelationships }),
          'invalid-relationships',
        ),
      ).loadProjectEntityRelationships({
        config: runtimeConfig(),
        scope: scope(),
        entityId: 'entity-1',
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_entities_service_contract_invalid',
    );
  }
});

test('HTTP projection keeps three load reads in one authority and relationships scoped', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    requests.push({ input: String(input), init });
    const url = new URL(String(input));
    if (url.pathname === '/api/v1/workspace-context') {
      return jsonResponse({
        context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 43 },
      });
    }
    if (url.pathname === '/api/v1/graph/entities/') {
      return jsonResponse({
        items: [
          {
            uuid: 'entity-1',
            name: 'Entity one',
            entity_type: 'Person',
            summary: 'Summary',
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            created_at: null,
          },
        ],
        total: 1,
      });
    }
    if (url.pathname === '/api/v1/graph/entities/types') {
      return jsonResponse({ entity_types: [{ entity_type: 'Person', count: 1 }] });
    }
    if (url.pathname === '/api/v1/graph/entities/entity-1/relationships') {
      return jsonResponse({
        relationships: [
          {
            edge_id: 'edge-1',
            relation_type: 'KNOWS',
            direction: 'outgoing',
            fact: 'Knows entity two',
            related_entity: {
              uuid: 'entity-2',
              name: 'Entity two',
              entity_type: 'Person',
              summary: 'Summary',
              tenant_id: 'tenant-1',
              project_id: 'project-1',
              created_at: null,
            },
          },
        ],
      });
    }
    throw new Error(`unexpected request: ${String(input)}`);
  };
  try {
    const authority = createDesktopProjectEntitiesHttpAuthorityV2(
      runtimeConfig(),
      scope(),
    );
    const snapshot = await authority.load();
    assert.equal(snapshot.scopeRevision, 43);
    assert.equal(snapshot.availability, 'degraded');
    assert.equal(snapshot.reasonCode, 'desktop_project_entities_actions_partial');
    assert.deepEqual(snapshot.allowedActions, ['view', 'list']);
    assert.equal(snapshot.entities[0].id, 'entity-1');
    assert.equal(requests.length, 3);
    const related = await authority.relationships('entity-1');
    assert.equal(related[0].relatedEntity.id, 'entity-2');
    assert.equal(requests.length, 4);
    assert.equal(new URL(requests[1].input).searchParams.get('limit'), '50');
    assert.equal(new URL(requests[3].input).searchParams.get('limit'), '100');
    for (const { init } of requests) {
      assert.equal(init.credentials, 'omit');
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer entities-session');
      assert.doesNotMatch(JSON.stringify(init), /entities-launch/u);
    }
    await assert.rejects(
      createDesktopProjectEntitiesHttpAuthorityV2(
        runtimeConfig({ mode: 'local' }),
        scope('local'),
      ).load(),
      (error) =>
        error.status === 501 &&
        error.payload.reason_code === 'local_project_entities_authority_unavailable',
    );
    assert.equal(requests.length, 4);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('escaped authority is revoked and primary failure wins over release failure', async () => {
  let escaped;
  await withDesktopProjectEntitiesAuthorityOperationV2(
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
      error.code === 'desktop_project_entities_operation_released',
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectEntitiesAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopProjectEntitiesAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      (authority) => authority.load(),
    ),
    (error) => error === release,
  );
});

test('old Entities request stays pinned while replacement generation serves new requests', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], {
    result: { ...result(), entities: [entity('old-entity')] },
  });
  const gatedService = Object.freeze({
    bindOperation(...args) {
      const authority = oldService.bindOperation(...args);
      return Object.freeze({
        async load(...loadArgs) {
          await gate;
          return authority.load(...loadArgs);
        },
        relationships: authority.relationships,
      });
    },
  });
  let actions = acceptedActions(gatedService, 'old');
  const operations = createDesktopProjectEntitiesOperationsV2(() => actions);
  const oldRequest = operations.loadProjectEntities({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(
    serviceFixture([], { result: { ...result(), entities: [entity('new-entity')] } }),
    'new',
  );
  const newRequest = operations.loadProjectEntities({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();
  assert.equal((await oldRequest).entities[0].id, 'old-entity');
  assert.equal((await newRequest).entities[0].id, 'new-entity');
});

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
