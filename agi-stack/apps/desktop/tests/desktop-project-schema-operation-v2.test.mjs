import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectSchemaAuthorityUnavailableErrorV2,
  createDesktopProjectSchemaOperationsV2,
  withDesktopProjectSchemaAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectSchemaAuthorityModuleV2.js');
const { createDesktopProjectSchemaHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectSchemaHttpProjectionV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'schema-session',
    localApiToken: 'schema-launch',
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

function schemaType(id = 'entity-1', projectId = 'project-1') {
  return {
    id,
    projectId,
    name: `Type ${id}`,
    description: null,
    schema: { type: 'object', properties: { name: { type: 'string' } } },
    status: 'ENABLED',
    source: 'user',
    createdAt: '2026-09-03T00:00:00Z',
    updatedAt: null,
  };
}

function mapping(id = 'mapping-1', projectId = 'project-1') {
  return {
    id,
    projectId,
    sourceType: 'Person',
    targetType: 'Person',
    edgeType: 'KNOWS',
    status: 'ENABLED',
    source: 'user',
    createdAt: '2026-09-03T00:00:00Z',
  };
}

function result(operationScope = scope(), entityId = 'entity-1') {
  return {
    scope: operationScope,
    scopeRevision: 71,
    authority: 'cloud',
    availability: 'degraded',
    reasonCode: 'desktop_project_schema_actions_and_export_unwired',
    contractVersion: '4.0.0',
    allowedActions: ['view', 'list-entity-types'],
    membershipRole: 'member',
    entityTypes: [schemaType(entityId)],
    edgeTypes: [schemaType('edge-1')],
    mappings: [mapping()],
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

test('Project Schema load freezes input and result under one exact project lease', async () => {
  const received = [];
  const lifecycle = [];
  const config = runtimeConfig();
  const operationScope = scope();
  const controller = new AbortController();
  const operations = createDesktopProjectSchemaOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-schema', lifecycle),
  );
  const pending = operations.loadProjectSchema({
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
    snapshot.entityTypes,
    snapshot.entityTypes[0],
    snapshot.entityTypes[0].schema,
    snapshot.entityTypes[0].schema.properties,
    snapshot.edgeTypes,
    snapshot.mappings,
    snapshot.mappings[0],
  ]) {
    assert.equal(Object.isFrozen(value), true);
  }
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-schema',
      request: {
        service: 'service:desktop-renderer.project-schema-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-schema' },
  ]);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[1], { type: 'load', signal: controller.signal });
});

test('invalid and Local Project Schema inputs fail before generation acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopProjectSchemaOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions += 1;
      assert.fail('invalid or Local input must not acquire');
    },
  }));
  for (const invalidInput of [
    { config: runtimeConfig({ mode: 'remote' }), scope: scope() },
    { config: runtimeConfig(), scope: scope('local') },
    { config: runtimeConfig(), scope: scope(), signal: {} },
    { config: runtimeConfig(), scope: scope(), extra: true },
  ]) {
    assert.throws(
      () => operations.loadProjectSchema(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_schema_operation_input_invalid',
    );
  }
  assert.throws(
    () =>
      operations.loadProjectSchema({
        config: runtimeConfig({ mode: 'local' }),
        scope: scope('local'),
      }),
    (error) =>
      error instanceof DesktopProjectSchemaAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'local_project_schema_authority_unavailable' &&
      error.status === 501,
  );
  assert.equal(acquisitions, 0);
});

