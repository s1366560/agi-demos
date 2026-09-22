import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  stdin: {
    contents: `export * from './src/features/chat/chatTimelinePresentation';
      export * from './src/features/chat/chatTimelineModel';
      export * from './src/features/session/sessionNarrativeModel';
      export * from './src/features/chat/timelineExecutionIdentity';`,
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'ts',
  },
  write: false,
  bundle: true,
  platform: 'node',
  format: 'cjs',
  packages: 'external',
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(
  require,
  module,
  module.exports,
);
const {
  timelineSummary,
  isImportantTimelineItem,
  pairToolCallItems,
  buildSessionNarrative,
  sessionToolGroupStatus,
  timelineExecutionScope,
} = module.exports;
const t = (key) => key;
const call = (id, execution, extra = {}) => ({
  id,
  type: 'act',
  toolName: 'same-tool',
  execution_id: execution,
  ...extra,
});
const result = (id, execution, extra = {}) => ({
  id,
  type: 'observe',
  toolName: 'same-tool',
  execution_id: execution,
  ...extra,
});

test('tool and unknown runtime summaries never serialize raw data into the reading flow', () => {
  for (const payload of [{ internal: 'opaque-json' }, '{"internal":"opaque-json"}']) {
    assert.equal(timelineSummary({ ...result('r'), toolOutput: payload }, 'tool', t), 'same-tool');
    assert.equal(
      timelineSummary({ id: 'runtime', type: 'future_event', payload }, 'runtime', t),
      'chat.event',
    );
  }
  assert.equal(
    timelineSummary({ ...result('r'), display: { summary: 'Read 3 files' } }, 'tool', t),
    'Read 3 files',
  );
});

test('explicit errors remain important and readable even without legacy error flags', () => {
  const cases = [
    [{ type: 'error', payload: { error_code: 'runtime_conflict' } }, 'chat.error.runtimeConflict'],
    [
      { type: 'error', payload: { error_code: 'model_response_invalid' } },
      'chat.error.modelResponseInvalid',
    ],
    [{ type: 'error', content: '{"debug":"raw"}' }, 'chat.error.executionFailed'],
    [{ type: 'future_event', isError: true }, 'chat.error.executionFailed'],
    [
      { type: 'subagent_failed', payload: { error: 'internal trace' } },
      'chat.error.executionFailed',
    ],
  ];
  for (const [item, expected] of cases) {
    assert.equal(isImportantTimelineItem(item), true);
    assert.equal(timelineSummary(item, 'runtime', t), expected);
  }
});

test('parallel same-name calls pair only exact IDs and tolerate out-of-order results', () => {
  const pairs = pairToolCallItems([
    result('r-b', 'b'),
    call('a', 'a'),
    call('b', 'b'),
    result('r-a', 'a'),
  ]);
  assert.deepEqual(
    pairs.map(({ call, result }) => [call.id, result?.id]),
    [
      ['a', 'r-a'],
      ['b', 'r-b'],
    ],
  );
  assert.equal(pairToolCallItems([call('a'), result('r')]).length, 2);
});

test('ambiguous duplicate, sibling, conflicting alias and run IDs never claim a result', () => {
  const cases = [
    [call('a', 'same'), call('b', 'same'), result('r', 'same')],
    [
      call('a', 'same', { subagent_id: 'child-a' }),
      result('r', 'same', { subagent_id: 'child-b' }),
    ],
    [call('a', 'same', { run_id: 'run-a' }), result('r', 'same', { run_id: 'run-b' })],
    [call('a', 'same', { payload: { execution_id: 'conflict' } }), result('r', 'same')],
    [call('a', 'same'), result('r1', 'same'), result('r2', 'same')],
  ];
  for (const items of cases)
    assert.ok(pairToolCallItems(items).every((pair) => pair.result === null));
});

test('late results join exact calls without moving assistant narrative or crossing user turns', () => {
  const assistant = {
    id: 'text',
    type: 'assistant_message',
    role: 'assistant',
    content: 'Progress',
  };
  const nodes = buildSessionNarrative(
    [call('a', 'exec'), assistant, result('r', 'exec')],
    'conversation',
  );
  assert.deepEqual(
    nodes.map((node) => (node.kind === 'item' ? node.id : node.items.map((item) => item.id))),
    [['a', 'r'], 'text'],
  );
  const boundary = { id: 'user', type: 'user_message', role: 'user' };
  const separated = buildSessionNarrative([call('a', 'exec'), boundary, result('r', 'exec')]);
  assert.equal(separated[0].status, 'running');
  assert.deepEqual(
    separated[0].items.map((item) => item.id),
    ['a'],
  );
});

test('group status does not infer success from equal counts or a completed run with missing results', () => {
  assert.equal(sessionToolGroupStatus([call('a'), result('r')]), 'running');
  assert.equal(sessionToolGroupStatus([call('a', 'a'), result('r', 'a')]), 'complete');
  assert.equal(
    sessionToolGroupStatus([
      call('a', 'a'),
      { type: 'run_status', payload: { status: 'completed' } },
    ]),
    'running',
  );
  assert.equal(
    sessionToolGroupStatus([
      call('a', 'a'),
      result('r', 'a'),
      { type: 'run_status', status: 'running' },
    ]),
    'running',
  );
  assert.equal(
    sessionToolGroupStatus([call('a', 'a'), { type: 'run_status', status: 'cancelled' }]),
    'stopped',
  );
  assert.equal(timelineExecutionScope(call('a', 'a')), null);
  assert.notEqual(
    timelineExecutionScope(call('a', 'a', { run_id: 'run-a' })),
    timelineExecutionScope(call('a', 'a', { run_id: 'run-b' })),
  );
});

