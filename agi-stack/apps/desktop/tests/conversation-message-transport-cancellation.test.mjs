import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const { DesktopApiClient } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const config = {
  apiBaseUrl: 'http://127.0.0.1:8787', deviceAuthorizationBaseUrl: '',
  apiKey: 'test-session', localApiToken: 'test-launch', mode: 'local',
  tenantId: 'tenant-1', projectId: 'project-1', workspaceId: 'workspace-1', workspaceRoot: '',
};
const calls = [
  ['create', (client, signal) => client.createAgentConversation('title', 'project-1', 'user-1', undefined, undefined, signal), 'POST', '/api/v1/agent/conversations'],
  ['bind', (client, signal) => client.updateAgentConversationMode('conversation-1', { workspace_id: 'workspace-1' }, 'project-1', signal), 'PATCH', '/api/v1/agent/conversations/conversation-1/mode'],
  ['run', (client, signal) => client.runAgentMessage('conversation-1', 'message', 'message-1', 'project-1', undefined, undefined, signal), 'POST', '/api/v1/agent/conversations/conversation-1/messages'],
  ['workspace', (client, signal) => client.sendMessage('message', undefined, [], [], signal), 'POST', '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/messages'],
];
for (const [name, invoke, method, path] of calls) {
  test(`${name} HTTP operation forwards cancellation with existing authenticated wire`, async () => {
    const controller = new AbortController();
    const sentinel = new Error('transport-sentinel');
    let count = 0;
    globalThis.fetch = async (url, init) => {
      count++;
      assert.equal(init.signal, controller.signal);
      assert.equal(init.method, method);
      assert.equal(new URL(url).pathname, path);
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer test-session');
      assert.equal(new Headers(init.headers).get('X-Agistack-Launch'), 'test-launch');
      throw sentinel;
    };
    await assert.rejects(invoke(new DesktopApiClient(config), controller.signal), (error) => error === sentinel);
    assert.equal(count, 1);
  });
  test(`${name} already-cancelled operation never reaches HTTP`, async () => {
    const controller = new AbortController();
    controller.abort();
    let count = 0;
    globalThis.fetch = async () => { count++; throw new Error('unexpected HTTP'); };
    await assert.rejects(invoke(new DesktopApiClient(config), controller.signal), { name: 'AbortError' });
    assert.equal(count, 0);
  });
}
