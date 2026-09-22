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
    { id: 'act-1', type: 'act', toolName: 'read_file', tool_call_id: 'read' },
    { id: 'observe-1', type: 'observe', toolName: 'read_file', tool_call_id: 'read' },
    { id: 'act-2', type: 'act', toolName: 'run_tests', tool_call_id: 'test' },
    { id: 'observe-2', type: 'observe', toolName: 'run_tests', tool_call_id: 'test' },
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
      toolName: 'read_file', tool_call_id: 'read',
      tool_execution_id: 'execution-1',
    },
    { id: 'thought-1', type: 'thought', content: 'I should inspect the result.' },
    {
      id: 'observe-1',
      type: 'observe',
      toolName: 'read_file', tool_call_id: 'read',
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

test('knowledge audit preserves paired tool results without becoming completion evidence', () => {
  const call = { id: 'search-call', type: 'act', toolName: 'knowledge_search', tool_call_id: 'search' };
  const audit = { id: 'search-audit', type: 'knowledge_tool_audit', data: { status: 'returned' } };
  const result = { id: 'search-result', type: 'observe', toolName: 'knowledge_search', tool_call_id: 'search' };
  for (const isError of [false, true]) {
    const narrative = buildSessionNarrative([call, audit, { ...result, isError }]);
    assert.deepEqual(narrative.map((node) => node.kind), ['tool_group', 'item']);
    assert.deepEqual(narrative[0].items.map((item) => item.id), [call.id, result.id]);
    assert.equal(narrative[0].toolCount, 1);
    assert.equal(narrative[0].status, isError ? 'failed' : 'complete');
    assert.equal(narrative[1].item, audit);
  }
  const pending = buildSessionNarrative([call, audit]);
  assert.equal(pending[0].status, 'running');
  assert.equal(pending[1].item, audit);
});

test('knowledge audit does not pair tools across a conversation message boundary', () => {
  const narrative = buildSessionNarrative([
    { id: 'call', type: 'act', toolName: 'knowledge_source' },
    { id: 'audit', type: 'knowledge_tool_audit' },
    { id: 'message', type: 'user_message', role: 'user', content: 'Next request' },
    { id: 'result', type: 'observe', toolName: 'knowledge_source' },
  ]);
  assert.equal(narrative[0].status, 'running');
  assert.deepEqual(narrative[0].items.map((item) => item.id), ['call']);
  assert.equal(narrative[1].item.id, 'audit');
  assert.equal(narrative[2].item.id, 'message');
});

test('tool groups expose running and failed states from structural events', () => {
  const running = buildSessionNarrative([
    { id: 'act-1', type: 'act', toolName: 'run_tests', tool_call_id: 'test' },
  ]);
  assert.equal(running[0].status, 'running');

  const failed = buildSessionNarrative([
    { id: 'act-1', type: 'act', toolName: 'run_tests', tool_call_id: 'test' },
    { id: 'observe-1', type: 'observe', toolName: 'run_tests', tool_call_id: 'test', isError: true },
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
        toolName: 'run_tests', tool_call_id: 'test',
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

test('subagent lifecycle and control acknowledgments preserve the parent tool pair', () => {
  const events = [
    { id: 'mcp-call', type: 'act', toolName: 'native-audit', tool_call_id: 'audit' },
    { id: 'mcp-result', type: 'observe', toolName: 'native-audit', tool_call_id: 'audit' },
    { id: 'child-call', type: 'act', toolName: 'subagent', tool_call_id: 'child' },
    ...['subagent_routed', 'subagent_started', 'ack', 'subagent_session_update', 'subagent_completed'].map((type) => ({ id: type, type })),
    { id: 'child-result', type: 'observe', toolName: 'subagent', tool_call_id: 'child' },
  ];
  for (const isError of [false, true]) {
    const narrative = buildSessionNarrative(events.map((event) => event.id === 'child-result' ? { ...event, isError } : event));
    const groups = narrative.filter((node) => node.kind === 'tool_group');
    assert.equal(groups.length, 1);
    assert.equal(groups[0].toolCount, 2);
    assert.equal(groups[0].status, isError ? 'failed' : 'complete');
    assert.deepEqual(groups[0].items.map((item) => item.id), ['mcp-call', 'mcp-result', 'child-call', 'child-result']);
    assert.equal(narrative.filter((node) => node.kind === 'item').length, 5);
  }
});

test('terminal run boundaries do not complete an unmatched earlier tool call', () => {
  for (const type of ['complete', 'run_status', 'environment_selected', 'assistant_message']) {
    const narrative = buildSessionNarrative([
      { id: 'call', type: 'act', toolName: 'subagent' },
      { id: 'started', type: 'subagent_started' },
      { id: 'boundary', type },
      { id: 'result', type: 'observe', toolName: 'subagent' },
    ]);
    const groups = narrative.filter((node) => node.kind === 'tool_group');
    assert.equal(groups.length, 2);
    assert.equal(groups[0].status, 'running');
    assert.deepEqual(groups[0].items.map((item) => item.id), ['call']);
  }
});

test('exact execution pairing spans assistant text while retaining non-tool narrative positions', () => {
  const call = { id:'a', type:'act', execution_id:'exec-1', toolName:'todo' };
  const assistant = { id:'text',type:'assistant_message',role:'assistant',content:'Original text' };
  const plan = { id:'plan',type:'task_list_updated' };
  const result = { id:'o',type:'observe',execution_id:'exec-1',toolName:'todo' };
  const narrative=buildSessionNarrative([call,assistant,plan,result],'cid');
  assert.deepEqual(narrative.map(n=>n.kind==='item'?n.item.id:n.items.map(i=>i.id)),[['a','o'],'text','plan']);
  assert.equal(narrative[0].status,'complete');
});

test('cross-segment pairing refuses missing, conflicting or sibling identities and run boundaries', () => {
  const call={id:'a',type:'act',execution_id:'exec-1',toolName:'todo'};
  const assistant={id:'text',type:'assistant_message',role:'assistant'};
  const result={id:'o',type:'observe',execution_id:'exec-1',toolName:'todo'};
  const cases=[
    [call,assistant,{...result,execution_id:'other'}],
    [{...call,execution_id:undefined},assistant,{...result,execution_id:undefined}],
    [{...call,conversation_id:'other'},assistant,result],
    [call,assistant,{...result,conversation_id:'other'}],
    [{...call,subagent_id:'child-a'},assistant,{...result,subagent_id:'child-b'}],
    [{...call,round_id:'round-a'},assistant,{...result,round_id:'round-b'}],
    [{...call,run_id:'run-a'},assistant,{...result,run_id:'run-b'}],
    ...['user_message','complete','run_status','environment_selected'].map(type=>[call,assistant,{id:'boundary',type},result]),
  ];
  for(const items of cases){
    const groups=buildSessionNarrative(items,'cid').filter(n=>n.kind==='tool_group');
    assert.equal(groups.length,2,JSON.stringify(items));
    assert.equal(groups[0].status,'running');
  }
});
