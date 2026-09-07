import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopProjectTeamAuthorityUnavailableErrorV2,
  createDesktopProjectTeamOperationsV2,
  withDesktopProjectTeamAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopProjectTeamAuthorityModuleV2.js');
const { createDesktopProjectTeamHttpAuthorityV2 } = require(
  COMPILED_ROOT + '/src/plugins/desktopProjectTeamHttpProjectionV2.js',
);
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'https://cloud.memstack.test',
    apiKey: 'team-session',
    localApiToken: 'team-launch',
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

function member(userId = 'user-1') {
  return {
    userId,
    email: `${userId}@example.test`,
    name: 'Project member',
    role: 'member',
    permissions: { read: true, write: false },
    createdAt: '2026-09-03T00:00:00Z',
  };
}

function agent(id = 'agent-1') {
  return {
    id,
    name: `Agent ${id}`,
    enabled: true,
    model: null,
  };
}

function result(operationScope = scope(), userId = 'user-1') {
  return {
    scope: operationScope,
    scopeRevision: 41,
    authority: 'cloud',
    availability: 'degraded',
    reasonCode: 'desktop_project_team_actions_partial',
    allowedActions: ['view', 'list-members', 'list-agent-teammates'],
    members: [member(userId)],
    agents: [agent()],
    currentUserRole: 'member',
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

test('Project Team load freezes input and holds one exact project generation lease', async () => {
  const received = [];
  const lifecycle = [];
  const config = runtimeConfig();
  const operationScope = scope();
  const controller = new AbortController();
  const operations = createDesktopProjectTeamOperationsV2(() =>
    acceptedActions(serviceFixture(received), 'digest-team', lifecycle),
  );
  const pending = operations.loadProjectTeam({
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
    snapshot.members,
    snapshot.members[0],
    snapshot.members[0].permissions,
    snapshot.agents,
    snapshot.agents[0],
  ]) {
    assert.equal(Object.isFrozen(value), true);
  }
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'digest-team',
      request: {
        service: 'service:desktop-renderer.project-team-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'digest-team' },
  ]);
  assert.equal(Object.isFrozen(received[0].config), true);
  assert.equal(Object.isFrozen(received[0].scope), true);
  assert.deepEqual(received[1], { type: 'load', signal: controller.signal });
});

test('invalid Project Team scope, signal and unknown fields fail before acquisition', () => {
  let acquisitions = 0;
  const operations = createDesktopProjectTeamOperationsV2(() => ({
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
      () => operations.loadProjectTeam(invalidInput),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_team_operation_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
  assert.throws(
    () =>
      createDesktopProjectTeamOperationsV2(() => null).loadProjectTeam({
        config: runtimeConfig(),
        scope: scope(),
      }),
    (error) =>
      error instanceof DesktopProjectTeamAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
});

test('missing or malformed Project Team service, authority and snapshots fail closed', async () => {
  await assert.rejects(
    createDesktopProjectTeamOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return {
          status: 'rejected',
          reasonCode: 'missing_service',
          runtimeCode: 'missing_service',
        };
      },
    })).loadProjectTeam({ config: runtimeConfig(), scope: scope() }),
    (error) =>
      error instanceof DesktopProjectTeamAuthorityUnavailableErrorV2 &&
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
      createDesktopProjectTeamOperationsV2(() =>
        acceptedActions(service, 'invalid-shape'),
      ).loadProjectTeam({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error && error.code === 'desktop_project_team_service_invalid',
    );
  }
  const valid = result();
  for (const invalidResult of [
    { ...valid, availability: 'available', reasonCode: null },
    { ...valid, reasonCode: 'partial' },
    { ...valid, allowedActions: [...valid.allowedActions, 'invite'] },
    { ...valid, scopeRevision: -1 },
    { ...valid, scope: scope('cloud', { projectId: 'project-2' }) },
    { ...valid, currentUserRole: 'superuser' },
    { ...valid, members: [{ ...valid.members[0], role: 'superuser' }] },
    { ...valid, members: [{ ...valid.members[0], email: '' }] },
    { ...valid, members: [valid.members[0], valid.members[0]] },
    { ...valid, agents: [{ ...valid.agents[0], enabled: 'yes' }] },
    { ...valid, agents: [valid.agents[0], valid.agents[0]] },
    { ...valid, extra: true },
  ]) {
    await assert.rejects(
      createDesktopProjectTeamOperationsV2(() =>
        acceptedActions(serviceFixture([], { result: invalidResult }), 'invalid-result'),
      ).loadProjectTeam({ config: runtimeConfig(), scope: scope() }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_project_team_service_contract_invalid',
    );
  }
});

test('HTTP projection keeps context, identity, members and agents in one authority', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    requests.push({ input: String(input), init });
    const url = new URL(String(input));
    if (url.pathname === '/api/v1/workspace-context') {
      return jsonResponse({
        context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 59 },
      });
    }
    if (url.pathname === '/api/v1/auth/me') {
      return jsonResponse({ id: 'user-1' });
    }
    if (url.pathname === '/api/v1/projects/project-1/members') {
      return jsonResponse({
        members: [
          {
            user_id: 'user-1',
            email: 'user-1@example.test',
            name: 'Project owner',
            role: 'owner',
            permissions: { read: true, write: true },
            created_at: '2026-09-03T00:00:00Z',
          },
        ],
        total: 1,
      });
    }
    if (url.pathname === '/api/v1/agent/definitions') {
      return jsonResponse({
        definitions: [
          {
            id: 'agent-1',
            project_id: 'project-1',
            display_name: 'Research Agent',
            enabled: true,
            model: null,
          },
        ],
        total: 1,
      });
    }
    throw new Error(`unexpected request: ${String(input)}`);
  };
  try {
    const authority = createDesktopProjectTeamHttpAuthorityV2(runtimeConfig(), scope());
    const snapshot = await authority.load();
    assert.equal(snapshot.scopeRevision, 59);
    assert.equal(snapshot.reasonCode, 'desktop_project_team_actions_partial');
    assert.deepEqual(snapshot.allowedActions, ['view', 'list-members', 'list-agent-teammates']);
    assert.equal(snapshot.currentUserRole, 'owner');
    assert.equal(snapshot.members[0].userId, 'user-1');
    assert.equal(snapshot.agents[0].id, 'agent-1');
    assert.equal(requests.length, 4);
    const agentQuery = new URL(requests[3].input).searchParams;
    assert.equal(agentQuery.get('tenant_id'), 'tenant-1');
    assert.equal(agentQuery.get('project_id'), 'project-1');
    assert.equal(agentQuery.get('include_total'), 'true');
    for (const { init } of requests) {
      assert.equal(init.credentials, 'omit');
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer team-session');
      assert.doesNotMatch(JSON.stringify(init), /team-launch/u);
    }
    await assert.rejects(
      createDesktopProjectTeamHttpAuthorityV2(
        runtimeConfig({ mode: 'local' }),
        scope('local'),
      ).load(),
      (error) =>
        error.status === 501 &&
        error.payload.reason_code === 'local_project_team_authority_unavailable',
    );
    assert.equal(requests.length, 4);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('escaped Project Team authority is revoked and primary failure wins over release failure', async () => {
  let escaped;
  await withDesktopProjectTeamAuthorityOperationV2(
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
      error instanceof RuntimeV2Error && error.code === 'desktop_project_team_operation_released',
  );
  const primary = new Error('primary_failure');
  const release = new Error('release_failure');
  await assert.rejects(
    withDesktopProjectTeamAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-failure', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      async () => {
        throw primary;
      },
    ),
    (error) => error === primary,
  );
  await assert.rejects(
    withDesktopProjectTeamAuthorityOperationV2(
      acceptedActions(serviceFixture([]), 'digest-release', [], release),
      { kind: 'load', config: runtimeConfig(), scope: scope() },
      (authority) => authority.load(),
    ),
    (error) => error === release,
  );
});

test('old Project Team request stays pinned while replacement generation serves new requests', async () => {
  let releaseOld;
  const gate = new Promise((resolve) => {
    releaseOld = resolve;
  });
  const oldService = serviceFixture([], { result: result(scope(), 'old-user') });
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
  const operations = createDesktopProjectTeamOperationsV2(() => actions);
  const oldRequest = operations.loadProjectTeam({ config: runtimeConfig(), scope: scope() });
  actions = acceptedActions(serviceFixture([], { result: result(scope(), 'new-user') }), 'new');
  const newRequest = operations.loadProjectTeam({ config: runtimeConfig(), scope: scope() });
  releaseOld();
  assert.equal((await oldRequest).members[0].userId, 'old-user');
  assert.equal((await newRequest).members[0].userId, 'new-user');
});

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
