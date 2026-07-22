import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { applyWorkspaceMessageStreamEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/workspaceMessageEventModel.js',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

const messageEvent = {
  type: 'workspace_message_created',
  data: {
    message: {
      id: 'message-live-1',
      workspace_id: 'workspace-1',
      sender_id: 'agent-release',
      sender_type: 'agent',
      content: 'Release verification completed.',
      mentions: ['user-reviewer'],
      created_at: '2026-07-22T09:00:00Z',
    },
  },
};

test('workspace message events append one scoped cloud chat message exactly once', () => {
  const appended = applyWorkspaceMessageStreamEvent([], messageEvent, 'workspace-1');
  assert.equal(appended.handled, true);
  assert.deepEqual(appended.messages, [messageEvent.data.message]);

  const replayed = applyWorkspaceMessageStreamEvent(
    appended.messages,
    messageEvent,
    'workspace-1',
  );
  assert.equal(replayed.handled, true);
  assert.equal(replayed.messages, appended.messages);
});

test('workspace message events reject cross-workspace and non-sensing payloads', () => {
  assert.equal(
    applyWorkspaceMessageStreamEvent([], messageEvent, 'workspace-2').handled,
    false,
  );
  assert.equal(
    applyWorkspaceMessageStreamEvent(
      [],
      {
        ...messageEvent,
        data: {
          ...messageEvent.data,
          surface_boundary: 'owned',
          signal_role: 'authoritative',
        },
      },
      'workspace-1',
    ).handled,
    false,
  );
});

test('workspace message events fail closed for malformed message records', () => {
  for (const message of [
    null,
    { id: '', workspace_id: 'workspace-1', content: 'missing id' },
    { id: 'message-2', workspace_id: 'workspace-1', content: 42 },
    { id: 'message-3', workspace_id: 'workspace-2', content: 'scope drift' },
  ]) {
    const result = applyWorkspaceMessageStreamEvent(
      [],
      { type: 'workspace_message_created', data: { message } },
      'workspace-1',
    );
    assert.equal(result.handled, false);
    assert.deepEqual(result.messages, []);
  }
});

test('Desktop applies new socket workspace messages to the active dataset', () => {
  assert.match(appSource, /applyWorkspaceMessageStreamEvent\(/);
  assert.match(appSource, /workspaceMessageEventsHeadRef/);
  assert.match(
    appSource,
    /socketEventsSince\(socket\.events, workspaceMessageEventsHeadRef\.current\)/,
  );
});
