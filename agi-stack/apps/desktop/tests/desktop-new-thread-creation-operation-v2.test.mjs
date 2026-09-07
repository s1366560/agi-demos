import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const COMPILED_ROOT = '/tmp/agistack-desktop-test-dist';
const require = createRequire(import.meta.url);
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  DesktopNewThreadCreationAuthorityUnavailableErrorV2,
  createDesktopNewThreadCreationOperationsV2,
  withDesktopNewThreadCreationAuthorityOperationV2,
} = require(COMPILED_ROOT + '/src/plugins/desktopNewThreadCreationAuthorityModuleV2.js');
const { DEFAULT_CONFIG } = require(COMPILED_ROOT + '/src/types.js');

function runtimeConfig(overrides = {}) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:46751',
    apiKey: 'new-thread-session',
    localApiToken: 'new-thread-launch',
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '',
    ...overrides,
  };
}

function conversation(overrides = {}) {
  return {
    id: 'conversation-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    user_id: 'user-1',
    workspace_id: null,
    workspace_name: null,
    title: 'Start a task',
    summary: null,
    status: 'active',
    message_count: 0,
    agent_config: null,
    metadata: null,
    conversation_mode: 'single_agent',
    current_mode: null,
    linked_workspace_task_id: null,
    participant_agents: [],
    coordinator_agent_id: null,
    focused_agent_id: null,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: null,
    ...overrides,
  };
}

function workspace(overrides = {}) {
  return {
    id: 'workspace-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: 'Start a task',
    is_archived: false,
    ...overrides,
  };
}

function taskSessionRequest(overrides = {}) {
  return {
    idempotency_key: 'new-thread-session-1',
    workspace: { kind: 'existing', workspace_id: 'workspace-1' },
    conversation: { title: 'Start a task', capability_mode: 'work' },
    initial_message: {
      content: 'Prepare the implementation plan',
      context_items: [],
    },
    ...overrides,
  };
}

function taskSession(overrides = {}) {
  return {
    replayed: false,
    workspace: workspace(),
    conversation: conversation({
      workspace_id: 'workspace-1',
      conversation_mode: 'workspace',
      current_mode: 'plan',
      agent_config: {
        selected_agent_id: 'builtin:all-access',
        capability_mode: 'work',
      },
    }),
    initial_message: {
      id: 'message-1',
      workspace_id: 'workspace-1',
      sender_id: 'user-1',
      sender_type: 'human',
      content: 'Prepare the implementation plan',
      mentions: [],
      parent_message_id: null,
      metadata: { source: 'task_session', conversation_id: 'conversation-1' },
      created_at: '2026-09-02T00:00:00Z',
    },
    ...overrides,
  };
}

