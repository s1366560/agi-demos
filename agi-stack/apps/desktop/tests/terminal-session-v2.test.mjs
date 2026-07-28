import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  parseTerminalSessionV2,
  terminalReconnectDecision,
  terminalSessionV2SocketUrl,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/sandbox/terminalSessionV2.js'
);

const session = {
  contract_version: 2,
  session_id: 'terminal-session-1',
  resume_token: 'resume-token-1',
  project_id: 'project/1',
  conversation_id: 'conversation-1',
  run_id: 'run-1',
  run_revision: 7,
  environment_id: 'environment-1',
  cwd: '/workspace/project',
  created_at: '2026-07-28T02:00:00.000Z',
  expires_at: '2026-07-28T02:05:00.000Z',
  resumable: true,
};

test('TerminalSessionV2 requires the complete scoped resumable authority', () => {
  assert.deepEqual(
    parseTerminalSessionV2(session, Date.parse('2026-07-28T02:01:00.000Z')),
    session
  );
  for (const invalid of [
    { ...session, contract_version: 1 },
    { ...session, resume_token: '' },
    { ...session, run_revision: 0 },
    { ...session, resumable: false },
    { ...session, expires_at: 'invalid' },
    { ...session, extra: 'not part of the contract' },
  ]) {
    assert.equal(
      parseTerminalSessionV2(invalid, Date.parse('2026-07-28T02:01:00.000Z')),
      null
    );
  }
  assert.equal(
    parseTerminalSessionV2(session, Date.parse('2026-07-28T02:06:00.000Z')),
    null
  );
});

test('TerminalSessionV2 socket URL carries only scoped session resume authority', () => {
  assert.equal(
    terminalSessionV2SocketUrl('https://api.memstack.test', session),
    'wss://api.memstack.test/api/v1/projects/project%2F1/sandbox/terminal/proxy/ws?session_id=terminal-session-1&resume_token=resume-token-1'
  );
});

test('terminal reconnect is bounded and never recreates a lost server session', () => {
  const now = Date.parse('2026-07-28T02:01:00.000Z');
  assert.deepEqual(terminalReconnectDecision(session, { kind: 'abnormal_close' }, 0, now), {
    action: 'resume',
    delay_ms: 1000,
  });
  assert.deepEqual(terminalReconnectDecision(session, { kind: 'abnormal_close' }, 2, now), {
    action: 'resume',
    delay_ms: 4000,
  });
  assert.deepEqual(terminalReconnectDecision(session, { kind: 'session_lost' }, 0, now), {
    action: 'refetch_run',
    reason_code: 'terminal_session_lost',
  });
  assert.deepEqual(terminalReconnectDecision(session, { kind: 'authority_revoked' }, 0, now), {
    action: 'refetch_run',
    reason_code: 'terminal_authority_revoked',
  });
  assert.deepEqual(terminalReconnectDecision(session, { kind: 'normal_close' }, 0, now), {
    action: 'stop',
    reason_code: 'terminal_closed',
  });
  assert.deepEqual(terminalReconnectDecision(session, { kind: 'abnormal_close' }, 5, now), {
    action: 'stop',
    reason_code: 'terminal_reconnect_exhausted',
  });
});
