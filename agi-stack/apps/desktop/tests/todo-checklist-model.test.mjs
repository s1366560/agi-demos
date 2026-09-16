import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  formatTodoToolCallSummary,
  isTodoToolName,
  todoChecklistFromTimeline,
  todoChecklistStats,
  todoToolCallSummary,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/todoChecklistModel.js');

/** Minimal i18n stub: English strings mirroring src/i18n.tsx entries. */
const EN = {
  'chat.todo.verb.add': 'Add',
  'chat.todo.verb.update': 'Update',
  'chat.todo.verb.replace': 'Replace',
  'chat.todo.verb.write': 'Update',
  'chat.todo.writeMany': '{verb} {count} todos: {summary}',
  'chat.todo.write': '{verb} todos',
  'chat.todo.writeOne': '{verb} todo {id}',
  'chat.todo.readMany': 'Read {count} todos: {summary}',
  'chat.todo.read': 'Read todos',
  'chat.todo.status.pending': 'pending',
  'chat.todo.status.inProgress': 'in progress',
  'chat.todo.status.completed': 'completed',
  'chat.todo.status.failed': 'failed',
  'chat.todo.status.cancelled': 'cancelled',
  'chat.todo.status.blocked': 'blocked',
  'chat.todo.statusCount': '{count} {status}',
  'chat.todo.moreItems': ' and {count} more',
};
const t = (key, values) =>
  Object.entries(values ?? {}).reduce(
    (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
    EN[key] ?? key,
  );

let counter = 0;
const item = (overrides) => ({
  id: `item-${(counter += 1)}`,
  eventTimeUs: counter * 1000,
  eventCounter: counter,
  ...overrides,
});

test('isTodoToolName matches todo tool spellings and rejects others', () => {
  assert.equal(isTodoToolName('todowrite'), true);
  assert.equal(isTodoToolName('TodoWrite'), true);
  assert.equal(isTodoToolName('todo_write'), true);
  assert.equal(isTodoToolName('todoread'), true);
  assert.equal(isTodoToolName('todo'), true);
  assert.equal(isTodoToolName('read_file'), false);
  assert.equal(isTodoToolName(undefined), false);
  assert.equal(isTodoToolName(''), false);
});

test('checklist is empty when the timeline has no task events or todo calls', () => {
  assert.deepEqual(todoChecklistFromTimeline([]), []);
  assert.deepEqual(
    todoChecklistFromTimeline([
      item({ type: 'act', toolName: 'read_file', toolInput: { path: 'a.ts' } }),
    ]),
    [],
  );
});

test('task_list_updated replaces the checklist and normalizes fields', () => {
  const items = todoChecklistFromTimeline([
    item({
      type: 'task_list_updated',
      payload: {
        tasks: [
          { id: 'a', content: ' Write tests ', status: 'in_progress', priority: 'high', order_index: 1 },
          { id: 'b', content: 'Ship it', status: 'done' },
          { id: 'c', title: 'Fallback title field', status: 'running' },
          { id: 'd', content: '   ' },
          { noContent: true },
          { id: 'e', content: 'Dropped low', status: 'canceled', priority: 'low' },
        ],
      },
    }),
  ]);

  // Sorted by (orderIndex, sourceIndex): a(1,0), b(1,1), c(2,2), e(4,4).
  assert.deepEqual(items, [
    { id: 'a', content: 'Write tests', status: 'in_progress', priority: 'high', orderIndex: 1 },
    { id: 'b', content: 'Ship it', status: 'completed', priority: 'medium', orderIndex: 1 },
    { id: 'c', content: 'Fallback title field', status: 'in_progress', priority: 'medium', orderIndex: 2 },
    { id: 'e', content: 'Dropped low', status: 'cancelled', priority: 'low', orderIndex: 5 },
  ]);
});

test('task_list_updated accepts a direct tasks array on the item', () => {
  const items = todoChecklistFromTimeline([
    item({
      type: 'task_list_updated',
      tasks: [{ id: 'x', content: 'Direct array', status: 'pending' }],
    }),
  ]);
  assert.equal(items.length, 1);
  assert.equal(items[0].content, 'Direct array');
});

test('a later task_list_updated fully replaces the earlier list', () => {
  const items = todoChecklistFromTimeline([
    item({
      type: 'task_list_updated',
      payload: { tasks: [{ id: 'old', content: 'Old plan', status: 'pending' }] },
    }),
    item({
      type: 'task_list_updated',
      payload: { tasks: [{ id: 'new', content: 'New plan', status: 'pending' }] },
    }),
  ]);
  assert.deepEqual(
    items.map((entry) => entry.id),
    ['new'],
  );
});

test('task_updated patches status and content of a known task (record shape)', () => {
  const items = todoChecklistFromTimeline([
    item({
      type: 'task_list_updated',
      payload: {
        tasks: [
          { id: 'one', content: 'First', status: 'pending' },
          { id: 'two', content: 'Second', status: 'pending' },
        ],
      },
    }),
    item({
      type: 'task_updated',
      payload: { task: { id: 'two', status: 'completed' } },
    }),
  ]);
  assert.equal(items[1].status, 'completed');
  assert.equal(items[0].status, 'pending');
});

test('task_updated patches a known task (flat web shape) and ignores unknown ids', () => {
  const items = todoChecklistFromTimeline([
    item({
      type: 'task_list_updated',
      payload: { tasks: [{ id: 'one', content: 'First', status: 'pending' }] },
    }),
    item({ type: 'task_updated', payload: { task_id: 'one', status: 'failed', content: 'First (edited)' } }),
    item({ type: 'task_updated', payload: { task_id: 'ghost', status: 'completed' } }),
  ]);
  assert.deepEqual(items, [
    { id: 'one', content: 'First (edited)', status: 'failed', priority: 'medium', orderIndex: 0 },
  ]);
});

test('falls back to the latest todowrite tool call when no task events exist', () => {
  const items = todoChecklistFromTimeline([
    item({
      type: 'act',
      toolName: 'todowrite',
      toolInput: {
        todos: [
          { content: 'Stale list', status: 'pending' },
        ],
      },
    }),
    item({
      type: 'act',
      toolName: 'todowrite',
      toolInput: JSON.stringify({
        todos: [
          { content: 'Fresh A', status: 'completed', priority: 'high' },
          { content: 'Fresh B', status: 'in_progress' },
        ],
      }),
    }),
  ]);
  assert.deepEqual(
    items.map((entry) => [entry.content, entry.status, entry.priority]),
    [
      ['Fresh A', 'completed', 'high'],
      ['Fresh B', 'in_progress', 'medium'],
    ],
  );
});

test('falls back to todos inside a todo tool result when the input has none', () => {
  const items = todoChecklistFromTimeline([
    item({
      type: 'observe',
      toolName: 'todoread',
      toolOutput: { todos: [{ content: 'From output', status: 'pending' }] },
    }),
  ]);
  assert.equal(items.length, 1);
  assert.equal(items[0].content, 'From output');
});

test('task events win over todowrite fallback', () => {
  const items = todoChecklistFromTimeline([
    item({
      type: 'act',
      toolName: 'todowrite',
      toolInput: { todos: [{ content: 'Tool list', status: 'pending' }] },
    }),
    item({
      type: 'task_list_updated',
      payload: { tasks: [{ id: 'ev', content: 'Event list', status: 'pending' }] },
    }),
  ]);
  assert.deepEqual(
    items.map((entry) => entry.content),
    ['Event list'],
  );
});

test('todoChecklistStats matches the web TaskList counters', () => {
  const stats = todoChecklistStats([
    { id: 'a', content: 'A', status: 'completed', priority: 'medium', orderIndex: 0 },
    { id: 'b', content: 'B', status: 'completed', priority: 'medium', orderIndex: 1 },
    { id: 'c', content: 'C', status: 'in_progress', priority: 'medium', orderIndex: 2 },
    { id: 'd', content: 'D', status: 'failed', priority: 'medium', orderIndex: 3 },
    { id: 'e', content: 'E', status: 'cancelled', priority: 'medium', orderIndex: 4 },
  ]);
  assert.deepEqual(stats, { total: 5, completed: 2, failed: 1, active: 1, percent: 40 });
  assert.deepEqual(todoChecklistStats([]), {
    total: 0,
    completed: 0,
    failed: 0,
    active: 0,
    percent: 0,
  });
});

test('todoToolCallSummary counts statuses and keeps the first two titles', () => {
  const summary = todoToolCallSummary(
    item({
      type: 'act',
      toolName: 'todowrite',
      toolInput: {
        todos: [
          { content: 'Alpha', status: 'completed' },
          { content: 'Beta', status: 'in_progress' },
          { content: 'Gamma', status: 'pending' },
          { content: 'Delta', status: 'pending' },
        ],
      },
    }),
    null,
  );
  assert.deepEqual(summary, {
    kind: 'write',
    verb: 'write',
    total: 4,
    statusCounts: [
      { status: 'completed', count: 1 },
      { status: 'in_progress', count: 1 },
      { status: 'pending', count: 2 },
    ],
    titles: ['Alpha', 'Beta'],
    hiddenTitleCount: 2,
    todoId: null,
  });
});

test('todoToolCallSummary reads the action verb and todo_id', () => {
  const replace = todoToolCallSummary(
    item({
      type: 'act',
      toolName: 'todowrite',
      toolInput: { action: 'replace', todos: [{ content: 'Only', status: 'pending' }] },
    }),
    null,
  );
  assert.equal(replace.verb, 'replace');

  const single = todoToolCallSummary(
    item({
      type: 'act',
      toolName: 'todowrite',
      toolInput: { action: 'update', todo_id: 'task-9' },
    }),
    null,
  );
  assert.deepEqual({ verb: single.verb, total: single.total, todoId: single.todoId }, {
    verb: 'update',
    total: 0,
    todoId: 'task-9',
  });
});

test('todoToolCallSummary prefers titled input todos over the result echo', () => {
  const summary = todoToolCallSummary(
    item({ type: 'act', toolName: 'todowrite', toolInput: { todos: [{ status: 'pending' }] } }),
    item({
      type: 'observe',
      toolName: 'todowrite',
      toolOutput: { todos: [{ content: 'Echo', status: 'completed' }] },
    }),
  );
  // Input todos have no titles, so the titled result echo wins (web behavior).
  assert.equal(summary.total, 1);
  assert.deepEqual(summary.titles, ['Echo']);
});

test('todoToolCallSummary classifies todoread as a read and returns null for other tools', () => {
  const read = todoToolCallSummary(
    item({
      type: 'observe',
      toolName: 'todoread',
      toolOutput: { todos: [{ content: 'A', status: 'pending' }] },
    }),
    null,
  );
  assert.equal(read.kind, 'read');
  assert.equal(
    todoToolCallSummary(item({ type: 'act', toolName: 'read_file', toolInput: {} }), null),
    null,
  );
});

test('formatTodoToolCallSummary renders the web-style status-count title', () => {
  const summary = todoToolCallSummary(
    item({
      type: 'act',
      toolName: 'todowrite',
      toolInput: {
        todos: [
          { content: 'Alpha', status: 'completed' },
          { content: 'Beta', status: 'in_progress' },
          { content: 'Gamma', status: 'pending' },
          { content: 'Delta', status: 'pending' },
        ],
      },
    }),
    null,
  );
  assert.equal(
    formatTodoToolCallSummary(summary, t),
    'Update 4 todos: 1 completed, 1 in progress, 2 pending: Alpha, Beta and 2 more',
  );
});

test('formatTodoToolCallSummary renders read, single-id, and empty variants', () => {
  const read = todoToolCallSummary(
    item({
      type: 'observe',
      toolName: 'todoread',
      toolOutput: { todos: [{ content: 'A', status: 'blocked' }, { content: 'B' }] },
    }),
    null,
  );
  assert.equal(
    formatTodoToolCallSummary(read, t),
    'Read 2 todos: 1 blocked, 1 pending: A, B',
  );

  const emptyRead = todoToolCallSummary(
    item({ type: 'observe', toolName: 'todoread', toolOutput: { todos: [] } }),
    null,
  );
  assert.equal(formatTodoToolCallSummary(emptyRead, t), 'Read todos');

  const single = todoToolCallSummary(
    item({ type: 'act', toolName: 'todowrite', toolInput: { action: 'add', todo_id: 'task-9' } }),
    null,
  );
  assert.equal(formatTodoToolCallSummary(single, t), 'Add todo task-9');

  const bare = todoToolCallSummary(
    item({ type: 'act', toolName: 'todowrite', toolInput: {} }),
    null,
  );
  assert.equal(formatTodoToolCallSummary(bare, t), 'Update todos');
});
