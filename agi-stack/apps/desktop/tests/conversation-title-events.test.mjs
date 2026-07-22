import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  applyConversationTitleUpdate,
  readConversationTitleStreamEvent,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/conversationTitleEventModel.js',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const qaSource = readFileSync(new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url), 'utf8');

function conversation(id, title) {
  return {
    id,
    project_id: 'project-1',
    tenant_id: 'tenant-1',
    user_id: 'user-1',
    title,
    status: 'active',
    message_count: 2,
    workspace_id: 'workspace-1',
    created_at: '2026-07-22T00:00:00Z',
  };
}

test('title_generated reads the authoritative nested server payload', () => {
  assert.deepEqual(
    readConversationTitleStreamEvent({
      type: 'title_generated',
      data: {
        conversation_id: 'conversation-1',
        title: '  Verify cloud session startup  ',
        generated_at: '2026-07-22T08:00:00Z',
      },
    }),
    {
      handled: true,
      update: {
        conversationId: 'conversation-1',
        title: 'Verify cloud session startup',
        generatedAt: '2026-07-22T08:00:00Z',
      },
    },
  );

  assert.deepEqual(readConversationTitleStreamEvent({ event_type: 'title_generated' }), {
    handled: true,
    update: null,
  });
  assert.deepEqual(readConversationTitleStreamEvent({ type: 'assistant_message' }), {
    handled: false,
    update: null,
  });
});

test('conversation title updates change only the exact active session and catalog entry', () => {
  const selected = conversation('conversation-1', 'New Conversation');
  const other = conversation('conversation-2', 'Keep this title');
  const update = {
    conversationId: 'conversation-1',
    title: 'Verify cloud session startup',
    generatedAt: '2026-07-22T08:00:00Z',
  };
  const result = applyConversationTitleUpdate(
    { scopeKey: 'project-1::workspace-1', conversation: selected },
    { 'workspace-1': [selected, other], 'workspace-2': [other] },
    update,
  );

  assert.equal(result.session?.conversation.title, 'Verify cloud session startup');
  assert.equal(result.conversationsByWorkspace['workspace-1'][0].title, update.title);
  assert.equal(result.conversationsByWorkspace['workspace-1'][1], other);
  assert.equal(result.conversationsByWorkspace['workspace-2'][0], other);

  const unchanged = applyConversationTitleUpdate(
    result.session,
    result.conversationsByWorkspace,
    update,
  );
  assert.equal(unchanged.session, result.session);
  assert.equal(unchanged.conversationsByWorkspace, result.conversationsByWorkspace);
});

test('Desktop consumes title events as metadata instead of raw timeline rows', () => {
  assert.match(appSource, /readConversationTitleStreamEvent\(event\)/);
  assert.match(appSource, /titleEvent\.handled[\s\S]*return existing/);
  assert.match(appSource, /applyConversationTitleUpdate\(/);
  assert.match(qaSource, /title-events/);
  assert.match(qaSource, /Verify cloud session startup/);
});
