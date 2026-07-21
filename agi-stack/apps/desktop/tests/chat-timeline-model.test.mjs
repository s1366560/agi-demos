import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  detectPayloadLanguage,
  formatToolCallDuration,
  pairToolCallItems,
  toolActivityRows,
  shouldShowAgentWorkingIndicator,
  timelineWorkingStartedAtUs,
  timelineDayKey,
  timelineDayLabel,
  toolCallDiffStat,
  toolCallPairDurationMs,
  toolCallPairStatus,
  toolCallPresentationKind,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/chatTimelineModel.js');

test('act items pair with the observe that answers them, preserving order', () => {
  const pairs = pairToolCallItems([
    { id: 'act-1', type: 'act', toolName: 'read_file', eventTimeUs: 1_000_000 },
    { id: 'observe-1', type: 'observe', toolName: 'read_file', eventTimeUs: 1_400_000 },
    { id: 'act-2', type: 'act', toolName: 'run_tests', eventTimeUs: 2_000_000 },
    { id: 'observe-2', type: 'observe', toolName: 'run_tests', eventTimeUs: 3_000_000 },
  ]);

  assert.equal(pairs.length, 2);
  assert.equal(pairs[0].call.id, 'act-1');
  assert.equal(pairs[0].result?.id, 'observe-1');
  assert.equal(pairs[1].call.id, 'act-2');
  assert.equal(pairs[1].result?.id, 'observe-2');
});

test('tool activity rows preserve structured thinking ahead of paired tool calls', () => {
  const rows = toolActivityRows([
    { id: 'thought-1', type: 'thought', content: 'Inspect the shared fixture.' },
    { id: 'act-1', type: 'act', toolName: 'read_file' },
    { id: 'observe-1', type: 'observe', toolName: 'read_file' },
  ]);

  assert.equal(rows.length, 2);
  assert.equal(rows[0].kind, 'thought');
  assert.equal(rows[0].item.id, 'thought-1');
  assert.equal(rows[1].kind, 'tool_call');
  assert.equal(rows[1].pair.call.id, 'act-1');
  assert.equal(rows[1].pair.result.id, 'observe-1');
});

test('a trailing act without its observe renders as a running call', () => {
  const pairs = pairToolCallItems([
    { id: 'act-1', type: 'act', toolName: 'read_file', eventTimeUs: 1 },
    { id: 'observe-1', type: 'observe', toolName: 'read_file', eventTimeUs: 2 },
    { id: 'act-2', type: 'act', toolName: 'write_file', eventTimeUs: 3 },
  ]);

  assert.equal(pairs.length, 2);
  assert.equal(toolCallPairStatus(pairs[0]), 'complete');
  assert.equal(toolCallPairStatus(pairs[1]), 'running');
  assert.equal(toolCallPairDurationMs(pairs[1]), null);
});

test('an orphaned observe still renders as a completed call on its own', () => {
  const pairs = pairToolCallItems([
    { id: 'observe-1', type: 'observe', toolName: 'read_file', eventTimeUs: 5 },
  ]);

  assert.equal(pairs.length, 1);
  assert.equal(pairs[0].result, null);
  assert.equal(toolCallPairStatus(pairs[0]), 'complete');
});

test('failed observations surface as failed pairs with a duration', () => {
  const failed = pairToolCallItems([
    { id: 'act-1', type: 'act', toolName: 'run_tests', eventTimeUs: 1_000_000 },
    { id: 'observe-1', type: 'observe', toolName: 'run_tests', isError: true, eventTimeUs: 2_000_000 },
  ]);
  const withDelta = pairToolCallItems([
    { id: 'act-1', type: 'act', toolName: 'run_tests', eventTimeUs: 1_000_000 },
    { id: 'observe-1', type: 'observe', toolName: 'run_tests', eventTimeUs: 2_500_000 },
  ]);

  assert.equal(toolCallPairStatus(failed[0]), 'failed');
  assert.equal(toolCallPairDurationMs(withDelta[0]), 1500);
});

test('tool call durations format for quick scanning', () => {
  assert.equal(formatToolCallDuration(420), '420ms');
  assert.equal(formatToolCallDuration(1800), '1.8s');
  assert.equal(formatToolCallDuration(12_000), '12s');
  assert.equal(formatToolCallDuration(72_000), '1m 12s');
  assert.equal(formatToolCallDuration(-5), '');
});

