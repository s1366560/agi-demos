import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  groupSubAgentTimelineItems,
} = require('/tmp/agistack-desktop-test-dist/apps/desktop/src/features/chat/subagentTimelineGroupModel.js');
const item = (id, type, data = {}) => ({
  id,
  type,
  payload: {
    run_id: 'child-one',
    execution_id: 'child-one',
    subagent_id: 'reader',
    parent_run_id: 'parent',
    parent_run_revision: 4,
    ...data,
  },
});

test('child tools remain inside their lifecycle and do not complete it early', () => {
  const result = groupSubAgentTimelineItems([
    item('start', 'subagent_started'),
    item('call', 'subagent_tool_call', {
      round: 0,
      tool_name: 'plugin__exact',
      tool_input: '{"input":"marker"}',
      failed: false,
    }),
    item('result', 'subagent_tool_result', {
      round: 0,
      tool_name: 'plugin__exact',
      tool_output: '{"score":20260914}',
      failed: false,
    }),
  ]);
  assert.equal(result.groups.length, 1);
  assert.equal(result.groups[0].status, 'running');
  assert.deepEqual(result.claimedItemIds, ['start', 'call', 'result']);
  assert.equal(result.groups[0].toolActivity[0].output, '{"score":20260914}');
  assert.equal(result.groups[0].toolActivity[0].status, 'success');
});

test('interleaved sibling calls never attach to the same child', () => {
  const result = groupSubAgentTimelineItems([
    item('start', 'subagent_started'),
    item('call', 'subagent_tool_call', { round: 0, tool_name: 'read' }),
    item('sibling', 'subagent_tool_result', {
      execution_id: 'child-two',
      run_id: 'child-two',
      round: 0,
      tool_name: 'read',
      tool_output: 'other',
    }),
    item('end', 'subagent_completed', { success: true }),
  ]);
  assert.equal(result.groups[0].toolActivity.length, 1);
  assert.equal(result.groups[0].toolActivity[0].output, undefined);
  assert.equal(result.groups[0].status, 'success');
});

test('a child tool failure does not replace the child lifecycle verdict', () => {
  const result = groupSubAgentTimelineItems([
    item('start', 'subagent_started'),
    item('fail', 'subagent_tool_error', {
      round: 0,
      tool_name: 'read',
      failed: true,
      error: 'SubAgent tool execution failed',
    }),
    item('end', 'subagent_completed', { success: true }),
  ]);
  assert.equal(result.groups[0].status, 'success');
  assert.equal(result.groups[0].error, '');
  assert.equal(result.groups[0].toolActivity[0].status, 'error');
});
