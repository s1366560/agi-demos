import assert from 'node:assert/strict';
import test from 'node:test';

import {
  terminalBindingState,
  terminalOutputText,
  terminalRunScopeKey,
  terminalSessionMatchesRun,
} from '/tmp/agistack-desktop-test-dist/src/features/session/sessionTerminalModel.js';

const run = {
  id: 'run-1',
  revision: 7,
  project_id: 'project-1',
  conversation_id: 'conversation-1',
  environment: { id: 'environment-1' },
};
const terminal = {
  success: true,
  session_id: 'terminal-1',
  project_id: 'project-1',
  conversation_id: 'conversation-1',
  run_id: 'run-1',
  run_revision: 7,
  environment_id: 'environment-1',
};

test('terminal attachment requires an exact authoritative scope match', () => {
  assert.equal(terminalSessionMatchesRun(terminal, run), true);
  assert.equal(terminalSessionMatchesRun({ ...terminal, run_revision: 8 }, run), false);
  assert.equal(terminalSessionMatchesRun({ ...terminal, conversation_id: 'other' }, run), false);
  assert.equal(terminalSessionMatchesRun({ ...terminal, project_id: 'other' }, run), false);
  assert.equal(terminalSessionMatchesRun({ ...terminal, environment_id: 'other' }, run), false);
  assert.equal(terminalSessionMatchesRun({ ...terminal, run_id: 'other' }, run), false);
});

test('terminal binding becomes stale before any connection status can be shown as current', () => {
  assert.equal(terminalBindingState(terminal, run, 'connected'), 'connected');
  assert.equal(
    terminalBindingState(terminal, { ...run, revision: 8 }, 'connected'),
    'stale',
  );
  assert.equal(terminalBindingState(null, run, 'closed'), 'idle');
  assert.equal(
    terminalRunScopeKey(run),
    'project-1:conversation-1:run-1:7:environment-1',
  );
});

test('terminal output preserves the original chunk boundaries in every canvas', () => {
  const chunks = ['first line\r\n', 'second', ' line\r\n'];
  assert.equal(terminalOutputText(chunks), 'first line\r\nsecond line\r\n');
  assert.equal(terminalOutputText(chunks, 2), 'second line\r\n');
});
