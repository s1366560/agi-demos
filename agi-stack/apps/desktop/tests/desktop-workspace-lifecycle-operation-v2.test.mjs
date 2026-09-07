import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopWorkspaceLifecycleAuthorityUnavailableErrorV2,
  createDesktopWorkspaceLifecycleOperationsV2,
  withDesktopWorkspaceLifecycleAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceLifecycleAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46971',
    apiKey: 'workspace-lifecycle-session',
    localApiToken: 'workspace-lifecycle-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '/workspace/project-1',
    ...overrides,
  };
}

function createInput(overrides = {}) {
  return {
    name: 'Created workspace',
    description: 'Created through V2',
    useCase: 'conversation',
    collaborationMode: 'multi_agent_shared',
    metadata: { source: 'desktop', autonomy_profile: { workspace_type: 'general' } },
    ...overrides,
  };
}

function updateInput(overrides = {}) {
  return {
    name: 'Updated workspace',
    description: 'Updated through V2',
    isArchived: true,
    metadata: { source: 'desktop-v2', code_context: { root: '/workspace/project-1' } },
    ...overrides,
  };
}

function workspace(overrides = {}) {
  return {
    id: 'workspace-created',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: 'Created workspace',
    created_by: 'user-1',
    description: 'Created through V2',
    status: 'active',
    is_archived: false,
    office_status: 'idle',
    hex_layout_config: {},
    created_at: '2026-09-02T00:00:00Z',
    updated_at: null,
    metadata: {},
    ...overrides,
  };
}

