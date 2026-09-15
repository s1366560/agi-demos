import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/src/';
const { timelineItemsForDisplay } = require(root + 'features/chat/chatTimelineModel.js');
const { enqueuePendingAgentRunMessage } = require(root + 'hooks/useAgentSocket.js');
const { DesktopApiClient } = require(root + 'api/client.js');
const raw = 'Work in Plan mode. Analyze the objective without changing files. Objective: 用户目标';

test('explicit user display content wins in live and persisted timelines while raw content survives', () => {
  for (const extra of [{ display_content: '用户目标' }, { payload: { display_content: '用户目标' } }, { metadata: { display_content: '用户目标' } }]) {
    const item = { id: 'message', type: 'user_message', role: 'user', content: raw, ...extra };
    const result = timelineItemsForDisplay([item]);
    assert.equal(result[0].content, '用户目标');
    assert.equal(item.content, raw);
  }
  assert.equal(timelineItemsForDisplay([{ id: 'old', type: 'user_message', content: raw }])[0].content, raw);
  assert.equal(timelineItemsForDisplay([{ id: 'assistant', type: 'assistant_message', content: raw, payload: { display_content: 'hidden' } }])[0].content, raw);
});

test('socket queue preserves explicit display text separately from the raw model instruction', () => {
  const queue = new Map();
  assert.equal(enqueuePendingAgentRunMessage(queue, { conversationId: 'conversation', projectId: 'project', messageId: 'turn', message: raw, displayContent: '用户目标' }), true);
  assert.equal([...queue.values()][0].message, raw);
  assert.equal([...queue.values()][0].display_content, '用户目标');
});

test('Local HTTP run carries explicit display field without changing message', async () => {
  const original = globalThis.fetch;
  let body;
  globalThis.fetch = async (_, init) => { body = JSON.parse(init.body); return new Response(JSON.stringify({ queued: true }), { headers: { 'content-type': 'application/json' } }); };
  try {
    const client = new DesktopApiClient({ mode: 'local', apiBaseUrl: 'http://localhost:1', localApiToken: 'test-only', apiKey: '', projectId: 'project' });
    await client.runAgentMessage('conversation', raw, 'turn', 'project', undefined, { displayContent: '用户目标' });
    assert.equal(body.message, raw);
    assert.equal(body.display_content, '用户目标');
  } finally { globalThis.fetch = original; }
});

test('operation-bound HTTP arguments retain display content and reject invalid presentation values', () => {
  const { cloneAgentMessageArgumentsV2 } = require(root + 'plugins/desktopNewThreadCreationContractV2.js');
  const config = { mode: 'local', tenantId: 'tenant', projectId: 'project', workspaceId: '' };
  const args = cloneAgentMessageArgumentsV2(config, 'conversation', raw, 'turn', 'project', undefined, { displayContent: '用户目标' });
  assert.equal(args.message, raw);
  assert.equal(args.execution.displayContent, '用户目标');
  for (const invalid of [null, '', '  ', 42, '字'.repeat(21846)]) {
    assert.throws(() => cloneAgentMessageArgumentsV2(config, 'conversation', raw, 'turn', 'project', undefined, { displayContent: invalid }));
    assert.equal(enqueuePendingAgentRunMessage(new Map(), { conversationId: 'conversation', projectId: 'project', messageId: 'turn', message: raw, displayContent: invalid }), false);
  }
});
