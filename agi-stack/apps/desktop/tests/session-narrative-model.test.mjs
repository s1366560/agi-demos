import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildSessionNarrative,
  sessionActivityPresence,
  sessionActivitySummary,
  timelineGroupOpen,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionNarrativeModel.js');

test('consecutive tool calls are grouped without merging surrounding conversation turns', () => {
  const narrative = buildSessionNarrative([
    { id: 'user-1', type: 'user_message', role: 'user', content: 'Inspect the runner.' },
    { id: 'thought-1', type: 'thought', content: 'The fixture may be shared.' },
    { id: 'act-1', type: 'act', toolName: 'read_file' },
    { id: 'observe-1', type: 'observe', toolName: 'read_file' },
    { id: 'act-2', type: 'act', toolName: 'run_tests' },
    { id: 'observe-2', type: 'observe', toolName: 'run_tests' },
    { id: 'agent-1', type: 'assistant_message', role: 'assistant', content: 'Fixed.' },
  ]);

  assert.equal(narrative.length, 4);
  assert.equal(narrative[0].kind, 'item');
  assert.equal(narrative[1].kind, 'item');
  assert.equal(narrative[1].item.type, 'thought');
  assert.equal(narrative[2].kind, 'tool_group');
  assert.deepEqual(
    narrative[2].items.map((item) => item.type),
    ['act', 'observe', 'act', 'observe'],
  );
  assert.equal(narrative[2].toolCount, 2);
  assert.equal(narrative[2].status, 'complete');
  assert.equal(narrative[3].kind, 'item');
});

test('thought does not split a structurally matched act and observe pair', () => {
  const narrative = buildSessionNarrative([
    {
      id: 'act-1',
      type: 'act',
      toolName: 'read_file',
      tool_execution_id: 'execution-1',
    },
    { id: 'thought-1', type: 'thought', content: 'I should inspect the result.' },
    {
      id: 'observe-1',
      type: 'observe',
      toolName: 'read_file',
      tool_execution_id: 'execution-1',
    },
  ]);

  assert.deepEqual(
    narrative.map((node) => node.kind),
    ['tool_group', 'item'],
  );
  assert.deepEqual(
    narrative[0].items.map((item) => item.id),
    ['act-1', 'observe-1'],
  );
  assert.equal(narrative[0].toolCount, 1);
  assert.equal(narrative[0].status, 'complete');
  assert.equal(narrative[1].item.id, 'thought-1');
});

test('group disclosure keeps explicit user state ahead of changing defaults', () => {
  const items = [{ id: 'act-1' }, { id: 'observe-1' }];

  assert.equal(timelineGroupOpen(items, {}, true), true);
  assert.equal(timelineGroupOpen(items, {}, false), false);
  assert.equal(timelineGroupOpen(items, { 'act-1': false }, true), false);
  assert.equal(timelineGroupOpen(items, { 'act-1': true }, false), true);
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

test('a standalone thought remains narrative text when no tool event follows it', () => {
  const narrative = buildSessionNarrative([
    { id: 'thought-1', type: 'thought', content: 'I am preparing the answer.' },
    { id: 'agent-1', type: 'assistant_message', role: 'assistant', content: 'Ready.' },
  ]);

  assert.deepEqual(
    narrative.map((node) => node.kind),
    ['item', 'item'],
  );
});

test('activity summary uses the latest event and leaves missing evidence unavailable', () => {
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
  });

  assert.equal(summary.title, 'Targeted tests');
  assert.equal(summary.detail, '18 tests passed');
  assert.equal(summary.checkpoint, '');
  assert.equal(summary.checkpointKey, 'session.activityCheckpoint');
  assert.deepEqual(summary.evidence, { kind: 'unavailable' });
});

test('free-form display evidence is explicitly presented as agent reported', () => {
  const summary = sessionActivitySummary({
    items: [
      {
        id: 'verification-1',
        type: 'task_updated',
        display: {
          title: 'Verifying the isolated fix',
          summary: '18 tests passed · 50 race runs passed',
          checkpoint: 'Patch applied',
          evidence: '18 tests · 50 race runs',
        },
      },
    ],
  });

  assert.equal(summary.checkpoint, 'Patch applied');
  assert.equal(summary.checkpointKey, null);
  assert.deepEqual(summary.evidence, {
    kind: 'agent_reported',
    text: '18 tests · 50 race runs',
  });
});

test('validated projection evidence takes priority over agent-reported display copy', () => {
  const summary = sessionActivitySummary({
    items: [
      {
        id: 'verification-1',
        type: 'task_updated',
        display: { evidence: '18 tests · 50 race runs' },
      },
    ],
    structuredEvidence: {
      artifactCount: 2,
      checkCount: 18,
      toolActivityCount: 4,
    },
  });

  assert.deepEqual(summary.evidence, {
    kind: 'structured',
    artifactCount: 2,
    checkCount: 18,
    toolActivityCount: 4,
  });
});

test('activity is live only for an authoritative running run with connected updates', () => {
  assert.equal(sessionActivityPresence(null, true), 'recorded');
  assert.equal(sessionActivityPresence('completed', true), 'recorded');
  assert.equal(sessionActivityPresence('running', false), 'recorded');
  assert.equal(sessionActivityPresence('running', true), 'live');
});

test('protocol event and tool identifiers map to localized activity copy', () => {
  const summary = sessionActivitySummary({
    items: [
      { id: 'tool-1', type: 'observe', toolName: 'todowrite' },
      { id: 'memory-1', type: 'memory_captured' },
    ],
  });

  assert.equal(summary.title, '');
  assert.equal(summary.titleKey, 'session.activityMemoryCaptured');
  assert.equal(summary.checkpoint, '');
  assert.equal(summary.checkpointKey, 'session.activityPlan');
});

test('unknown protocol identifiers use localized fallbacks instead of leaking wire values', () => {
  const summary = sessionActivitySummary({
    items: [{ id: 'runtime-1', type: 'future_runtime_event', toolName: 'future_tool_call' }],
  });

  assert.equal(summary.title, '');
  assert.equal(summary.titleKey, 'session.activityUpdated');
  assert.equal(summary.checkpoint, '');
  assert.equal(summary.checkpointKey, 'session.activityCheckpoint');
});