function serviceFixture(received = [], overrides = {}) {
  return Object.freeze({
    bindOperation(config) {
      received.push({ kind: 'bind-operation', config });
      return Object.freeze({
        async createWorkspace(input, signal) {
          received.push({ kind: 'create', input, signal });
          return overrides.created ?? workspace({ name: input.name });
        },
        async updateWorkspace(workspaceId, input, signal) {
          received.push({ kind: 'update', workspaceId, input, signal });
          return (
            overrides.updated ??
            workspace({
              id: workspaceId,
              name: input.name,
              description: input.description,
              is_archived: input.isArchived,
            })
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

function operations(actions) {
  return createDesktopWorkspaceLifecycleOperationsV2(() => actions);
}

test('create and update freeze project scope, payload and signal before lease acquisition', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const createCommand = createInput();
  const updateCommand = updateInput();
  const authority = operations(
    acceptedActions(serviceFixture(received), 'sha256:generation-1', lifecycle),
  );

  const createdPending = authority.createWorkspace({
    config,
    input: createCommand,
    signal: controller.signal,
  });
  const updatedPending = authority.updateWorkspace({
    config: runtimeConfig({ workspaceId: 'workspace-1' }),
    workspaceId: 'workspace-1',
    input: updateCommand,
    signal: controller.signal,
  });
  config.tenantId = 'mutated-tenant';
  createCommand.name = 'mutated-name';
  createCommand.metadata.autonomy_profile.workspace_type = 'mutated';
  updateCommand.metadata.code_context.root = '/mutated';

  const [created, updated] = await Promise.all([createdPending, updatedPending]);
  assert.equal(created.name, 'Created workspace');
  assert.equal(updated.name, 'Updated workspace');
  assert.equal(Object.isFrozen(created), true);
  assert.equal(Object.isFrozen(updated), true);
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ request }) => request),
    Array.from({ length: 2 }, () => ({
      service: 'service:desktop-renderer.workspace-lifecycle-authority',
      version: '1.0.0',
      scope: { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
    })),
  );
  const bindings = received.filter(({ kind }) => kind === 'bind-operation');
  assert.equal(bindings.length, 2);
  assert.equal(bindings.every(({ config: bound }) => Object.isFrozen(bound)), true);
  assert.equal(bindings.every(({ config: bound }) => bound.tenantId === 'tenant-1'), true);
  const createCall = received.find(({ kind }) => kind === 'create');
  const updateCall = received.find(({ kind }) => kind === 'update');
  assert.equal(createCall.input.name, 'Created workspace');
  assert.equal(createCall.input.metadata.autonomy_profile.workspace_type, 'general');
  assert.equal(updateCall.input.metadata.code_context.root, '/workspace/project-1');
  assert.equal(createCall.signal, controller.signal);
  assert.equal(updateCall.signal, controller.signal);
});

test('invalid inputs fail before lease acquisition', () => {
  let acquisitions = 0;
  const authority = operations({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  });
  const createBase = { config: runtimeConfig(), input: createInput() };
  for (const input of [
    { ...createBase, config: runtimeConfig({ tenantId: '' }) },
    { ...createBase, config: runtimeConfig({ workspaceId: 'workspace-1' }) },
    { ...createBase, input: createInput({ name: ' Created workspace' }) },
    { ...createBase, input: createInput({ useCase: 'unknown' }) },
    { ...createBase, input: createInput({ metadata: { bad: undefined } }) },
    { ...createBase, signal: {} },
    { ...createBase, legacy: true },
  ]) {
    assert.throws(
      () => authority.createWorkspace(input),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_lifecycle_input_invalid',
    );
  }
  assert.throws(
    () =>
      authority.updateWorkspace({
        config: runtimeConfig({ workspaceId: 'workspace-1' }),
        workspaceId: 'workspace-2',
        input: updateInput(),
      }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_lifecycle_input_invalid',
  );
  assert.equal(acquisitions, 0);
});

test('response validation rejects identity, name and shape drift', async () => {
  for (const created of [
    workspace({ tenant_id: 'tenant-2' }),
    workspace({ project_id: 'project-2' }),
    workspace({ name: 'Different name' }),
    workspace({ id: '' }),
    { ...workspace(), legacy: true },
  ]) {
    await assert.rejects(
      operations(acceptedActions(serviceFixture([], { created }), 'sha256:bad-create'))
        .createWorkspace({ config: runtimeConfig(), input: createInput() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_lifecycle_response_invalid',
    );
  }
  await assert.rejects(
    operations(
      acceptedActions(
        serviceFixture([], {
          updated: workspace({ id: 'workspace-2', name: 'Updated workspace' }),
        }),
        'sha256:bad-update',
      ),
    ).updateWorkspace({
      config: runtimeConfig({ workspaceId: 'workspace-1' }),
      workspaceId: 'workspace-1',
      input: updateInput(),
    }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_lifecycle_response_invalid',
  );
});

test('missing, rejected, malformed and escaped authorities fail closed', async () => {
  assert.throws(
    () => operations(null).createWorkspace({ config: runtimeConfig(), input: createInput() }),
    (error) =>
      error instanceof DesktopWorkspaceLifecycleAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  for (const runtimeCode of ['missing_service', 'service_version_mismatch']) {
    await assert.rejects(
      operations({
        acquireServiceOperationLease: async () => ({
          status: 'rejected',
          reasonCode: 'desktop_renderer_service_resolve_failed',
          runtimeCode,
        }),
      }).createWorkspace({ config: runtimeConfig(), input: createInput() }),
      (error) =>
        error instanceof DesktopWorkspaceLifecycleAuthorityUnavailableErrorV2 &&
        error.runtimeCode === runtimeCode,
    );
  }
  for (const service of [
    {},
    { bindOperation: () => ({}) },
    {
      bindOperation: () => ({
        createWorkspace: async () => workspace(),
        updateWorkspace: async () => workspace(),
        legacyFallback: () => undefined,
      }),
    },
  ]) {
    await assert.rejects(
      operations(acceptedActions(service, 'sha256:invalid-service')).createWorkspace({
        config: runtimeConfig(),
        input: createInput(),
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_lifecycle_service_invalid',
    );
  }

  let escaped;
  await withDesktopWorkspaceLifecycleAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    { config: runtimeConfig(), input: createInput() },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  assert.throws(
    () => escaped.createWorkspace(createInput()),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_lifecycle_operation_released',
  );
});

test('operation failure outranks release failure while successful cleanup failure surfaces', async () => {
  let failureReleases = 0;
  const failingActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) =>
        operation(serviceFixture([], { created: Promise.reject(new Error('create_failed')) })),
      release: async () => {
        failureReleases += 1;
        throw new Error('release_failed');
      },
    }),
  };
  await assert.rejects(
    operations(failingActions).createWorkspace({ config: runtimeConfig(), input: createInput() }),
    /create_failed/u,
  );
  assert.equal(failureReleases, 1);

  let successReleases = 0;
  const successfulActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) => operation(serviceFixture()),
      release: async () => {
        successReleases += 1;
        throw new Error('release_failed');
      },
    }),
  };
  await assert.rejects(
    operations(successfulActions).createWorkspace({
      config: runtimeConfig(),
      input: createInput(),
    }),
    /release_failed/u,
  );
  assert.equal(successReleases, 1);
});

test('HMR pins an in-flight mutation and routes the next mutation to the new generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  let actions = acceptedActions(
    serviceFixture([], { created: oldResponse }),
    'sha256:old',
    lifecycle,
  );
  const authority = createDesktopWorkspaceLifecycleOperationsV2(() => actions);
  const input = { config: runtimeConfig(), input: createInput() };
  const oldPending = authority.createWorkspace(input);
  actions = acceptedActions(
    serviceFixture([], { created: workspace({ id: 'workspace-new' }) }),
    'sha256:new',
    lifecycle,
  );
  const next = await authority.createWorkspace(input);
  resolveOld(workspace({ id: 'workspace-old' }));
  const old = await oldPending;

  assert.equal(next.id, 'workspace-new');
  assert.equal(old.id, 'workspace-old');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    ['acquire:sha256:old', 'acquire:sha256:new', 'release:sha256:new', 'release:sha256:old'],
  );
});
