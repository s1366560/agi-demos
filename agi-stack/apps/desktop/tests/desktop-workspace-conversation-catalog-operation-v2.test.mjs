import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopWorkspaceConversationCatalogAuthorityUnavailableErrorV2,
  createDesktopWorkspaceConversationCatalogOperationsV2,
  withDesktopWorkspaceConversationCatalogAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46931',
    apiKey: 'workspace-conversation-session',
    localApiToken: 'workspace-conversation-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace/project-1',
    ...overrides,
  };
}

function conversation(overrides = {}) {
  return {
    id: 'conversation-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    user_id: 'user-1',
    title: 'Conversation one',
    status: 'active',
    message_count: 2,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: null,
    summary: 'Summary',
    agent_config: { selected_agent_id: 'builtin:all-access' },
    metadata: { source: 'desktop' },
    conversation_mode: 'workspace',
    current_mode: 'act',
    workspace_id: 'workspace-1',
    linked_workspace_task_id: null,
    workspace_name: 'Workspace one',
    participant_agents: ['builtin:all-access'],
    coordinator_agent_id: null,
    focused_agent_id: 'builtin:all-access',
    ...overrides,
  };
}

function catalogResponse(items = [conversation()], overrides = {}) {
  return {
    items,
    total: items.length,
    has_more: false,
    offset: 0,
    limit: 500,
    next_offset: null,
    ...overrides,
  };
}

