import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { deriveCurrentActivity, formatElapsedClock } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/currentActivityModel.js',
);

let idSequence = 0;

function item(overrides) {
  idSequence += 1;
  return {
    id: overrides.id ?? `item-${idSequence}`,
    type: 'act',
    eventTimeUs: 1_000_000 + idSequence * 1_000,
    eventCounter: idSequence,
    ...overrides,
  };
}

function userItem(overrides = {}) {
  return item({ type: 'user_message', role: 'user', content: 'do the thing', ...overrides });
}

function toolCall(overrides = {}) {
  return item({
    type: 'act',
    toolName: 'terminal',
    toolInput: { command: 'npm test' },
    ...overrides,
  });
}

function toolResult(call, overrides = {}) {
  return item({
    type: 'observe',
    toolName: call.toolName,
    content: 'ok',
    ...overrides,
  });
}

function subagentStarted(name, overrides = {}) {
  return item({
    type: 'subagent_started',
    payload: { subagent_name: name, task: `task for ${name}`, ...(overrides.payload ?? {}) },
    ...overrides,
  });
}

test('returns null when the run is not live', () => {
  const items = [userItem(), toolCall()];
  assert.equal(deriveCurrentActivity({ items, presence: 'recorded' }), null);
});

test('returns a generic working headline when live with no activity yet', () => {
  const headline = deriveCurrentActivity({ items: [], presence: 'live' });
  assert.ok(headline);
  assert.equal(headline.kind, 'working');
  assert.equal(headline.titleKey, 'session.currentActivity.working');
  assert.equal(headline.label, '');
  assert.deepEqual(headline.entries, []);
});

test('derives a tool headline from an in-flight tool call', () => {
  const call = toolCall({
    display: { title: 'Run command', summary: 'npm test', kind: 'command' },
  });
  const headline = deriveCurrentActivity({ items: [userItem(), call], presence: 'live' });
  assert.ok(headline);
  assert.equal(headline.kind, 'command');
  assert.equal(headline.label, 'Run command');
  assert.equal(headline.titleKey, null);
  assert.equal(headline.detail, 'npm test');
  assert.equal(headline.startedAtMs, Math.floor(call.eventTimeUs / 1000));
});

test('falls back to toolName and primary input argument without display data', () => {
  const call = toolCall({ toolName: 'read_file', toolInput: { path: 'src/App.tsx' } });
  const headline = deriveCurrentActivity({ items: [userItem(), call], presence: 'live' });
  assert.ok(headline);
  assert.equal(headline.kind, 'tool');
  assert.equal(headline.label, 'read_file');
  assert.equal(headline.detail, 'src/App.tsx');
});

test('truncates long detail with an ellipsis', () => {
  const longSummary = `x`.repeat(200);
  const call = toolCall({ display: { title: 'Run command', summary: longSummary } });
  const headline = deriveCurrentActivity({ items: [userItem(), call], presence: 'live' });
  assert.ok(headline);
  assert.ok(headline.detail.length <= 96);
  assert.ok(headline.detail.endsWith('…'));
});

test('completed tool calls fall through to the working headline during idle gaps', () => {
  const call = toolCall();
  const result = toolResult(call);
  const headline = deriveCurrentActivity({
    items: [userItem(), call, result],
    presence: 'live',
  });
  assert.ok(headline);
  assert.equal(headline.kind, 'working');
  assert.equal(headline.titleKey, 'session.currentActivity.working');
  // The clock reflects the whole run (from the user turn), not the last step.
  assert.ok(headline.startedAtMs !== null);
});

test('thought-only streaming produces a thinking headline', () => {
  const thought = item({
    type: 'thought',
    content: ' weighing the options ',
    metadata: { streaming: true },
  });
  const headline = deriveCurrentActivity({ items: [userItem(), thought], presence: 'live' });
  assert.ok(headline);
  assert.equal(headline.kind, 'thinking');
  assert.equal(headline.titleKey, 'session.currentActivity.thinking');
  assert.equal(headline.detail, 'weighing the options');
});

test('streaming assistant text produces a responding headline', () => {
  const reply = item({
    type: 'assistant_message',
    role: 'assistant',
    content: 'partial answer',
    metadata: { streaming: true },
  });
  const headline = deriveCurrentActivity({ items: [userItem(), reply], presence: 'live' });
  assert.ok(headline);
  assert.equal(headline.kind, 'responding');
  assert.equal(headline.titleKey, 'session.currentActivity.responding');
});

test('summarizes multiple concurrent subagents with the most recent one', () => {
  const first = subagentStarted('researcher');
  const second = subagentStarted('coder');
  const headline = deriveCurrentActivity({
    items: [userItem(), first, second],
    presence: 'live',
  });
  assert.ok(headline);
  assert.equal(headline.kind, 'subagent');
  assert.equal(headline.label, 'coder');
  assert.equal(headline.detail, 'task for coder');
  assert.equal(headline.activeSubagentCount, 2);
  const subagentEntries = headline.entries.filter((entry) => entry.kind === 'subagent');
  assert.equal(subagentEntries.length, 2);
  assert.ok(subagentEntries.every((entry) => entry.status === 'running'));
});

test('a fresh running tool call wins over an older active subagent', () => {
  const subagent = subagentStarted('researcher');
  const call = toolCall({ display: { title: 'Read file', kind: 'read', summary: 'a.ts' } });
  const headline = deriveCurrentActivity({
    items: [userItem(), subagent, call],
    presence: 'live',
  });
  assert.ok(headline);
  assert.equal(headline.kind, 'read');
  assert.equal(headline.label, 'Read file');
  assert.equal(headline.activeSubagentCount, 1);
});

test('a fresh subagent event wins over an older running tool call', () => {
  const call = toolCall();
  const subagent = subagentStarted('researcher');
  const headline = deriveCurrentActivity({
    items: [userItem(), call, subagent],
    presence: 'live',
  });
  assert.ok(headline);
  assert.equal(headline.kind, 'subagent');
  assert.equal(headline.label, 'researcher');
});

test('expansion entries list recent tool pairs chronologically and cap the count', () => {
  const items = [userItem()];
  for (let index = 0; index < 10; index += 1) {
    const call = toolCall({ toolName: `tool_${index}` });
    items.push(call, toolResult(call));
  }
  items.push(toolCall({ toolName: 'tool_running' }));
  const headline = deriveCurrentActivity({ items, presence: 'live', maxEntries: 5 });
  assert.ok(headline);
  assert.equal(headline.entries.length, 5);
  const last = headline.entries[headline.entries.length - 1];
  assert.equal(last.label, 'tool_running');
  assert.equal(last.status, 'running');
  const firstKept = headline.entries[0];
  assert.equal(firstKept.label, 'tool_6');
  assert.equal(firstKept.status, 'complete');
});

test('formats elapsed durations as a ticking clock', () => {
  assert.equal(formatElapsedClock(0), '00:00');
  assert.equal(formatElapsedClock(999), '00:00');
  assert.equal(formatElapsedClock(65_000), '01:05');
  assert.equal(formatElapsedClock(599_000), '09:59');
  assert.equal(formatElapsedClock(3_600_000), '1:00:00');
  assert.equal(formatElapsedClock(3_661_000), '1:01:01');
  assert.equal(formatElapsedClock(-5), '');
  assert.equal(formatElapsedClock(Number.NaN), '');
});
