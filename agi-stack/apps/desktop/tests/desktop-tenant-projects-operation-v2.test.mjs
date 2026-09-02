import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopTenantProjectsAuthorityUnavailableErrorV2,
  createDesktopTenantProjectsOperationsV2,
  withDesktopTenantProjectsAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopTenantProjectsAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46942',
    apiKey: 'projects-secret',
    localApiToken: 'projects-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: '',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function scope(overrides = {}) {
  return { authority: 'local', tenantId: 'tenant-1', ...overrides };
}

function mutationInput(overrides = {}) {
  return { name: 'Alpha', description: 'Tenant project', isPublic: false, ...overrides };
}

function project(overrides = {}) {
  return {
    id: 'project-1',
    tenantId: 'tenant-1',
    name: 'Alpha',
    description: 'Tenant project',
    ownerId: 'user-1',
    memberIds: ['user-1'],
    allowedActions: ['view', 'update', 'delete'],
    isPublic: false,
    createdAt: '2026-09-03T00:00:00Z',
    updatedAt: null,
    stats: {},
    ...overrides,
  };
}

function snapshot(overrides = {}) {
  return {
    scope: scope(),
    authority: 'local',
    availability: 'degraded',
    reasonCode: 'local_project_configuration_projection_partial',
    serviceVersion: '0.1.0',
    contractVersion: '3.0.0',
    allowedActions: ['view', 'list', 'create', 'update', 'delete'],
    authorityRevision: 11,
    projects: [project()],
    total: 1,
    page: 1,
    pageSize: 20,
    ownerIds: ['user-1'],
    ...overrides,
  };
}

function serviceFixture(received, overrides = {}) {
  return Object.freeze({
    bindOperation(config, operationScope) {
      received.push({ type: 'bind', config, scope: operationScope });
      return Object.freeze({
        async list(query, signal) {
          received.push({ type: 'list', query, signal });
          return overrides.list ?? snapshot();
        },
        async get(projectId, signal) {
          received.push({ type: 'get', projectId, signal });
          return overrides.get ?? project({ id: projectId });
        },
        async create(input, idempotencyKey, signal) {
          received.push({ type: 'create', input, idempotencyKey, signal });
          return overrides.create ?? project({ id: 'project-created', name: input.name });
        },
        async update(projectId, input, idempotencyKey, signal) {
          received.push({ type: 'update', projectId, input, idempotencyKey, signal });
          return overrides.update ?? project({ id: projectId, name: input.name });
        },
        async delete(projectId, idempotencyKey, signal) {
          received.push({ type: 'delete', projectId, idempotencyKey, signal });
          return overrides.delete;
        },
      });
    },
  });
}

function acceptedActions(service, digest, lifecycle = [], releaseError = null) {
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
          if (releaseError) throw releaseError;
        },
      };
    },
  };
}

test('each Tenant Projects operation freezes inputs before one exact tenant lease', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const operationScope = scope();
  const query = { page: 2, pageSize: 25, search: ' alpha ', visibility: 'private' };
  const create = mutationInput();
  const update = mutationInput({ name: 'Updated' });
  const operations = createDesktopTenantProjectsOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-a', lifecycle),
  );

  const pendingList = operations.listTenantProjects({
    config,
    scope: operationScope,
    query,
    signal: controller.signal,
  });
  config.tenantId = 'tenant-mutated';
  operationScope.tenantId = 'tenant-mutated';
  query.search = 'mutated';
  await pendingList;
  await operations.getTenantProject({
    config: runtimeConfig(),
    scope: scope(),
    projectId: 'project-1',
  });
  const pendingCreate = operations.createTenantProject({
    config: runtimeConfig(),
    scope: scope(),
    input: create,
    idempotencyKey: 'project-create-0001',
  });
  create.name = 'Mutated';
  await pendingCreate;
  const pendingUpdate = operations.updateTenantProject({
    config: runtimeConfig(),
    scope: scope(),
    projectId: 'project-1',
    input: update,
    idempotencyKey: 'project-update-0001',
  });
  update.name = 'Mutated';
  await pendingUpdate;
  await operations.deleteTenantProject({
    config: runtimeConfig(),
    scope: scope(),
    projectId: 'project-1',
    idempotencyKey: 'project-delete-0001',
  });

  assert.equal(lifecycle.length, 10);
  for (const event of lifecycle.filter(({ type }) => type === 'acquire')) {
    assert.deepEqual(event.request, {
      service: 'service:desktop-renderer.tenant-projects-authority',
      version: '1.0.0',
      scope: { kind: 'tenant', tenant_id: 'tenant-1' },
    });
  }
  assert.equal(received[0].config.tenantId, 'tenant-1');
  assert.deepEqual(received[0].scope, { authority: 'local', tenantId: 'tenant-1' });
  assert.deepEqual(received[1].query, {
    page: 2,
    pageSize: 25,
    search: 'alpha',
    visibility: 'private',
  });
  assert.equal(Object.isFrozen(received[1].query), true);
  assert.equal(received[1].signal, controller.signal);
  assert.equal(received[5].input.name, 'Alpha');
  assert.equal(Object.isFrozen(received[5].input), true);
  assert.equal(received[7].input.name, 'Updated');
  assert.equal(received[9].idempotencyKey, 'project-delete-0001');
});

