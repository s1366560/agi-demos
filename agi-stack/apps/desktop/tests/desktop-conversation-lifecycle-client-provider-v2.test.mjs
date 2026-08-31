import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createDesktopConversationLifecycleClientProviderV2,
  DesktopConversationLifecycleClientProviderErrorV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/' +
    'desktopConversationLifecycleClientProviderV2.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const providerSource = readFileSync(
  new URL(
    '../src/features/workspace/desktopConversationLifecycleClientProviderV2.ts',
    import.meta.url,
  ),
  'utf8',
);

test('desktop conversation lifecycle client provider fails closed before publication', () => {
  const provider = createDesktopConversationLifecycleClientProviderV2();

  assert.throws(
    () => provider.resolve(),
    (error) => {
      assert.equal(
        error instanceof DesktopConversationLifecycleClientProviderErrorV2,
        true,
      );
      assert.equal(
        error.reasonCode,
        'desktop_conversation_lifecycle_client_unpublished',
      );
      assert.equal(
        error.message,
        'desktop_conversation_lifecycle_client_unpublished',
      );
      return true;
    },
  );
});

test('publications pin one frozen lifecycle client to each generation config', async () => {
  const provider = createDesktopConversationLifecycleClientProviderV2();
  const firstConfig = runtimeConfig('http://127.0.0.1:41001', 'tenant-1', 'project-1');
  const first = provider.publish({ config: firstConfig });
  firstConfig.apiBaseUrl = 'http://127.0.0.1:49999';
  const second = provider.publish({
    config: runtimeConfig('http://127.0.0.1:41002', 'tenant-2', 'project-2'),
  });
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    if (init?.method === 'DELETE') return new Response(null, { status: 204 });
    const secondGeneration = String(input).startsWith('http://127.0.0.1:41002');
    return json(
      conversationRecord({
        id: secondGeneration ? 'conversation-2' : 'conversation-1',
        tenantId: secondGeneration ? 'tenant-2' : 'tenant-1',
        projectId: secondGeneration ? 'project-2' : 'project-1',
        title: String(input).includes('/summary') ? 'Generated summary' : 'Renamed',
      }),
    );
  };

  try {
    const renamed = await first.client.updateAgentConversationTitle(
      'conversation-1',
      'Renamed',
      'project-1',
      'workspace-1',
    );
    const summarized = await second.client.generateAgentConversationSummary(
      'conversation-2',
      'project-2',
      'workspace-1',
    );
    await first.client.deleteAgentConversation('conversation-1', 'project-1');

    assert.equal(Object.isFrozen(first), true);
    assert.equal(Object.isFrozen(first.client), true);
    assert.equal(Object.isFrozen(second), true);
    assert.notEqual(first, second);
    assert.notEqual(first.client, second.client);
    assert.equal(provider.resolve(), second);
    assert.equal(renamed.title, 'Renamed');
    assert.equal(summarized.summary, 'Generated summary');
    assert.deepEqual(
      calls.map((call) => call.input),
      [
        'http://127.0.0.1:41001/api/v1/agent/conversations/conversation-1/title?project_id=project-1',
        'http://127.0.0.1:41002/api/v1/agent/conversations/conversation-2/summary?project_id=project-2',
        'http://127.0.0.1:41001/api/v1/agent/conversations/conversation-1?project_id=project-1',
      ],
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('failed lifecycle client publication keeps the last-good binding', () => {
  const provider = createDesktopConversationLifecycleClientProviderV2();
  const lastGood = provider.publish({ config: DEFAULT_CONFIG });
  const poisonedConfig = {
    ...DEFAULT_CONFIG,
    get apiBaseUrl() {
      throw new Error('candidate_conversation_lifecycle_config_invalid');
    },
  };

  assert.throws(
    () => provider.publish({ config: poisonedConfig }),
    /candidate_conversation_lifecycle_config_invalid/u,
  );
  assert.equal(provider.resolve(), lastGood);
});

test('App consumes the published V2 lifecycle client without constructing request clients', () => {
  assert.match(
    appSource,
    /desktopConversationLifecycleClientProviderV2\.publish\(\{ config \}\)/u,
  );
  assert.match(
    appSource,
    /desktopConversationLifecycleClientV2\.client\.updateAgentConversationTitle/u,
  );
  assert.match(
    appSource,
    /desktopConversationLifecycleClientV2\.client\.generateAgentConversationSummary/u,
  );
  assert.match(
    appSource,
    /desktopConversationLifecycleClientV2\.client\.deleteAgentConversation/u,
  );
  for (const handlerName of [
    'renameConversation',
    'regenerateConversationSummary',
    'deleteConversation',
  ]) {
    const handler = functionSource(appSource, handlerName);
    assert.doesNotMatch(handler, /new DesktopApiClient\(/u);
  }
  assert.match(providerSource, /new DesktopApiClient\(config\)/u);
});

function runtimeConfig(apiBaseUrl, tenantId, projectId) {
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl,
    localApiToken: 'local-session-token',
    tenantId,
    projectId,
    workspaceId: 'workspace-1',
    mode: 'local',
  };
}

function conversationRecord({ id, tenantId, projectId, title }) {
  return {
    id,
    tenant_id: tenantId,
    project_id: projectId,
    user_id: 'user-1',
    workspace_id: 'workspace-1',
    workspace_name: 'Workspace 1',
    title,
    summary: title,
    status: 'active',
    message_count: 0,
    agent_config: null,
    metadata: null,
    conversation_mode: 'single_agent',
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

function functionSource(source, name) {
  const start = source.indexOf(`const ${name} = async`);
  assert.notEqual(start, -1);
  const end = source.indexOf('\n  };', start);
  assert.notEqual(end, -1);
  return source.slice(start, end + 5);
}
