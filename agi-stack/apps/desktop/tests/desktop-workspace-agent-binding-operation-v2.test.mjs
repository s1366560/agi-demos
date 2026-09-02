import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopWorkspaceAgentBindingAuthorityUnavailableErrorV2,
  createDesktopWorkspaceAgentBindingOperationsV2,
  withDesktopWorkspaceAgentBindingAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceAgentBindingAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46941',
    apiKey: 'workspace-agent-binding-session',
    localApiToken: 'workspace-agent-binding-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace/project-1',
    ...overrides,
  };
}

function definition(overrides = {}) {
  return {
    id: 'agent-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: 'project-agent',
    display_name: 'Project Agent',
    enabled: true,
    model: 'project-model',
    ...overrides,
  };
}

function binding(overrides = {}) {
  return {
    id: 'binding-1',
    workspace_id: 'workspace-1',
    agent_id: 'agent-1',
    display_name: 'Project Agent',
    description: 'Workspace helper',
    config: { source: 'desktop' },
    is_active: true,
    hex_q: null,
    hex_r: null,
    theme_color: null,
    label: null,
    status: null,
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
        async listAgentDefinitions(signal) {
          received.push({ kind: 'list', signal });
          return overrides.definitions ?? [definition()];
        },
        async bindAgent(input, signal) {
          received.push({ kind: 'bind-agent', input, signal });
          return overrides.binding ?? binding();
        },
        async unbindAgent(bindingId, signal) {
          received.push({ kind: 'unbind-agent', bindingId, signal });
          return overrides.unbindResult;
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
  return createDesktopWorkspaceAgentBindingOperationsV2(() => actions);
}

test('operations freeze project scope, workspace identity, bind input and signal before leases', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const bindInput = {
    agentId: 'agent-1',
    displayName: ' Project Agent ',
    description: ' Helper ',
  };
  const authority = operations(
    acceptedActions(serviceFixture(received), 'sha256:generation-1', lifecycle),
  );

  const listPending = authority.listWorkspaceBindingAgentDefinitions({
    config,
    workspaceId: 'workspace-1',
    signal: controller.signal,
  });
  const bindPending = authority.bindWorkspaceAgent({
    config,
    workspaceId: 'workspace-1',
    input: bindInput,
    signal: controller.signal,
  });
  const unbindPending = authority.unbindWorkspaceAgent({
    config,
    workspaceId: 'workspace-1',
    bindingId: 'binding-1',
    signal: controller.signal,
  });
  config.tenantId = 'mutated-tenant';
  bindInput.agentId = 'mutated-agent';

  const [definitions, created] = await Promise.all([listPending, bindPending, unbindPending]).then(
    ([listed, bound]) => [listed, bound],
  );
  assert.equal(Object.isFrozen(authority), true);
  assert.equal(definitions[0].id, 'agent-1');
  assert.equal(created.id, 'binding-1');
  assert.equal(Object.isFrozen(definitions), true);
  assert.equal(Object.isFrozen(definitions[0]), true);
  assert.equal(Object.isFrozen(created), true);
  assert.equal(Object.isFrozen(created.config), true);
  assert.equal(received.filter(({ kind }) => kind === 'bind-operation').length, 3);
  for (const item of received.filter(({ kind }) => kind === 'bind-operation')) {
    assert.equal(item.config.tenantId, 'tenant-1');
    assert.equal(item.workspaceId, 'workspace-1');
    assert.equal(Object.isFrozen(item.config), true);
  }
  assert.deepEqual(received.find(({ kind }) => kind === 'bind-agent').input, {
    agentId: 'agent-1',
    displayName: 'Project Agent',
    description: 'Helper',
  });
  assert.equal(Object.isFrozen(received.find(({ kind }) => kind === 'bind-agent').input), true);
  assert.equal(
    received.every(({ signal }) => signal === undefined || signal === controller.signal),
    true,
  );
  assert.deepEqual(
    lifecycle.filter(({ type }) => type === 'acquire').map(({ request }) => request),
    Array.from({ length: 3 }, () => ({
      service: 'service:desktop-renderer.workspace-agent-binding-authority',
      version: '1.0.0',
      scope: {
        kind: 'project',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
      },
    })),
  );
});

test('invalid scope and operation inputs fail before lease acquisition', () => {
  let acquisitions = 0;
  const authority = operations({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  });
  const listCases = [
    { config: runtimeConfig({ tenantId: '' }), workspaceId: 'workspace-1' },
    {
      config: runtimeConfig({ projectId: ' project-1' }),
      workspaceId: 'workspace-1',
    },
    { config: runtimeConfig(), workspaceId: ' workspace-1' },
    { config: runtimeConfig(), workspaceId: 'workspace-1', signal: {} },
    { config: runtimeConfig(), workspaceId: 'workspace-1', legacy: true },
  ];
  for (const input of listCases) {
    assert.throws(
      () => authority.listWorkspaceBindingAgentDefinitions(input),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_agent_binding_input_invalid',
    );
  }
  for (const input of [
    {},
    { agentId: '' },
    { agentId: ' agent-1' },
    { agentId: 'agent-1', displayName: 1 },
    { agentId: 'agent-1', description: 'x'.repeat(501) },
    { agentId: 'agent-1', legacy: true },
  ]) {
    assert.throws(
      () =>
        authority.bindWorkspaceAgent({
          config: runtimeConfig(),
          workspaceId: 'workspace-1',
          input,
        }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_agent_binding_input_invalid',
    );
  }
  for (const bindingId of ['', ' binding-1']) {
    assert.throws(
      () =>
        authority.unbindWorkspaceAgent({
          config: runtimeConfig(),
          workspaceId: 'workspace-1',
          bindingId,
        }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_agent_binding_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
});

test('response validation rejects definition, binding and unbind scope or shape drift', async () => {
  for (const definitions of [
    [definition(), definition()],
    [definition({ tenant_id: 'tenant-2' })],
    [definition({ project_id: 'project-2' })],
    [definition({ enabled: false })],
    [{ ...definition(), legacy: true }],
  ]) {
    await assert.rejects(
      operations(
        acceptedActions(serviceFixture([], { definitions }), 'sha256:bad-definitions'),
      ).listWorkspaceBindingAgentDefinitions({
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_agent_binding_response_invalid',
    );
  }
  for (const value of [
    binding({ workspace_id: 'workspace-2' }),
    binding({ agent_id: 'agent-2' }),
    binding({ config: { score: Number.NaN } }),
    { ...binding(), legacy: true },
  ]) {
    await assert.rejects(
      operations(
        acceptedActions(serviceFixture([], { binding: value }), 'sha256:bad-binding'),
      ).bindWorkspaceAgent({
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
        input: { agentId: 'agent-1' },
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_agent_binding_response_invalid',
    );
  }
  await assert.rejects(
    operations(
      acceptedActions(serviceFixture([], { unbindResult: { ok: true } }), 'sha256:bad-unbind'),
    ).unbindWorkspaceAgent({
      config: runtimeConfig(),
      workspaceId: 'workspace-1',
      bindingId: 'binding-1',
    }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_agent_binding_response_invalid',
  );
});

test('missing generation, malformed service and escaped authority fail closed', async () => {
  assert.throws(
    () =>
      operations(null).listWorkspaceBindingAgentDefinitions({
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
      }),
    (error) =>
      error instanceof DesktopWorkspaceAgentBindingAuthorityUnavailableErrorV2 &&
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
      }).listWorkspaceBindingAgentDefinitions({
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
      }),
      (error) =>
        error instanceof DesktopWorkspaceAgentBindingAuthorityUnavailableErrorV2 &&
        error.runtimeCode === runtimeCode,
    );
  }
  for (const service of [
    {},
    { bindOperation: () => ({}) },
    {
      bindOperation: () => ({
        listAgentDefinitions: async () => [],
        bindAgent: async () => binding(),
        unbindAgent: async () => undefined,
        legacyFallback: () => undefined,
      }),
    },
  ]) {
    await assert.rejects(
      operations(
        acceptedActions(service, 'sha256:invalid-service'),
      ).listWorkspaceBindingAgentDefinitions({
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_agent_binding_service_invalid',
    );
  }

  let escaped;
  await withDesktopWorkspaceAgentBindingAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    { config: runtimeConfig(), workspaceId: 'workspace-1' },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  assert.throws(
    () => escaped.listAgentDefinitions(),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_agent_binding_operation_released',
  );
});

test('operation error outranks release error and success surfaces release failure', async () => {
  const failingActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) =>
        operation(
          serviceFixture([], {
            definitions: Promise.reject(new Error('binding_operation_failed')),
          }),
        ),
      release: async () => {
        throw new Error('binding_release_failed');
      },
    }),
  };
  await assert.rejects(
    operations(failingActions).listWorkspaceBindingAgentDefinitions({
      config: runtimeConfig(),
      workspaceId: 'workspace-1',
    }),
    /binding_operation_failed/u,
  );
  const successfulActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) => operation(serviceFixture()),
      release: async () => {
        throw new Error('binding_release_failed');
      },
    }),
  };
  await assert.rejects(
    operations(successfulActions).listWorkspaceBindingAgentDefinitions({
      config: runtimeConfig(),
      workspaceId: 'workspace-1',
    }),
    /binding_release_failed/u,
  );
});

test('HMR pins an in-flight read while the next read uses the replacement generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  let actions = acceptedActions(
    serviceFixture([], { definitions: oldResponse }),
    'sha256:old',
    lifecycle,
  );
  const authority = createDesktopWorkspaceAgentBindingOperationsV2(() => actions);
  const input = { config: runtimeConfig(), workspaceId: 'workspace-1' };
  const oldPending = authority.listWorkspaceBindingAgentDefinitions(input);
  actions = acceptedActions(
    serviceFixture([], { definitions: [definition({ id: 'agent-new' })] }),
    'sha256:new',
    lifecycle,
  );
  const next = await authority.listWorkspaceBindingAgentDefinitions(input);
  resolveOld([definition({ id: 'agent-old' })]);
  const old = await oldPending;

  assert.equal(next[0].id, 'agent-new');
  assert.equal(old[0].id, 'agent-old');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    ['acquire:sha256:old', 'acquire:sha256:new', 'release:sha256:new', 'release:sha256:old'],
  );
});