test('invalid scope, query, identity, payload and idempotency fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopTenantProjectsOperationsV2(() => ({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      assert.fail('invalid input must not acquire a lease');
    },
  }));
  const invalidCalls = [
    () =>
      operations.listTenantProjects({
        config: runtimeConfig(),
        scope: scope({ authority: 'cloud' }),
      }),
    () =>
      operations.listTenantProjects({
        config: runtimeConfig(),
        scope: scope(),
        query: { pageSize: 101 },
      }),
    () =>
      operations.getTenantProject({
        config: runtimeConfig(),
        scope: scope(),
        projectId: ' project-1',
      }),
    () =>
      operations.createTenantProject({
        config: runtimeConfig(),
        scope: scope(),
        input: mutationInput({ name: ' ' }),
      }),
    () =>
      operations.updateTenantProject({
        config: runtimeConfig(),
        scope: scope(),
        projectId: 'project-1',
        input: mutationInput(),
        idempotencyKey: 'short',
      }),
    () =>
      operations.deleteTenantProject({
        config: runtimeConfig(),
        scope: scope(),
        projectId: '',
      }),
  ];
  for (const invalidCall of invalidCalls) {
    assert.throws(
      invalidCall,
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_tenant_projects_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopTenantProjectsOperationsV2(() => null).listTenantProjects({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopTenantProjectsAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('lease rejection and malformed service, authority or result shapes fail closed', async () => {
  const rejectedOperations = createDesktopTenantProjectsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'rejected',
        reasonCode: 'missing_service',
        runtimeCode: 'missing_service',
      };
    },
  }));
  await assert.rejects(
    rejectedOperations.listTenantProjects({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopTenantProjectsAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'missing_service' &&
      error.runtimeCode === 'missing_service',
  );

  for (const service of [
    Object.freeze({ bindOperation: null }),
    Object.freeze({
      bindOperation() {
        return Object.freeze({ list: async () => snapshot() });
      },
    }),
  ]) {
    const operations = createDesktopTenantProjectsOperationsV2(() =>
      acceptedActions(service, 'invalid-shape'),
    );
    await assert.rejects(
      operations.listTenantProjects({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_tenant_projects_service_invalid',
    );
  }

  const malformed = createDesktopTenantProjectsOperationsV2(() =>
    acceptedActions(
      serviceFixture([], { list: { ...snapshot(), authority: 'cloud' } }),
      'bad-result',
    ),
  );
  await assert.rejects(
    malformed.listTenantProjects({ config: runtimeConfig(), scope: scope() }),
    /desktop_tenant_projects_service_contract_invalid/u,
  );
});

test('escaped authority is revoked and primary failure wins over disposer failure', async () => {
  let escaped;
  await withDesktopTenantProjectsAuthorityOperationV2(
    acceptedActions(serviceFixture([]), 'digest-a'),
    { config: runtimeConfig(), scope: scope() },
    (authority) => {
      escaped = authority;
      return authority.list();
    },
  );
  await assert.rejects(
    escaped.list(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_tenant_projects_operation_released',
  );

  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopTenantProjectsAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopTenantProjectsAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { config: runtimeConfig(), scope: scope() },
      (authority) => authority.list(),
    ),
    (error) => error === release,
  );
});

test('old Tenant Projects request stays pinned while a new request uses replacement generation', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([]);
  const originalBind = oldService.bindOperation;
  const gatedService = Object.freeze({
    bindOperation(...args) {
      const authority = originalBind(...args);
      return Object.freeze({
        ...authority,
        async list(query, signal) {
          await gate;
          await authority.list(query, signal);
          return snapshot({ serviceVersion: 'old' });
        },
      });
    },
  });
  let actions = acceptedActions(gatedService, 'old');
  const operations = createDesktopTenantProjectsOperationsV2(() => actions);
  const oldRequest = operations.listTenantProjects({
    config: runtimeConfig(),
    scope: scope(),
  });
  actions = acceptedActions(
    serviceFixture([], { list: snapshot({ serviceVersion: 'new' }) }),
    'new',
  );
  const newRequest = operations.listTenantProjects({
    config: runtimeConfig(),
    scope: scope(),
  });
  releaseOld();

  assert.equal((await oldRequest).serviceVersion, 'old');
  assert.equal((await newRequest).serviceVersion, 'new');
});
