import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  conversationSearchMatches,
  moveConversationSearchIndex,
  resolveConversationSearchIndex,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/conversationSearchModel.js',
);
const chatPanelSource = readFileSync(
  new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
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

test('conversation search matches one row per structured Web timeline event', () => {
  const items = [
    {
      id: 'user-1',
      type: 'user_message',
      role: 'user',
      content: 'Inspect the Cache policy.',
    },
    {
      id: 'assistant-1',
      type: 'assistant_message',
      role: 'assistant',
      content: 'CACHE policy verified.',
    },
    {
      id: 'thought-1',
      type: 'thought',
      content: 'Trace the cache invalidation path.',
    },
    {
      id: 'act-1',
      type: 'act',
      toolName: 'cache.read',
      toolInput: { path: '/workspace/cache.json' },
    },
    {
      id: 'observe-1',
      type: 'observe',
      toolName: 'cache.read',
      toolOutput: 'Cache hit.',
    },
    {
      id: 'observe-tool-name-only',
      type: 'observe',
      toolName: 'cache.secret',
      toolOutput: 'Unrelated output.',
    },
    {
      id: 'state-only-1',
      type: 'cost_update',
      content: 'cache must stay out of search',
    },
  ];

  assert.deepEqual(
    conversationSearchMatches(items, '  cAcHe  ').map((match) => ({
      eventId: match.eventId,
      eventIndex: match.eventIndex,
      anchorId: match.anchorId,
    })),
    [
      { eventId: 'user-1', eventIndex: 0, anchorId: 'user-1' },
      { eventId: 'assistant-1', eventIndex: 1, anchorId: 'assistant-1' },
      { eventId: 'thought-1', eventIndex: 2, anchorId: 'thought-1' },
      { eventId: 'act-1', eventIndex: 3, anchorId: 'act-1' },
      { eventId: 'observe-1', eventIndex: 4, anchorId: 'observe-1' },
    ],
  );
  assert.deepEqual(conversationSearchMatches(items, '   '), []);
});

test('conversation search navigation wraps and preserves a stable anchor after prepends', () => {
  const initial = conversationSearchMatches(
    [
      { id: 'assistant-a', type: 'assistant_message', content: 'match' },
      { id: 'assistant-b', type: 'assistant_message', content: 'match' },
    ],
    'match',
  );
  const prepended = conversationSearchMatches(
    [
      { id: 'assistant-new', type: 'assistant_message', content: 'match' },
      { id: 'assistant-a', type: 'assistant_message', content: 'match' },
      { id: 'assistant-b', type: 'assistant_message', content: 'match' },
    ],
    'match',
  );

  assert.equal(moveConversationSearchIndex(0, initial.length, 'previous'), 1);
  assert.equal(moveConversationSearchIndex(1, initial.length, 'next'), 0);
  assert.equal(moveConversationSearchIndex(7, 0, 'next'), 0);
  assert.equal(resolveConversationSearchIndex(prepended, 'assistant-b', 1), 2);
  assert.equal(resolveConversationSearchIndex(initial, 'missing-anchor', 9), 1);
});

test('desktop conversation search mirrors the Web keyboard, focus, count, and anchor contract', () => {
  assert.match(
    chatPanelSource,
    /\(event\.metaKey \|\| event\.ctrlKey\)[\s\S]*?event\.key\.toLowerCase\(\) === 'f'[\s\S]*?preventDefault\(\)[\s\S]*?setConversationSearchVisible/,
  );
  assert.match(chatPanelSource, /<ConversationSearch[\s\S]*?items=\{timelineItems \?\? \[\]\}/);
  assert.match(conversationSearchSource, /event\.key === 'Escape'[\s\S]*?onClose\(\)/);
  assert.match(
    conversationSearchSource,
    /event\.key === 'Enter'[\s\S]*?event\.shiftKey[\s\S]*?'previous'[\s\S]*?'next'/,
  );
  assert.match(conversationSearchSource, /inputRef\.current\?\.focus\(\)/);
  assert.match(conversationSearchSource, /aria-live="polite"/);
  assert.match(conversationSearchSource, /data-timeline-anchor-id/);
  assert.match(conversationSearchSource, /data-timeline-anchor-members/);
  assert.match(conversationSearchSource, /scrollIntoView/);
  assert.match(conversationSearchSource, /chat-search-highlight/);
  assert.match(chatPanelStyles, /\.conversation-search-overlay/);
  assert.match(chatPanelStyles, /\.chat-search-highlight/);
  assert.equal(i18nSource.match(/'chat\.search\.placeholder':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.search\.noResults':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.search\.previousResult':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.search\.nextResult':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.search\.close':/g)?.length, 2);
});