test('missing or malformed Project Schema services and snapshots fail closed', async () => {
  await assert.rejects(
    createDesktopProjectSchemaOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return {
          status: 'rejected',
          reasonCode: 'missing_service',
          runtimeCode: 'missing_service',
        };
      },
    })).loadProjectSchema({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopProjectSchemaAuthorityUnavailableErrorV2 &&
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
      createDesktopProjectSchemaOperationsV2(() =>
        acceptedActions(service, 'invalid-shape'),
      ).loadProjectSchema({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error && error.code === 'desktop_project_schema_service_invalid',
    );
  }
  const valid = result();
  const cyclicSchema = {};
  cyclicSchema.self = cyclicSchema;
  for (const invalidResult of [
    { ...valid, availability: 'available', reasonCode: null },
    { ...valid, reasonCode: 'partial' },
    { ...valid, contractVersion: '3.0.0' },
    {
      ...valid,
      allowedActions: [...valid.allowedActions, 'create-entity-type'],
    },
    { ...valid, scopeRevision: -1 },
    { ...valid, scope: scope('cloud', { projectId: 'project-2' }) },
    { ...valid, membershipRole: 'superuser' },
    {
      ...valid,
      entityTypes: [{ ...valid.entityTypes[0], projectId: 'project-2' }],
    },
    { ...valid, entityTypes: [valid.entityTypes[0], valid.entityTypes[0]] },
    {
      ...valid,
      entityTypes: [{ ...valid.entityTypes[0], schema: cyclicSchema }],
    },
    { ...valid, edgeTypes: [{ ...valid.edgeTypes[0], schema: [] }] },
    { ...valid, mappings: [{ ...valid.mappings[0], sourceType: '' }] },
    { ...valid, mappings: [valid.mappings[0], valid.mappings[0]] },
    { ...valid, extra: true },
  ]) {
    await assert.rejects(
      createDesktopProjectSchemaOperationsV2(() =>
        acceptedActions(serviceFixture([], { result: invalidResult }), 'invalid-result'),
      ).loadProjectSchema({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_schema_service_contract_invalid',
    );
  }
});

test('HTTP projection keeps scope observation and three schema reads in one authority', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    requests.push({ input: String(input), init });
    const path = new URL(String(input)).pathname;
    if (path === '/api/v1/workspace-context') {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 73,
        },
      });
    }
    if (path === '/api/v1/auth/me') return jsonResponse({ user_id: 'user-1' });
    if (path === '/api/v1/projects/project-1/members') {
      return jsonResponse({
        members: [{ user_id: 'user-1', role: 'owner' }],
        total: 1,
      });
    }
    if (path === '/api/v1/projects/project-1/schema/entities') {
      return jsonResponse([schemaTypePayload('entity-1', 'Person')]);
    }
    if (path === '/api/v1/projects/project-1/schema/edges') {
      return jsonResponse([schemaTypePayload('edge-1', 'KNOWS')]);
    }
    if (path === '/api/v1/projects/project-1/schema/mappings') {
      return jsonResponse([mappingPayload()]);
    }
    throw new Error(`unexpected request: ${String(input)}`);
  };
  try {
    const authority = createDesktopProjectSchemaHttpAuthorityV2(runtimeConfig(), scope());
    const snapshot = await authority.load();
    assert.equal(snapshot.scopeRevision, 73);
    assert.equal(snapshot.reasonCode, 'desktop_project_schema_actions_and_export_unwired');
    assert.deepEqual(snapshot.allowedActions, ['view', 'list-entity-types']);
    assert.equal(snapshot.membershipRole, 'owner');
    assert.equal(snapshot.entityTypes[0].name, 'Person');
    assert.equal(snapshot.edgeTypes[0].name, 'KNOWS');
    assert.equal(snapshot.mappings[0].edgeType, 'KNOWS');
    assert.equal(requests.length, 6);
    for (const { init } of requests) {
      assert.equal(init.credentials, 'omit');
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer schema-session');
      assert.doesNotMatch(JSON.stringify(init), /schema-launch/u);
    }
    await assert.rejects(
      createDesktopProjectSchemaHttpAuthorityV2(
        runtimeConfig({ mode: 'local' }),
        scope('local'),
      ).load(),
      (error) =>
        error.status === 501 &&
        error.payload.reason_code === 'local_project_schema_authority_unavailable',
    );
    assert.equal(requests.length, 6);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('escaped Project Schema authority is revoked and primary failure wins', async () => {
  let escaped;
  await withDesktopProjectSchemaAuthorityOperationV2(
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
      error instanceof RuntimeV2Error && error.code === 'desktop_project_schema_operation_released',
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectSchemaAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopProjectSchemaAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      (authority) => authority.load(),
    ),
    (error) => error === release,
  );
});

test('old Project Schema request stays pinned while replacement serves new requests', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], {
    result: result(scope(), 'old-entity'),
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
  const operations = createDesktopProjectSchemaOperationsV2(() => actions);
  const oldRequest = operations.loadProjectSchema({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(serviceFixture([], { result: result(scope(), 'new-entity') }), 'new');
  const newRequest = operations.loadProjectSchema({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();
  assert.equal((await oldRequest).entityTypes[0].id, 'old-entity');
  assert.equal((await newRequest).entityTypes[0].id, 'new-entity');
});

function schemaTypePayload(id, name) {
  return {
    id,
    project_id: 'project-1',
    name,
    description: null,
    schema: {},
    status: 'ENABLED',
    source: 'user',
    created_at: '2026-09-03T00:00:00Z',
    updated_at: null,
  };
}

function mappingPayload() {
  return {
    id: 'mapping-1',
    project_id: 'project-1',
    source_type: 'Person',
    target_type: 'Person',
    edge_type: 'KNOWS',
    status: 'ENABLED',
    source: 'user',
    created_at: '2026-09-03T00:00:00Z',
  };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