function serviceFixture(received = [], overrides = {}) {
  return Object.freeze({
    bindOperation(config) {
      received.push({ kind: 'bind', config });
      return Object.freeze({
        async listConversations(filters) {
          received.push({ kind: 'list', filters });
          return overrides.response ?? catalogResponse();
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
  return createDesktopWorkspaceConversationCatalogOperationsV2(() => actions);
}

test('facade freezes config and filters before an exact project generation lease', async () => {
  const lifecycle = [];
  const received = [];
  const controller = new AbortController();
  const config = runtimeConfig();
  const input = {
    config,
    workspaceId: 'workspace-1',
    unboundOnly: false,
    signal: controller.signal,
  };
  const authority = operations(
    acceptedActions(serviceFixture(received), 'sha256:generation-1', lifecycle),
  );
  const pending = authority.listConversations(input);
  config.tenantId = 'mutated-tenant';
  input.workspaceId = 'mutated-workspace';
  input.unboundOnly = true;
  const result = await pending;

  assert.equal(Object.isFrozen(authority), true);
  assert.deepEqual(lifecycle, [
    {
      type: 'acquire',
      digest: 'sha256:generation-1',
      request: {
        service: 'service:desktop-renderer.workspace-conversation-catalog-authority',
        version: '1.0.0',
        scope: {
          kind: 'project',
          tenant_id: 'tenant-1',
          project_id: 'project-1',
        },
      },
    },
    { type: 'release', digest: 'sha256:generation-1' },
  ]);
  const bind = received.find(({ kind }) => kind === 'bind');
  const list = received.find(({ kind }) => kind === 'list');
  assert.equal(bind.config.tenantId, 'tenant-1');
  assert.equal(Object.isFrozen(bind.config), true);
  assert.deepEqual(list.filters, {
    workspaceId: 'workspace-1',
    unboundOnly: false,
    signal: controller.signal,
  });
  assert.equal(Object.isFrozen(list.filters), true);
  assert.equal(Object.isFrozen(result), true);
  assert.equal(Object.isFrozen(result.items), true);
  assert.equal(Object.isFrozen(result.items[0]), true);
  assert.equal(Object.isFrozen(result.items[0].agent_config), true);
  assert.equal(Object.isFrozen(result.items[0].metadata), true);
  assert.equal(Object.isFrozen(result.items[0].participant_agents), true);
});

test('invalid config and filters fail before lease acquisition', async () => {
  let acquisitions = 0;
  const authority = operations({
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  });
  const cases = [
    { config: runtimeConfig({ tenantId: '' }), workspaceId: null, unboundOnly: true },
    { config: runtimeConfig({ projectId: ' project-1' }), workspaceId: null, unboundOnly: true },
    { config: runtimeConfig(), workspaceId: ' workspace-1', unboundOnly: false },
    { config: runtimeConfig(), workspaceId: 'workspace-1', unboundOnly: true },
    { config: runtimeConfig(), workspaceId: null, unboundOnly: 'yes' },
    { config: runtimeConfig(), workspaceId: undefined, unboundOnly: false },
    { config: runtimeConfig(), workspaceId: null, unboundOnly: false, legacy: true },
    { config: runtimeConfig(), workspaceId: null, unboundOnly: false, signal: {} },
  ];
  for (const input of cases) {
    assert.throws(
      () => authority.listConversations(input),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_conversation_catalog_input_invalid',
    );
  }
  assert.equal(acquisitions, 0);
});

test('response validation rejects scope, shape, duplicate, status and JSON drift', async () => {
  const invalidResponses = [
    catalogResponse([], { total: 1 }),
    catalogResponse([], { has_more: true }),
    catalogResponse([], { offset: 1 }),
    catalogResponse([], { limit: 100 }),
    catalogResponse([], { next_offset: 1 }),
    catalogResponse([conversation(), conversation()]),
    catalogResponse([conversation({ tenant_id: 'tenant-2' })]),
    catalogResponse([conversation({ project_id: 'project-2' })]),
    catalogResponse([conversation({ workspace_id: 'workspace-2' })]),
    catalogResponse([conversation({ status: 'archived' })]),
    catalogResponse([conversation({ message_count: -1 })]),
    catalogResponse([conversation({ metadata: { score: Number.NaN } })]),
    catalogResponse([conversation({ participant_agents: ['agent-1', 2] })]),
    { ...catalogResponse(), legacy_fallback: true },
  ];
  for (const response of invalidResponses) {
    await assert.rejects(
      operations(
        acceptedActions(serviceFixture([], { response }), 'sha256:invalid-response'),
      ).listConversations({
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
        unboundOnly: false,
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_conversation_catalog_response_invalid',
    );
  }

  await assert.rejects(
    operations(
      acceptedActions(
        serviceFixture([], {
          response: catalogResponse([conversation({ workspace_id: 'workspace-1' })]),
        }),
        'sha256:invalid-unbound-response',
      ),
    ).listConversations({
      config: runtimeConfig(),
      workspaceId: null,
      unboundOnly: true,
    }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_conversation_catalog_response_invalid',
  );
});

test('missing generation, invalid service and escaped authority fail closed', async () => {
  assert.throws(
    () =>
      operations(null).listConversations({
        config: runtimeConfig(),
        workspaceId: null,
        unboundOnly: true,
      }),
    (error) =>
      error instanceof DesktopWorkspaceConversationCatalogAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  await assert.rejects(
    operations({
      acquireServiceOperationLease: async () => ({
        status: 'rejected',
        reasonCode: 'desktop_renderer_service_resolve_failed',
        runtimeCode: 'missing_service',
      }),
    }).listConversations({
      config: runtimeConfig(),
      workspaceId: null,
      unboundOnly: true,
    }),
    (error) =>
      error instanceof DesktopWorkspaceConversationCatalogAuthorityUnavailableErrorV2 &&
      error.runtimeCode === 'missing_service',
  );
  for (const service of [
    {},
    { bindOperation: () => ({}) },
    {
      bindOperation: () => ({
        listConversations: async () => catalogResponse(),
        legacyFallback: () => undefined,
      }),
    },
  ]) {
    await assert.rejects(
      operations(acceptedActions(service, 'sha256:invalid-service')).listConversations({
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
        unboundOnly: false,
      }),
      (error) =>
        error instanceof RuntimeV2Error &&
        error.code === 'desktop_workspace_conversation_catalog_service_invalid',
    );
  }

  let escaped;
  await withDesktopWorkspaceConversationCatalogAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    {
      config: runtimeConfig(),
      workspaceId: 'workspace-1',
      unboundOnly: false,
    },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  assert.throws(
    () =>
      escaped.listConversations({
        workspaceId: 'workspace-1',
        unboundOnly: false,
      }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_conversation_catalog_operation_released',
  );
  await assert.rejects(
    withDesktopWorkspaceConversationCatalogAuthorityOperationV2(
      acceptedActions(serviceFixture(), 'sha256:filter-drift'),
      {
        config: runtimeConfig(),
        workspaceId: 'workspace-1',
        unboundOnly: false,
      },
      (authority) => authority.listConversations({ workspaceId: null, unboundOnly: true }),
    ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_workspace_conversation_catalog_input_invalid',
  );
});

test('operation error outranks release error and successful operation surfaces release failure', async () => {
  const actions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) =>
        operation({
          bindOperation: () => ({
            listConversations: async () => {
              throw new Error('conversation_catalog_operation_failed');
            },
          }),
        }),
      release: async () => {
        throw new Error('conversation_catalog_release_failed');
      },
    }),
  };
  await assert.rejects(
    operations(actions).listConversations({
      config: runtimeConfig(),
      workspaceId: 'workspace-1',
      unboundOnly: false,
    }),
    /conversation_catalog_operation_failed/u,
  );

  const successfulActions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) => operation(serviceFixture()),
      release: async () => {
        throw new Error('conversation_catalog_release_failed');
      },
    }),
  };
  await assert.rejects(
    operations(successfulActions).listConversations({
      config: runtimeConfig(),
      workspaceId: 'workspace-1',
      unboundOnly: false,
    }),
    /conversation_catalog_release_failed/u,
  );
});

test('HMR pins an in-flight read and routes the next read to the new generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  let actions = acceptedActions(
    serviceFixture([], { response: oldResponse }),
    'sha256:old',
    lifecycle,
  );
  const authority = createDesktopWorkspaceConversationCatalogOperationsV2(() => actions);
  const input = {
    config: runtimeConfig(),
    workspaceId: 'workspace-1',
    unboundOnly: false,
  };
  const oldPending = authority.listConversations(input);
  actions = acceptedActions(
    serviceFixture([], {
      response: catalogResponse([
        conversation({ id: 'conversation-new', title: 'New generation' }),
      ]),
    }),
    'sha256:new',
    lifecycle,
  );
  const next = await authority.listConversations(input);
  resolveOld(catalogResponse([conversation({ id: 'conversation-old', title: 'Old generation' })]));
  const old = await oldPending;

  assert.equal(next.items[0].id, 'conversation-new');
  assert.equal(old.items[0].id, 'conversation-old');
  assert.deepEqual(
    lifecycle.map(({ type, digest }) => `${type}:${digest}`),
    ['acquire:sha256:old', 'acquire:sha256:new', 'release:sha256:new', 'release:sha256:old'],
  );
});
