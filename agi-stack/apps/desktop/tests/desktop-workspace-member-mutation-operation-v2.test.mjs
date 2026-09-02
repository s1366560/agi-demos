import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopWorkspaceMemberMutationAuthorityUnavailableErrorV2,
  createDesktopWorkspaceMemberMutationOperationsV2,
  withDesktopWorkspaceMemberMutationAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceMemberMutationAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46951',
    apiKey: 'workspace-member-session',
    localApiToken: 'workspace-member-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace/project-1',
    ...overrides,
  };
}

function member(overrides = {}) {
  return {
    id: 'member-1',
    workspace_id: 'workspace-1',
    user_id: 'user-1',
    user_email: 'member@example.test',
    role: 'viewer',
    invited_by: 'owner-1',
    created_at: '2026-09-02T00:00:00Z',
    updated_at: null,
    ...overrides,
  };
}

function serviceFixture(received = [], overrides = {}) {
  return Object.freeze({
    bindOperation(config, workspaceId) {
      received.push({ kind: 'bind-operation', config, workspaceId });
      return Object.freeze({
        async addMember(userId, role, signal) {
          received.push({ kind: 'add', userId, role, signal });
          return overrides.added ?? member({ user_id: userId, role });
        },
        async updateMemberRole(userId, role, signal) {
          received.push({ kind: 'update-role', userId, role, signal });
          return overrides.updated ?? member({ user_id: userId, role });
        },
        async removeMember(userId, signal) {
          received.push({ kind: 'remove', userId, signal });
          return overrides.removeResult;
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
  return createDesktopWorkspaceMemberMutationOperationsV2(() => actions);
}

test('operations freeze project scope, workspace, user, role and signal before leases', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const authority = operations(
    acceptedActions(serviceFixture(received), 'sha256:generation-1', lifecycle),
  );

  const addedPending = authority.addWorkspaceMember({
    config,
    workspaceId: 'workspace-1',
    userId: 'user-1',
    role: 'viewer',
    signal: controller.signal,
  });
  const updatedPending = authority.updateWorkspaceMemberRole({
    config,
    workspaceId: 'workspace-1',
    userId: 'user-1',
    role: 'editor',
    signal: controller.signal,
  });
  const removedPending = authority.removeWorkspaceMember({
    config,
    workspaceId: 'workspace-1',
    userId: 'user-1',
    signal: controller.signal,
  });
  config.tenantId = 'mutated-tenant';

  const [added, updated] = await Promise.all([addedPending, updatedPending, removedPending]);
  assert.equal(Object.isFrozen(authority), true);
  assert.equal(added.role, 'viewer');
  assert.equal(updated.role, 'editor');
  assert.equal(Object.isFrozen(added), true);
  assert.equal(Object.isFrozen(updated), true);
  assert.equal(received.filter(({ kind }) => kind === 'bind-operation').length, 3);
  for (const item of received.filter(({ kind }) => kind === 'bind-operation')) {
    assert.equal(item.config.tenantId, 'tenant-1');
    assert.equal(item.workspaceId, 'workspace-1');
    assert.equal(Object.isFrozen(item.config), true);
  }
  assert.equal(
    received.every(({ userId }) => userId === undefined || userId === 'user-1'),
    true,
  );
  assert.equal(
    received.every(({ signal }) => signal === undefined || signal === controller.signal),
    true,
  );
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ request }) => request),
    Array.from({ length: 3 }, () => ({
      service: 'service:desktop-renderer.workspace-member-mutation-authority',
      version: '1.0.0',
      scope: {
        kind: 'project',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
      },
    })),
  );
});

test('invalid inputs fail before lease acquisition', () => {
  let acquisitions = 0;
  const authority = operations({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  });
  const base = {
    config: runtimeConfig(),
    workspaceId: 'workspace-1',
    userId: 'user-1',
    role: 'viewer',
  };
  for (const input of [
    { ...base, config: runtimeConfig({ tenantId: '' }) },
    { ...base, workspaceId: ' workspace-1' },
    { ...base, workspaceId: 'workspace-2' },
    { ...base, userId: '' },
    { ...base, userId: ' user-1' },
    { ...base, role: 'admin' },
    { ...base, signal: {} },
    { ...base, legacy: true },
  ]) {
    assert.throws(
      () => authority.addWorkspaceMember(input),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_member_mutation_input_invalid',
    );
  }
  assert.throws(
    () => authority.removeWorkspaceMember({ ...base, role: undefined }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_member_mutation_input_invalid',
  );
  assert.equal(acquisitions, 0);
});

test('response validation rejects workspace, user, role and shape drift', async () => {
  for (const added of [
    member({ workspace_id: 'workspace-2' }),
    member({ user_id: 'user-2' }),
    member({ role: 'editor' }),
    member({ id: '' }),
    { ...member(), legacy: true },
  ]) {
    await assert.rejects(
      operations(
        acceptedActions(serviceFixture([], { added }), 'sha256:bad-member'),
      ).addWorkspaceMember({
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
        userId: 'user-1',
        role: 'viewer',
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_member_mutation_response_invalid',
    );
  }
  await assert.rejects(
    operations(
      acceptedActions(serviceFixture([], { removeResult: { ok: true } }), 'sha256:bad-remove'),
    ).removeWorkspaceMember({
      config: runtimeConfig(),
      workspaceId: 'workspace-1',
      userId: 'user-1',
    }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_member_mutation_response_invalid',
  );
});

test('missing generation, rejected or malformed service and escaped authority fail closed', async () => {
  assert.throws(
    () =>
      operations(null).addWorkspaceMember({
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
        userId: 'user-1',
        role: 'viewer',
      }),
    (error) =>
      error instanceof DesktopWorkspaceMemberMutationAuthorityUnavailableErrorV2 &&
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
      }).addWorkspaceMember({
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
        userId: 'user-1',
        role: 'viewer',
      }),
      (error) =>
        error instanceof DesktopWorkspaceMemberMutationAuthorityUnavailableErrorV2 &&
        error.runtimeCode === runtimeCode,
    );
  }
  for (const service of [
    {},
    { bindOperation: () => ({}) },
    {
      bindOperation: () => ({
        addMember: async () => member(),
        updateMemberRole: async () => member({ role: 'editor' }),
        removeMember: async () => undefined,
        legacyFallback: () => undefined,
      }),
    },
  ]) {
    await assert.rejects(
      operations(acceptedActions(service, 'sha256:invalid-service')).addWorkspaceMember({
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
        userId: 'user-1',
        role: 'viewer',
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_member_mutation_service_invalid',
    );
  }

  let escaped;
  await withDesktopWorkspaceMemberMutationAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    {
      config: runtimeConfig(),
      workspaceId: 'workspace-1',
      userId: 'user-1',
      role: 'viewer',
    },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  assert.throws(
    () => escaped.addMember('user-1', 'viewer'),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_member_mutation_operation_released',
  );
});

test('operation error outranks release error and success surfaces release failure once', async () => {
  let failureReleases = 0;
  const failingActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) =>
        operation(
          serviceFixture([], {
            added: Promise.reject(new Error('member_operation_failed')),
          }),
        ),
      release: async () => {
        failureReleases += 1;
        throw new Error('member_release_failed');
      },
    }),
  };
  await assert.rejects(
    operations(failingActions).addWorkspaceMember({
      config: runtimeConfig(),
      workspaceId: 'workspace-1',
      userId: 'user-1',
      role: 'viewer',
    }),
    /member_operation_failed/u,
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
        throw new Error('member_release_failed');
      },
    }),
  };
  await assert.rejects(
    operations(successfulActions).addWorkspaceMember({
      config: runtimeConfig(),
      workspaceId: 'workspace-1',
      userId: 'user-1',
      role: 'viewer',
    }),
    /member_release_failed/u,
  );
  assert.equal(successReleases, 1);
});

test('HMR pins an in-flight mutation while the next mutation uses replacement generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  let actions = acceptedActions(
    serviceFixture([], { added: oldResponse }),
    'sha256:old',
    lifecycle,
  );
  const authority = createDesktopWorkspaceMemberMutationOperationsV2(() => actions);
  const input = {
    config: runtimeConfig(),
    workspaceId: 'workspace-1',
    userId: 'user-1',
    role: 'viewer',
  };
  const oldPending = authority.addWorkspaceMember(input);
  actions = acceptedActions(
    serviceFixture([], { added: member({ id: 'member-new' }) }),
    'sha256:new',
    lifecycle,
  );
  const next = await authority.addWorkspaceMember(input);
  resolveOld(member({ id: 'member-old' }));
  const old = await oldPending;

  assert.equal(next.id, 'member-new');
  assert.equal(old.id, 'member-old');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    ['acquire:sha256:old', 'acquire:sha256:new', 'release:sha256:new', 'release:sha256:old'],
  );
});