test('same-run internal events stay in the tool group without absorbing prose, errors or other runs', () => {
  const a = call('a', 'a', { run_id: 'run' });
  const diagnostic = { id: 'audit', type: 'knowledge_tool_audit', run_id: 'run' };
  const b = call('b', 'b', { run_id: 'run' });
  const items = [
    a,
    result('ra', 'a', { run_id: 'run' }),
    diagnostic,
    b,
    result('rb', 'b', { run_id: 'run' }),
  ];
  const grouped = buildSessionNarrative(items);
  assert.equal(grouped.length, 1);
  assert.equal(grouped[0].toolCount, 2);
  assert.ok(grouped[0].items.includes(diagnostic));
  for (const separator of [
    { ...diagnostic, run_id: 'other-run' },
    { ...diagnostic, isError: true },
    { ...diagnostic, type: 'thought' },
    { ...diagnostic, type: 'work_plan' },
    { ...diagnostic, type: 'future_unknown' },
  ]) {
    const nodes = buildSessionNarrative([a, separator, b]);
    assert.equal(nodes.length, 3);
    assert.equal(nodes[1].kind, 'item');
  }
});

test('actual tool row preview preserves call metadata when the result has only raw output', async () => {
  const ts = require('typescript');
  const source = ts.createSourceFile(
    'ChatTimeline.tsx',
    readFileSync(new URL('../src/features/chat/ChatTimeline.tsx', import.meta.url), 'utf8'),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const declaration = source.statements.find(
    (node) => ts.isFunctionDeclaration(node) && node.name?.text === 'toolCallPairPreviewText',
  );
  assert.ok(declaration);
  const output = await esbuild.build({
    stdin: {
      contents: `import {timelineToolDisplay, timelineSummary, timelineFileMetadata} from './src/features/chat/chatTimelinePresentation';
        import {toolCallPresentationKind, toolCallPairStatus} from './src/features/chat/chatTimelineModel';
        import {todoToolCallSummary, formatTodoToolCallSummary} from './src/features/chat/todoChecklistModel';
        export ${declaration.getText(source)}`,
      resolveDir: new URL('..', import.meta.url).pathname,
      loader: 'ts',
    },
    write: false,
    bundle: true,
    platform: 'node',
    format: 'cjs',
    packages: 'external',
  });
  const rowModule = { exports: {} };
  new Function('require', 'module', 'exports', output.outputFiles[0].text)(
    require,
    rowModule,
    rowModule.exports,
  );
  const preview = rowModule.exports.toolCallPairPreviewText;
  const pair = {
    call: call('a', 'a', {
      display: { kind: 'read', title: 'Read file', summary: 'Inspect entry point' },
    }),
    result: result('r', 'a', { toolOutput: '{"internal":"raw"}' }),
  };
  assert.deepEqual(preview(pair, t), { preview: 'Inspect entry point', label: 'Read file' });
  assert.equal(
    preview({ ...pair, result: { ...pair.result, display: { summary: 'Read 20 lines' } } }, t)
      .preview,
    'Read 20 lines',
  );
  assert.equal(
    preview({ ...pair, result: { ...pair.result, isError: true } }, t).preview,
    'chat.error.executionFailed',
  );
  assert.equal(
    preview({ call: call('a', 'a', { display: { kind: 'read' } }), result: pair.result }, t)
      .preview,
    'session.toolKind.read',
  );
});


test('conflicting call IDs defeat matching execution IDs; redelivery retains latest same-ID event', () => {
  const conflicting = pairToolCallItems([
    call('a', 'exec', {call_id: 'left'}), result('r', 'exec', {call_id: 'right'}),
  ]);
  assert.equal(conflicting.length, 2);
  assert.ok(conflicting.every((pair) => pair.result === null));
  const original = result('r', 'exec', {display: {summary: 'Original'}});
  const latest = {...original, display: {summary: 'Latest'}};
  const pairs = pairToolCallItems([call('a', 'exec'), original, call('a', 'exec'), latest]);
  assert.equal(pairs.length, 1);
  assert.equal(pairs[0].result, latest);
  const nodes = buildSessionNarrative([call('a', 'exec'), original, call('a', 'exec'), latest]);
  assert.equal(nodes[0].items.length, 2);
  assert.equal(nodes[0].toolCount, 1);
  assert.equal(nodes[0].items[1], latest);
});

test('historical todowrite structured failure is failed, including unpaired results', () => {
  const output = { success: false, code: 'PLAN_EXECUTION_NOT_APPROVED', error: 'Plan mode requires approval' };
  for (const toolOutput of [output, JSON.stringify(output)]) {
    const action = call('plan-call', 'plan-one', { toolName: 'todowrite' });
    const observation = result('plan-result', 'plan-one', { toolName: 'todowrite', isError: false, toolOutput });
    assert.equal(module.exports.toolCallPairStatus({ call: action, result: observation }), 'failed');
    assert.equal(module.exports.toolCallPairStatus({ call: observation }), 'failed');
    assert.equal(sessionToolGroupStatus([action, observation]), 'failed');
    assert.equal(sessionToolGroupStatus([observation]), 'failed');
    assert.equal(sessionToolGroupStatus([action, observation, {id:'run',type:'run_status',payload:{status:'running'}}]), 'failed');
  }
  for (const toolOutput of [{ success: true }, { success: 'false' }, { content: [{ text: 'error' }] }, { nested: { success: false } }]) {
    assert.equal(module.exports.toolCallPairStatus({ call: call('c', 'ok'), result: result('r', 'ok', { toolOutput }) }), 'complete');
  }
  assert.equal(module.exports.toolCallPairStatus({call:call('c','err'),result:result('r','err',{payload:{tool_output:{error:{code:'DENIED'}}}})}),'failed');
});