test('structured tool presentation metadata drives worklog anatomy', () => {
  const pair = pairToolCallItems([
    {
      id: 'act-edit',
      type: 'act',
      toolName: 'patch',
      display: { kind: 'edit' },
      eventTimeUs: 1_000_000,
    },
    {
      id: 'observe-edit',
      type: 'observe',
      toolName: 'patch',
      display: { kind: 'edit' },
      fileMetadata: { diffStat: { filesChanged: 2, additions: 18, deletions: 4 } },
      eventTimeUs: 1_500_000,
    },
  ])[0];

  assert.equal(toolCallPresentationKind(pair), 'edit');
  assert.deepEqual(toolCallDiffStat(pair), { filesChanged: 2, additions: 18, deletions: 4 });
});

test('unknown presentation metadata stays generic instead of text-classified', () => {
  const pair = pairToolCallItems([
    {
      id: 'act-unknown',
      type: 'act',
      toolName: 'custom_tool',
      toolInput: { description: 'edit and run a command' },
      eventTimeUs: 1,
    },
  ])[0];

  assert.equal(toolCallPresentationKind(pair), 'tool');
  assert.equal(toolCallDiffStat(pair), null);
});

test('working duration starts from the latest authoritative running boundary', () => {
  const items = [
    { id: 'user-1', type: 'user_message', role: 'user', eventTimeUs: 1_000_000 },
    { id: 'run-1', type: 'run_status', payload: { status: 'running' }, eventTimeUs: 2_000_000 },
    { id: 'tool-1', type: 'act', eventTimeUs: 3_000_000 },
  ];

  assert.equal(timelineWorkingStartedAtUs(items), 2_000_000);
  assert.equal(timelineWorkingStartedAtUs(items.slice(0, 1)), 1_000_000);
  assert.equal(timelineWorkingStartedAtUs([]), null);
});

test('day dividers bucket items by local calendar day', () => {
  const now = new Date(2026, 6, 20, 15, 0, 0).getTime();
  const todayUs = new Date(2026, 6, 20, 9, 0, 0).getTime() * 1000;
  const yesterdayUs = new Date(2026, 6, 19, 23, 0, 0).getTime() * 1000;
  const olderUs = new Date(2026, 6, 10, 12, 0, 0).getTime() * 1000;

  assert.equal(timelineDayKey(todayUs), timelineDayKey(now * 1000));
  assert.notEqual(timelineDayKey(yesterdayUs), timelineDayKey(todayUs));
  assert.deepEqual(timelineDayLabel(todayUs, now), { kind: 'today' });
  assert.deepEqual(timelineDayLabel(yesterdayUs, now), { kind: 'yesterday' });
  const older = timelineDayLabel(olderUs, now);
  assert.equal(older.kind, 'date');
  assert.ok(older.date.length > 0);
});

test('working indicator only shows while live, blocked neither by stream nor HITL', () => {
  const userTail = [{ id: 'u1', type: 'user_message', role: 'user', eventTimeUs: 1 }];
  const streamingTail = [
    {
      id: 'a1',
      type: 'assistant_message',
      role: 'assistant',
      metadata: { streaming: true },
      eventTimeUs: 2,
    },
  ];
  const answerTail = [{ id: 'a2', type: 'assistant_message', role: 'assistant', eventTimeUs: 3 }];
  const observeTail = [{ id: 'o1', type: 'observe', toolName: 'read_file', eventTimeUs: 4 }];

  assert.equal(
    shouldShowAgentWorkingIndicator({ items: userTail, presence: 'live', awaitingHitl: false }),
    true,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: observeTail, presence: 'live', awaitingHitl: false }),
    true,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: streamingTail, presence: 'live', awaitingHitl: false }),
    false,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: answerTail, presence: 'live', awaitingHitl: false }),
    false,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: userTail, presence: 'recorded', awaitingHitl: false }),
    false,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: userTail, presence: 'live', awaitingHitl: true }),
    false,
  );
  assert.equal(
    shouldShowAgentWorkingIndicator({ items: [], presence: 'live', awaitingHitl: false }),
    false,
  );
});

test('payload detection pretty-prints JSON and keeps plain text untouched', () => {
  assert.deepEqual(detectPayloadLanguage('hello world'), {
    code: 'hello world',
    language: 'text',
  });
  assert.deepEqual(detectPayloadLanguage('{"a":1}'), { code: '{\n  "a": 1\n}', language: 'json' });
  assert.deepEqual(detectPayloadLanguage({ a: 1 }), { code: '{\n  "a": 1\n}', language: 'json' });
  assert.deepEqual(detectPayloadLanguage('{not json'), { code: '{not json', language: 'text' });
  assert.deepEqual(detectPayloadLanguage('$ cargo test\nok'), {
    code: '$ cargo test\nok',
    language: 'text',
  });
});