function serviceFixture(received = [], values = {}) {
  return Object.freeze({
    bindOperation(config) {
      received.push({ kind: 'bind', config });
      return Object.freeze({
        async createAgentConversation(
          title,
          projectId,
          expectedUserId,
          capabilityMode,
          agentConfig,
        ) {
          received.push({
            kind: 'createAgentConversation',
            title,
            projectId,
            expectedUserId,
            capabilityMode,
            agentConfig,
          });
          return (
            values.conversation ??
            conversation({ title, user_id: expectedUserId })
          );
        },
        async bindConversationWorkspace(value, signal) {
          received.push({ kind: 'bindConversationWorkspace', conversation: value, signal });
          return values.boundConversation ?? { ...value, workspace_id: config.workspaceId };
        },
        async createTaskSession(input) {
          received.push({ kind: 'createTaskSession', input });
          return values.taskSession ?? taskSession();
        },
        async runAgentMessage(
          conversationId,
          message,
          messageId,
          projectId,
          workloadRole,
          execution,
        ) {
          received.push({
            kind: 'runAgentMessage',
            conversationId,
            message,
            messageId,
            projectId,
            workloadRole,
            execution,
          });
          return values.queued ?? { queued: true };
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
test('facade freezes every input before exact project, project and session leases', async () => {
  const lifecycle = [];
  const received = [];
  const config = runtimeConfig();
  const actions = acceptedActions(
    serviceFixture(received),
    'sha256:generation-1',
    lifecycle,
  );
  const client = createDesktopNewThreadCreationOperationsV2(
    () => actions,
  ).bindOperation(config);
  const agentConfig = { llm_model_override: 'model-1' };
  const taskInput = taskSessionRequest();
  const execution = { agentId: 'agent-1' };
  const pending = [
    client.createAgentConversation(
      'Start a task',
      'project-1',
      'user-1',
      'work',
      agentConfig,
    ),
    client.createTaskSession(taskInput),
    client.runAgentMessage(
      'conversation-1',
      'Begin',
      'message-1',
      'project-1',
      'coding',
      execution,
    ),
  ];
  config.tenantId = 'mutated-tenant';
  config.projectId = 'mutated-project';
  agentConfig.llm_model_override = 'mutated-model';
  taskInput.conversation.title = 'mutated-title';
  execution.agentId = 'mutated-agent';
  await Promise.all(pending);

  assert.equal(Object.isFrozen(client), true);
  const bindings = received.filter(({ kind }) => kind === 'bind');
  assert.equal(bindings.length, 3);
  for (const binding of bindings) {
    assert.equal(Object.isFrozen(binding.config), true);
    assert.equal(binding.config.tenantId, 'tenant-1');
    assert.equal(binding.config.projectId, 'project-1');
  }
  assert.equal(
    received.find(({ kind }) => kind === 'createAgentConversation').agentConfig
      .llm_model_override,
    'model-1',
  );
  assert.equal(
    received.find(({ kind }) => kind === 'createTaskSession').input.conversation
      .title,
    'Start a task',
  );
  assert.equal(
    received.find(({ kind }) => kind === 'runAgentMessage').execution.agentId,
    'agent-1',
  );
  assert.deepEqual(
    lifecycle
      .filter(({ type }) => type === 'acquire')
      .map(({ request }) => request.scope),
    [
      { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
      { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
      {
        kind: 'session',
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        session_id: 'conversation-1',
      },
    ],
  );
  assert.equal(lifecycle.filter(({ type }) => type === 'release').length, 3);
});

test('malformed scope, input and response fail closed at the authority boundary', async () => {
  let acquisitions = 0;
  const neverActions = {
    acquireServiceOperationLease: async () => {
      acquisitions += 1;
      throw new Error('unexpected_acquire');
    },
  };
  let client = createDesktopNewThreadCreationOperationsV2(
    () => neverActions,
  ).bindOperation(runtimeConfig({ tenantId: '' }));
  await assert.rejects(
    client.createAgentConversation('Start a task', 'project-1', 'user-1'),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_new_thread_creation_input_invalid',
  );
  client = createDesktopNewThreadCreationOperationsV2(
    () => neverActions,
  ).bindOperation(runtimeConfig());
  await assert.rejects(
    client.createAgentConversation('Start a task', 'other-project', 'user-1'),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_new_thread_creation_scope_mismatch',
  );
  await assert.rejects(
    client.runAgentMessage('conversation-1', '', 'message-1', 'project-1'),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_new_thread_creation_input_invalid',
  );
  assert.equal(acquisitions, 0);

  const malformed = serviceFixture([], {
    conversation: conversation({ workspace_id: 'workspace-1' }),
  });
  const malformedClient = createDesktopNewThreadCreationOperationsV2(() =>
    acceptedActions(malformed, 'sha256:malformed'),
  ).bindOperation(runtimeConfig());
  await assert.rejects(
    malformedClient.createAgentConversation(
      'Start a task',
      'project-1',
      'user-1',
    ),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_new_thread_creation_response_invalid',
  );
});

test('missing service is structured, invalid shapes fail closed, and escaped authority is revoked', async () => {
  const unavailable = createDesktopNewThreadCreationOperationsV2(
    () => null,
  ).bindOperation(runtimeConfig());
  await assert.rejects(
    unavailable.createAgentConversation('Start a task', 'project-1', 'user-1'),
    (error) =>
      error instanceof DesktopNewThreadCreationAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_generation_actions_unavailable',
  );
  const rejected = createDesktopNewThreadCreationOperationsV2(() => ({
    acquireServiceOperationLease: async () => ({
      status: 'rejected',
      reasonCode: 'desktop_renderer_service_resolve_failed',
      runtimeCode: 'missing_service',
    }),
  })).bindOperation(runtimeConfig());
  await assert.rejects(
    rejected.runAgentMessage(
      'conversation-1',
      'Begin',
      'message-1',
      'project-1',
    ),
    (error) =>
      error instanceof DesktopNewThreadCreationAuthorityUnavailableErrorV2 &&
      error.reasonCode === 'desktop_renderer_service_resolve_failed' &&
      error.runtimeCode === 'missing_service',
  );
  const invalid = createDesktopNewThreadCreationOperationsV2(() =>
    acceptedActions(
      {
        bindOperation: () => ({ createTaskSession: async () => taskSession() }),
      },
      'x',
    ),
  ).bindOperation(runtimeConfig());
  await assert.rejects(
    invalid.createTaskSession(taskSessionRequest()),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_new_thread_creation_service_invalid',
  );

  let escaped;
  await withDesktopNewThreadCreationAuthorityOperationV2(
    acceptedActions(serviceFixture(), 'sha256:revocation'),
    {
      kind: 'create-agent-conversation',
      config: runtimeConfig(),
      title: 'Start a task',
      projectId: 'project-1',
      expectedUserId: 'user-1',
    },
    (authority) => {
      escaped = authority;
      return 'complete';
    },
  );
  assert.throws(
    () =>
      escaped.createAgentConversation('Start a task', 'project-1', 'user-1'),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_new_thread_creation_operation_released',
  );
});

test('operation failure outranks release failure and successful release failure propagates', async () => {
  let failOperation = true;
  const fixture = serviceFixture();
  const service = {
    bindOperation(config) {
      const authority = fixture.bindOperation(config);
      return {
        ...authority,
        runAgentMessage: async () => {
          if (failOperation) throw new Error('new_thread_operation_failed');
          return { queued: true };
        },
      };
    },
  };
  const actions = {
    acquireServiceOperationLease: async () => ({
      status: 'accepted',
      digest: 'sha256:release-failure',
      useService: (operation) => operation(service),
      release: async () => {
        throw new Error('new_thread_release_failed');
      },
    }),
  };
  const client = createDesktopNewThreadCreationOperationsV2(
    () => actions,
  ).bindOperation(runtimeConfig());

  await assert.rejects(
    client.runAgentMessage('conversation-1', 'Begin', 'message-1', 'project-1'),
    /new_thread_operation_failed/u,
  );
  failOperation = false;
  await assert.rejects(
    client.runAgentMessage('conversation-1', 'Begin', 'message-1', 'project-1'),
    /new_thread_release_failed/u,
  );
});

test('HMR pins the in-flight request and routes the next request to the new generation', async () => {
  const lifecycle = [];
  let resolveOld;
  const oldResponse = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const oldFixture = serviceFixture();
  const oldService = {
    bindOperation(config) {
      return {
        ...oldFixture.bindOperation(config),
        createAgentConversation: async () => oldResponse,
      };
    },
  };
  const newConversation = conversation({
    id: 'conversation-new',
    title: 'New generation',
  });
  let actions = acceptedActions(oldService, 'sha256:old', lifecycle);
  const client = createDesktopNewThreadCreationOperationsV2(
    () => actions,
  ).bindOperation(runtimeConfig());
  const oldPending = client.createAgentConversation(
    'Old generation',
    'project-1',
    'user-1',
  );
  actions = acceptedActions(
    serviceFixture([], { conversation: newConversation }),
    'sha256:new',
    lifecycle,
  );
  const next = await client.createAgentConversation(
    'New generation',
    'project-1',
    'user-1',
  );
  resolveOld(conversation({ id: 'conversation-old', title: 'Old generation' }));
  const old = await oldPending;

  assert.equal(next.id, 'conversation-new');
  assert.equal(old.id, 'conversation-old');
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
