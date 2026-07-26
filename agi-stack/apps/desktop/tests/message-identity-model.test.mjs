import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  formatWorkspaceMessageTime,
  workspaceMessageSenderLabel,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/messageIdentityModel.js',
);

const labels = {
  agent: 'Agent',
  system: 'System',
  you: 'You',
};

test('workspace sender labels use structured names without exposing unknown sender types', () => {
  assert.equal(
    workspaceMessageSenderLabel(
      {
        id: 'human',
        sender_type: 'human',
        sender_id: 'internal-user-id',
        content: 'hello',
        metadata: { sender_name: '  Alice  ' },
      },
      labels,
    ),
    'Alice',
  );
  assert.equal(
    workspaceMessageSenderLabel(
      {
        id: 'agent',
        sender_type: 'agent',
        sender_id: 'internal-agent-id',
        content: 'hello',
        metadata: { sender_name: 'Builder' },
      },
      labels,
    ),
    'Builder',
  );
  assert.equal(
    workspaceMessageSenderLabel(
      {
        id: 'unknown',
        sender_type: 'internal_dispatch_worker',
        sender_id: 'secret-runtime-id',
        content: 'hello',
      },
      labels,
    ),
    'Agent',
  );
  assert.equal(
    workspaceMessageSenderLabel(
      {
        id: 'system',
        sender_type: 'runtime',
        content: 'hello',
      },
      labels,
    ),
    'System',
  );
});

test('workspace message times omit malformed values and format valid timestamps', () => {
  assert.equal(formatWorkspaceMessageTime(undefined), '');
  assert.equal(formatWorkspaceMessageTime('not-a-date'), '');
  assert.match(formatWorkspaceMessageTime('2026-07-26T09:05:00.000Z'), /\d/);
});
