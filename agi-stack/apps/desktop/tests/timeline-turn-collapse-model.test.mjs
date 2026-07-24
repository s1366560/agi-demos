import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  collapsedTimelineTurnStorageKey,
  computeTimelineTurns,
  readCollapsedTimelineTurnIds,
  timelineTurnForMember,
  writeCollapsedTimelineTurnIds,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/timelineTurnCollapseModel.js',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const chatPanelSource = readFileSync(
  new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
  'utf8',
);
const chatTimelineSource = readFileSync(
  new URL('../src/features/chat/ChatTimeline.tsx', import.meta.url),
  'utf8',
);
const conversationSearchSource = readFileSync(
  new URL('../src/features/chat/ConversationSearch.tsx', import.meta.url),
  'utf8',
);
const chatPanelStyles = readFileSync(
  new URL('../src/features/chat/ChatPanel.css', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

test('timeline turns use structural user boundaries and preserve response event order', () => {
  const turns = computeTimelineTurns([
    { id: 'runtime-before', type: 'runtime_status' },
    { id: 'user-1', type: 'user_message', role: 'user' },
    { id: 'thought-1', type: 'thought' },
    { id: 'tool-1', type: 'act' },
    { id: 'assistant-1', type: 'assistant_message', role: 'assistant' },
    { id: 'user-2', type: 'user_message', role: 'user' },
    { id: 'assistant-2', type: 'assistant_message', role: 'assistant' },
  ]);

  assert.deepEqual(turns, [
    {
      id: 'user-1',
      userItemId: 'user-1',
      responseItemIds: ['thought-1', 'tool-1', 'assistant-1'],
    },
    {
      id: 'user-2',
      userItemId: 'user-2',
      responseItemIds: ['assistant-2'],
    },
  ]);
  assert.equal(timelineTurnForMember(turns, 'tool-1')?.id, 'user-1');
  assert.equal(timelineTurnForMember(turns, 'user-1'), null);
  assert.equal(timelineTurnForMember(turns, 'runtime-before'), null);
});

test('empty response turns remain structural but are not eligible for collapse', () => {
  assert.deepEqual(
    computeTimelineTurns([
      { id: 'user-1', type: 'user_message' },
      { id: 'user-2', role: 'user', type: 'message' },
    ]),
    [
      { id: 'user-1', userItemId: 'user-1', responseItemIds: [] },
      { id: 'user-2', userItemId: 'user-2', responseItemIds: [] },
    ],
  );
});

test('turn collapse storage is isolated by runtime, tenant, project, and conversation', () => {
  const base = {
    mode: 'cloud',
    apiBaseUrl: 'https://user:secret@example.test/api/v1/?token=private#fragment',
    tenantId: 'tenant-a',
    projectId: 'project-a',
    conversationId: 'conversation-a',
  };
  const key = collapsedTimelineTurnStorageKey(base);

  assert.match(key, /^memstack:desktop:turn-collapse:v1:/);
  assert.doesNotMatch(key, /user|secret|token|private|fragment/);
  assert.notEqual(
    key,
    collapsedTimelineTurnStorageKey({ ...base, mode: 'local' }),
  );
  assert.notEqual(
    key,
    collapsedTimelineTurnStorageKey({ ...base, tenantId: 'tenant-b' }),
  );
  assert.notEqual(
    key,
    collapsedTimelineTurnStorageKey({ ...base, projectId: 'project-b' }),
  );
  assert.notEqual(
    key,
    collapsedTimelineTurnStorageKey({ ...base, conversationId: 'conversation-b' }),
  );
});

test('turn collapse storage tolerates malformed data and persists bounded IDs only', () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  const scope = {
    mode: 'local',
    apiBaseUrl: 'not a URL',
    tenantId: 'tenant-a',
    projectId: 'project-a',
    conversationId: 'conversation-a',
  };
  const key = collapsedTimelineTurnStorageKey(scope);

  values.set(key, '{bad json');
  assert.deepEqual(readCollapsedTimelineTurnIds(storage, scope), []);

  values.set(
    key,
    JSON.stringify(['turn-a', '', 42, 'turn-a', 'x'.repeat(300), 'turn-b']),
  );
  assert.deepEqual(readCollapsedTimelineTurnIds(storage, scope), ['turn-a', 'turn-b']);

  writeCollapsedTimelineTurnIds(
    storage,
    scope,
    Array.from({ length: 600 }, (_, index) => `turn-${index}`),
  );
  const saved = JSON.parse(values.get(key));
  assert.equal(saved.length, 500);
  assert.equal(saved[0], 'turn-100');
  assert.equal(saved.at(-1), 'turn-599');
});

test('desktop timeline exposes a Web-parity accessible whole-turn collapse contract', () => {
  assert.match(appSource, /turnCollapseRuntime=\{\{[\s\S]*?mode: config\.mode[\s\S]*?apiBaseUrl/);
  assert.match(chatPanelSource, /computeTimelineTurns\(timelineDisplayItems\)/);
  assert.match(chatPanelSource, /useTimelineTurnCollapse/);
  assert.match(chatTimelineSource, /aria-expanded=\{!collapsed\}/);
  assert.match(chatTimelineSource, /aria-controls=\{regionId\}/);
  assert.match(chatTimelineSource, /className="timeline-turn-placeholder"/);
  assert.match(chatTimelineSource, /data-timeline-anchor-members=\{membersJson\}/);
  assert.match(chatTimelineSource, /window\.requestAnimationFrame[\s\S]*?\.focus\(\)/);
  assert.match(chatPanelStyles, /\.timeline-turn-collapse-control:focus-visible/);
  assert.match(chatPanelStyles, /\.timeline-turn-placeholder:focus-visible/);
  assert.equal(i18nSource.match(/'session\.collapseTurn':/g)?.length, 2);
  assert.equal(i18nSource.match(/'session\.expandTurn':/g)?.length, 2);
  assert.equal(i18nSource.match(/'session\.turnItemsHidden':/g)?.length, 2);
});

test('search and pinned jumps reveal a collapsed response before locating its anchor', () => {
  assert.match(chatPanelSource, /const revealTimelineMember = useCallback/);
  assert.match(
    chatPanelSource,
    /revealTimelineMember\(message\.id\)[\s\S]*?requestAnimationFrame/,
  );
  assert.match(chatPanelSource, /<ConversationSearch[\s\S]*?onRevealItem=\{revealTimelineMember\}/);
  assert.match(conversationSearchSource, /onRevealItem\?: \(itemId: string\) => boolean/);
  assert.match(
    conversationSearchSource,
    /onRevealItem\?\.\(match\.anchorId\)[\s\S]*?requestAnimationFrame/,
  );
});
