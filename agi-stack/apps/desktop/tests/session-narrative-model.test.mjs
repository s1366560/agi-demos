import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { buildSessionNarrative, sessionActivitySummary } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionNarrativeModel.js'
);

test('consecutive tool calls are grouped without merging surrounding conversation turns', () => {
  const narrative = buildSessionNarrative([
    { id: 'user-1', type: 'user_message', role: 'user', content: 'Inspect the runner.' },
    { id: 'act-1', type: 'act', toolName: 'read_file' },
    { id: 'observe-1', type: 'observe', toolName: 'read_file' },
    { id: 'act-2', type: 'act', toolName: 'run_tests' },
    { id: 'observe-2', type: 'observe', toolName: 'run_tests' },
    { id: 'agent-1', type: 'assistant_message', role: 'assistant', content: 'Fixed.' },
  ]);

  assert.equal(narrative.length, 3);
  assert.equal(narrative[0].kind, 'item');
  assert.equal(narrative[1].kind, 'tool_group');
  assert.equal(narrative[1].items.length, 4);
  assert.equal(narrative[1].toolCount, 2);
  assert.equal(narrative[1].status, 'complete');
  assert.equal(narrative[2].kind, 'item');
});

test('tool groups expose running and failed states from structural events', () => {
  const running = buildSessionNarrative([
    { id: 'act-1', type: 'act', toolName: 'run_tests' },
  ]);
  assert.equal(running[0].status, 'running');

  const failed = buildSessionNarrative([
    { id: 'act-1', type: 'act', toolName: 'run_tests' },
    { id: 'observe-1', type: 'observe', toolName: 'run_tests', isError: true },
  ]);
  assert.equal(failed[0].status, 'failed');
});

test('activity summary uses the latest authoritative event and evidence counts', () => {
  const summary = sessionActivitySummary({
    items: [
      { id: 'user-1', type: 'user_message', role: 'user', content: 'Do the work.' },
      { id: 'plan-1', type: 'work_plan', content: 'Implement the isolated fix.' },
      {
        id: 'tool-1',
        type: 'observe',
        toolName: 'run_tests',
        display: { title: 'Targeted tests', summary: '18 tests passed' },
      },
    ],
    artifactCount: 2,
    taskCount: 4,
  });

  assert.equal(summary.title, 'Targeted tests');
  assert.equal(summary.detail, '18 tests passed');
  assert.equal(summary.checkpoint, '');
  assert.equal(summary.checkpointKey, 'session.activityCheckpoint');
  assert.equal(summary.evidence, '2 artifacts · 4 tasks');
});

test('protocol event and tool identifiers map to localized activity copy', () => {
  const summary = sessionActivitySummary({
    items: [
      { id: 'tool-1', type: 'observe', toolName: 'todowrite' },
      { id: 'memory-1', type: 'memory_captured' },
    ],
    artifactCount: 0,
    taskCount: 1,
  });

  assert.equal(summary.title, '');
  assert.equal(summary.titleKey, 'session.activityMemoryCaptured');
  assert.equal(summary.checkpoint, '');
  assert.equal(summary.checkpointKey, 'session.activityPlan');
});

test('unknown protocol identifiers use localized fallbacks instead of leaking wire values', () => {
  const summary = sessionActivitySummary({
    items: [{ id: 'runtime-1', type: 'future_runtime_event', toolName: 'future_tool_call' }],
    artifactCount: 0,
    taskCount: 0,
  });

  assert.equal(summary.title, '');
  assert.equal(summary.titleKey, 'session.activityUpdated');
  assert.equal(summary.checkpoint, '');
  assert.equal(summary.checkpointKey, 'session.activityCheckpoint');
});
