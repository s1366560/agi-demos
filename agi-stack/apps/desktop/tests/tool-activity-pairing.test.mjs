import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { mergeToolStreamItem, toolActivityRows, toolActivityPairIndex } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/chatTimelineModel.js',
);

const tool = (id, type, callId, extra = {}) => ({
  id, type, toolName: 'read_file', tool_call_id: callId,
  eventTimeUs: Number(id.replaceAll(/\D/g, '')) || 1, eventCounter: 0,
  ...extra,
});

test('thoughts do not split an explicitly linked call from its result', () => {
  const call = tool('act-1', 'act', 'call-1');
  const thought = { id: 'thought', type: 'thought', content: 'Continue waiting.' };
  const result = tool('observe-3', 'observe', 'call-1');
  const rows = toolActivityRows([call, thought, result]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].pair.call, call);
  assert.equal(rows[0].pair.result, result);
  assert.equal(rows[1].item, thought);
});

test('group-local rows pair against the full timeline and claim results only once', () => {
  const call = tool('act-1', 'act', 'call-1');
  const result = tool('observe-3', 'observe', 'call-1');
  const all = [call, { id: 'permission', type: 'permission_requested' }, result];
  assert.equal(toolActivityRows([call], toolActivityPairIndex(all))[0].pair.result, result);
  assert.deepEqual(toolActivityRows([result], toolActivityPairIndex(all)), []);
  const orphan = tool('observe-4', 'observe', 'missing-call');
  assert.equal(toolActivityRows([orphan], toolActivityPairIndex([...all, orphan]))[0].pair.call, orphan);
});

test('live calls with distinct top-level tool_call_id values never overwrite each other', () => {
  let items = mergeToolStreamItem([], tool('act-1', 'act', 'call-1'), 'delta');
  items = mergeToolStreamItem(items, tool('act-2', 'act', 'call-2'), 'delta');
  assert.equal(items.length, 2);
  assert.deepEqual(items.map((item) => item.tool_call_id), ['call-1', 'call-2']);
});

test('a foreign-run observation cannot settle a call even with a reused call id', () => {
  let items = mergeToolStreamItem([], tool('act-1', 'act', 'call-1', {
    payload: { run_id: 'run-a', call_id: 'call-1' },
  }), 'act');
  items = mergeToolStreamItem(items, tool('observe-2', 'observe', 'call-1', {
    payload: { run_id: 'run-b', call_id: 'call-1' },
  }), 'observe');
  assert.equal(items[0].metadata.streaming, true);
  assert.equal(toolActivityRows(items).length, 2);
});

test('global pairing preserves user and lifecycle boundaries before filtering tool rows', () => {
  for (const boundary of [
    { type: 'user_message', role: 'user' },
    { type: 'complete' },
    { type: 'run_status', payload: { status: 'completed' } },
    { type: 'environment_selected' },
    { type: 'agent_conversation_finished' },
    { type: 'conversation_finished' },
  ]) {
    const call = tool('act-1', 'act', 'reused');
    const result = tool('observe-3', 'observe', 'reused');
    const index = toolActivityPairIndex([call, { id: 'boundary', ...boundary }, result]);
    assert.equal(index.get(call.id).result, null, boundary.type);
    assert.equal(index.get(result.id).call, result, boundary.type);
  }
});

test('reused call ids in separate turns pair within each turn instead of becoming ambiguous', () => {
  const first = [tool('act-1', 'act', 'reused'), tool('observe-2', 'observe', 'reused')];
  const second = [tool('act-4', 'act', 'reused'), tool('observe-5', 'observe', 'reused')];
  const index = toolActivityPairIndex([
    ...first, { id: 'new-turn', type: 'user_message', role: 'user' }, ...second,
  ]);
  assert.equal(index.size, 2);
  assert.equal(index.get(first[0].id).result, first[1]);
  assert.equal(index.get(second[0].id).result, second[1]);
});

test('same-turn reasoning, permission, and assistant prose do not block exact tool pairing', () => {
  const call = tool('act-1', 'act', 'call-1');
  const result = tool('observe-5', 'observe', 'call-1');
  const index = toolActivityPairIndex([
    call, { id: 'thought', type: 'thought' },
    { id: 'permission', type: 'permission_requested' },
    { id: 'assistant', type: 'assistant_message', role: 'assistant' }, result,
  ]);
  assert.equal(index.get(call.id).result, result);
  assert.equal(index.has(result.id), false);
});
