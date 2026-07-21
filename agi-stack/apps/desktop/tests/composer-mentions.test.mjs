import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('workspace message API sends structured mention ids with composer context', async () => {
  const originalFetch = globalThis.fetch;
  let request = null;
  globalThis.fetch = async (input, init = {}) => {
    request = { url: String(input), init };
    return Response.json(
      {
        id: 'message-1',
        workspace_id: 'workspace-1',
        sender_id: 'user-1',
        sender_type: 'human',
        content: 'Delegate this',
        mentions: ['agent-research'],
        parent_message_id: null,
        metadata: {},
        created_at: '2026-07-21T12:00:00Z',
      },
      { status: 201 },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'https://api.memstack.test',
      apiKey: 'cloud-session',
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'workspace-1',
    });
    await client.sendMessage(
      'Delegate this',
      undefined,
      [
        {
          kind: 'agent',
          resource_id: 'agent-research',
          label: '@Research',
          metadata: { mention_target: true },
        },
      ],
      ['agent-research'],
    );

    assert.equal(
      new URL(request.url).pathname,
      '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/messages',
    );
    assert.deepEqual(JSON.parse(request.init.body), {
      content: 'Delegate this',
      sender_type: 'human',
      mentions: ['agent-research'],
      context_items: [
        {
          kind: 'agent',
          resource_id: 'agent-research',
          label: '@Research',
          metadata: { mention_target: true },
        },
      ],
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
