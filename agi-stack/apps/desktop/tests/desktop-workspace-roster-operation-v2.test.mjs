import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopWorkspaceRosterAuthorityUnavailableErrorV2,
  createDesktopWorkspaceRosterOperationsV2,
  withDesktopWorkspaceRosterAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceRosterAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46981',
    apiKey: 'workspace-roster-session',
    localApiToken: 'workspace-roster-launch',
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
    user_email: 'member@example.com',
    role: 'owner',
    invited_by: null,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: null,
    ...overrides,
  };
}

function agent(overrides = {}) {
  return {
    id: 'binding-1',
    workspace_id: 'workspace-1',
    agent_id: 'agent-1',
    display_name: 'Planner',
    description: null,
    config: { model: { id: 'planner-v1' } },
    is_active: true,
    hex_q: null,
    hex_r: null,
    theme_color: null,
    label: null,
    status: 'idle',
    created_at: '2026-09-02T00:00:00Z',
    updated_at: null,
    ...overrides,
  };
}

function serviceFixture(received = [], overrides = {}) {
  return Object.freeze({
    bindOperation(config) {
      received.push({ kind: 'bind-operation', config });
      return Object.freeze({
        async listWorkspaceMembers(signal) {
          received.push({ kind: 'members', signal });
          if (overrides.membersError) throw overrides.membersError;
          return overrides.members ?? [member({ workspace_id: config.workspaceId })];
        },
        async listWorkspaceAgents(signal) {
          received.push({ kind: 'agents', signal });
          if (overrides.agentsError) throw overrides.agentsError;
          return overrides.agents ?? [agent({ workspace_id: config.workspaceId })];
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
  return createDesktopWorkspaceRosterOperationsV2(() => actions);
}

test('member and Agent reads freeze scope and signal before lease acquisition', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const authority = operations(
    acceptedActions(serviceFixture(received), 'sha256:generation-1', lifecycle)
  );

  const membersPending = authority.listWorkspaceMembers({
    config,
    signal: controller.signal,
  });
  const agentsPending = authority.listWorkspaceAgents({
    config,
    signal: controller.signal,
  });
  config.tenantId = 'mutated-tenant';
  config.projectId = 'mutated-project';
  config.workspaceId = 'mutated-workspace';

  const [members, agents] = await Promise.all([membersPending, agentsPending]);
  assert.equal(members[0].workspace_id, 'workspace-1');
  assert.equal(agents[0].workspace_id, 'workspace-1');
  assert.equal(Object.isFrozen(members), true);
  assert.equal(Object.isFrozen(members[0]), true);
  assert.equal(Object.isFrozen(agents), true);
  assert.equal(Object.isFrozen(agents[0]), true);
  assert.equal(Object.isFrozen(agents[0].config), true);
  assert.equal(Object.isFrozen(agents[0].config.model), true);
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ request }) => request),
    Array.from({ length: 2 }, () => ({
      service: 'service:desktop-renderer.workspace-roster-authority',
      version: '1.0.0',
      scope: { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
    }))
  );
  const bindings = received.filter(({ kind }) => kind === 'bind-operation');
  assert.equal(bindings.length, 2);
  assert.equal(
    bindings.every(({ config: bound }) => Object.isFrozen(bound)),
    true
  );
  assert.equal(
    bindings.every(({ config: bound }) => bound.workspaceId === 'workspace-1'),
    true
  );
  assert.equal(
    received
      .filter(({ kind }) => kind === 'members' || kind === 'agents')
      .every(({ signal }) => signal === controller.signal),
    true
  );
});

test('invalid roster inputs fail before lease acquisition', () => {
  let acquisitions = 0;
  const authority = operations({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  });
  const base = { config: runtimeConfig() };
  for (const input of [
    { config: runtimeConfig({ tenantId: '' }) },
    { config: runtimeConfig({ projectId: ' project-1' }) },
    { config: runtimeConfig({ workspaceId: '' }) },
    { config: runtimeConfig({ workspaceId: 'workspace-1 ' }) },
    { config: runtimeConfig({ mode: 'legacy' }) },
    { ...base, signal: {} },
    { ...base, legacy: true },
  ]) {
    assert.throws(
      () => authority.listWorkspaceMembers(input),
      (error) =>
        error instanceof RuntimeV2Error && error.code === 'desktop_workspace_roster_input_invalid'
    );
  }
  assert.equal(acquisitions, 0);
});

test('response validation rejects scope, role, shape and duplicate identity drift', async () => {
  for (const members of [
    [member({ workspace_id: 'workspace-2' })],
    [member({ role: 'manager' })],
    [{ ...member(), legacy: true }],
    [member(), member()],
  ]) {
    await assert.rejects(
      operations(
        acceptedActions(serviceFixture([], { members }), 'sha256:bad-members')
      ).listWorkspaceMembers({ config: runtimeConfig() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_roster_response_invalid'
    );
  }
  for (const agents of [
    [agent({ workspace_id: 'workspace-2' })],
    [agent({ is_active: 'yes' })],
    [{ ...agent(), legacy: true }],
    [agent(), agent()],
  ]) {
    await assert.rejects(
      operations(
        acceptedActions(serviceFixture([], { agents }), 'sha256:bad-agents')
      ).listWorkspaceAgents({ config: runtimeConfig() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_roster_response_invalid'
    );
  }
});

test('missing, rejected, malformed and escaped roster authorities fail closed', async () => {
  assert.throws(
    () => operations(null).listWorkspaceMembers({ config: runtimeConfig() }),
    (error) =>
      error instanceof DesktopWorkspaceRosterAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable'
  );
  for (const runtimeCode of ['missing_service', 'service_version_mismatch']) {
    await assert.rejects(
      operations({
        acquireServiceOperationLease: async () => ({
          status: 'rejected',
          reasonCode: 'desktop_renderer_service_resolve_failed',
          runtimeCode,
        }),
      }).listWorkspaceMembers({ config: runtimeConfig() }),
      (error) =>
        error instanceof DesktopWorkspaceRosterAuthorityUnavailableErrorV2 &&
        error.runtimeCode === runtimeCode
    );
  }
  for (const service of [
    {},
    { bindOperation: () => ({}) },
    {
      bindOperation: () => ({
        listWorkspaceMembers: async () => [],
        listWorkspaceAgents: async () => [],
        legacyFallback: () => undefined,
      }),
    },
  ]) {
    await assert.rejects(
      operations(acceptedActions(service, 'sha256:invalid-service')).listWorkspaceMembers({
        config: runtimeConfig(),
      }),
      (error) =>
        error instanceof RuntimeV2Error && error.code === 'desktop_workspace_roster_service_invalid'
    );
  }

  let escaped;
  await withDesktopWorkspaceRosterAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    { config: runtimeConfig() },
    (authority) => {
      escaped = authority;
      return 'complete';
    }
  );
  assert.throws(
    () => escaped.listWorkspaceMembers(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_roster_operation_released'
  );
});

test('operation failure outranks release failure while successful cleanup failure surfaces', async () => {
  let failureReleases = 0;
  const failingActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) =>
        operation(serviceFixture([], { membersError: new Error('members_failed') })),
      release: async () => {
        failureReleases += 1;
        throw new Error('release_failed');
      },
    }),
  };
  await assert.rejects(
    operations(failingActions).listWorkspaceMembers({ config: runtimeConfig() }),
    /members_failed/u
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
    operations(successfulActions).listWorkspaceMembers({ config: runtimeConfig() }),
    /release_failed/u
  );
  assert.equal(successReleases, 1);
});

test('HMR pins an in-flight roster read and routes the next read to the new generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  let actions = acceptedActions(
    serviceFixture([], { members: oldResponse }),
    'sha256:old',
    lifecycle
  );
  const authority = createDesktopWorkspaceRosterOperationsV2(() => actions);
  const input = { config: runtimeConfig() };
  const oldPending = authority.listWorkspaceMembers(input);
  actions = acceptedActions(
    serviceFixture([], { members: [member({ id: 'member-new' })] }),
    'sha256:new',
    lifecycle
  );
  const next = await authority.listWorkspaceMembers(input);
  resolveOld([member({ id: 'member-old' })]);
  const old = await oldPending;

  assert.equal(next[0].id, 'member-new');
  assert.equal(old[0].id, 'member-old');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    ['acquire:sha256:old', 'acquire:sha256:new', 'release:sha256:new', 'release:sha256:old']
  );
});
