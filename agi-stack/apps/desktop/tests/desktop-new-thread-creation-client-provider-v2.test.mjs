import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopNewThreadCreationClientProviderV2,
  DesktopNewThreadCreationClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/task/' +
    'desktopNewThreadCreationClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('desktop new-thread creation client provider fails closed before publication', () => {
  const provider = createDesktopNewThreadCreationClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(error instanceof DesktopNewThreadCreationClientProviderErrorV2, true);
      assert.equal(error.reasonCode, 'desktop_new_thread_creation_client_unpublished');
      assert.equal(error.message, 'desktop_new_thread_creation_client_unpublished');
      return true;
    },
  );
});

test('publications pin frozen base and operation clients to their exact configs', async () => {
  const provider = createDesktopNewThreadCreationClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:43001', 'tenant-1', 'project-1');
  const first = provider.publish({ config: firstConfig });
  const operationConfig = runtimeConfig(
    'http://127.0.0.1:43003',
    'tenant-3',
    'project-3',
    'workspace-3',
  );
  const operationClient = first.bindOperation(operationConfig);
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  operationConfig.apiBaseUrl = 'http://127.0.0.1:49998';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:43002', 'tenant-2', 'project-2'),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    calls.push({ url, init });
    if (url.endsWith('/api/v1/agent/conversations')) {
      return json(
        conversationRecord({
          id: 'conversation-1',
          tenantId: 'tenant-1',
          projectId: 'project-1',
          title: 'Pinned thread',
          workspaceId: null,
        }),
      );
    }
    if (url.endsWith('/task-sessions')) {
      return json(taskSessionRecord());
    }
    return json({ queued: true });
  };

  try {
    const conversation = await first.client.createAgentConversation(
      'Pinned thread',
      'project-1',
      'user-1',
    );
    const session = await operationClient.createTaskSession(taskSessionRequest());
    const turn = await operationClient.runAgentMessage(
      'conversation-3',
      'Start the plan',
      'message-3',
      'project-3',
    );

    assert.equal(Object.isFrozen(first), true);
    assert.equal(Object.isFrozen(first.client), true);
    assert.equal(Object.isFrozen(operationClient), true);
    assert.equal(Object.isFrozen(second), true);
    assert.notEqual(first, second);
    assert.notEqual(first.client, second.client);
    assert.equal(provider.resolve(), second);
    assert.equal(conversation.id, 'conversation-1');
    assert.equal(session.workspace.id, 'workspace-3');
    assert.deepEqual(turn, { queued: true });
    assert.deepEqual(
      calls.map(({ url }) => url),
      [
        'http://127.0.0.1:43001/api/v1/agent/conversations',
        'http://127.0.0.1:43003/api/v1/tenants/tenant-3/projects/project-3/task-sessions',
        'http://127.0.0.1:43003/api/v1/agent/conversations/conversation-3/messages',
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed new-thread creation publication keeps the last-good binding', () => {
  const provider = createDesktopNewThreadCreationClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_new_thread_creation_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_new_thread_creation_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

function runtimeConfig(apiBaseUrl, tenantId, projectId, workspaceId = '') {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    localApiToken: 'local-session-token',
    tenantId,
    projectId,
    workspaceId,
    mode: 'local',
  };
}

function taskSessionRequest() {
  return {
    idempotency_key: 'desktop-task-session-3',
    workspace: { kind: 'existing', workspace_id: 'workspace-3' },
    conversation: { title: 'Atomic task', capability_mode: 'work' },
    initial_message: { content: 'Create the reviewable plan' },
  };
}

function taskSessionRecord() {
  return {
    replayed: false,
    workspace: {
      id: 'workspace-3',
      tenant_id: 'tenant-3',
      project_id: 'project-3',
      name: 'Atomic task',
      is_archived: false,
    },
    conversation: {
      ...conversationRecord({
        id: 'conversation-3',
        tenantId: 'tenant-3',
        projectId: 'project-3',
        title: 'Atomic task',
        workspaceId: 'workspace-3',
      }),
      conversation_mode: 'workspace',
      current_mode: 'plan',
      agent_config: {
        selected_agent_id: 'builtin:all-access',
        capability_mode: 'work',
      },
    },
    initial_message: {
      id: 'message-3',
      workspace_id: 'workspace-3',
      sender_id: 'user-3',
      sender_type: 'human',
      content: 'Create the reviewable plan',
      mentions: [],
      parent_message_id: null,
      metadata: {
        source: 'task_session',
        conversation_id: 'conversation-3',
      },
      created_at: '2026-08-31T00:00:00Z',
    },
  };
}

function conversationRecord({ id, tenantId, projectId, title, workspaceId }) {
  return {
    id,
    tenant_id: tenantId,
    project_id: projectId,
    user_id: 'user-1',
    workspace_id: workspaceId,
    workspace_name: workspaceId ? 'Workspace' : null,
    title,
    summary: title,
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
    created_at: '2026-08-31T00:00:00Z',
    updated_at: null,
  };
}

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}
