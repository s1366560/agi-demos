import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  pinnedMessagesInTimelineOrder,
  reconcilePinnedMessageIds,
  togglePinnedMessageId,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/pinnedMessageModel.js',
);

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

const chatPanelSource = readSource('features/chat/ChatPanel.tsx');
const chatTimelineSource = readSource('features/chat/ChatTimeline.tsx');
const chatTranscriptSource = readSource('features/chat/ChatTranscript.tsx');
const pinnedMessagesSource = readSource('features/chat/PinnedMessages.tsx');
const chatStyles = readSource('features/chat/ChatPanel.css');
const i18nSource = readSource('i18n.tsx');

const messages = [
  {
    id: 'user-1',
    conversationId: 'conversation-1',
    kind: 'user',
    content: 'First prompt',
  },
  {
    id: 'agent-1',
    conversationId: 'conversation-1',
    kind: 'agent',
    content: 'First answer',
  },
  {
    id: 'runtime-1',
    conversationId: 'conversation-1',
    kind: 'runtime',
    content: 'Runtime update',
  },
  {
    id: 'agent-2',
    conversationId: 'conversation-1',
    kind: 'agent',
    content: 'Second answer',
  },
];

test('pinned messages remain agent-only, deduplicated, and ordered by the timeline', () => {
  assert.deepEqual(
    pinnedMessagesInTimelineOrder(messages, [
      'agent-2',
      'user-1',
      'agent-1',
      'agent-2',
      'runtime-1',
    ]).map((message) => message.id),
    ['agent-1', 'agent-2'],
  );
});

test('pin identity survives content updates and prunes removed targets without rebinding', () => {
  const updated = messages.map((message) =>
    message.id === 'agent-1'
      ? { ...message, content: 'First answer, still streaming' }
      : message,
  );
  assert.deepEqual(reconcilePinnedMessageIds(['agent-1', 'missing'], updated), ['agent-1']);
  assert.deepEqual(
    reconcilePinnedMessageIds(['agent-1'], updated.filter((message) => message.id !== 'agent-1')),
    [],
  );
  assert.deepEqual(
    pinnedMessagesInTimelineOrder(updated, ['agent-1']).map((message) => message.content),
    ['First answer, still streaming'],
  );
});

test('pin toggling is immutable and stable by structured message ID', () => {
  const initial = ['agent-1'];
  const added = togglePinnedMessageId(initial, 'agent-2');
  const removed = togglePinnedMessageId(added, 'agent-1');

  assert.deepEqual(initial, ['agent-1']);
  assert.deepEqual(added, ['agent-1', 'agent-2']);
  assert.deepEqual(removed, ['agent-2']);
});

test('Desktop mirrors the Web pinned-message interaction and accessibility contract', () => {
  assert.match(chatPanelSource, /pinnedMessagesInTimelineOrder\(/);
  assert.match(chatPanelSource, /reconcilePinnedMessageIds\(/);
  assert.match(
    chatPanelSource,
    /useEffect\(\(\) => \{[\s\S]*?setPinnedMessageIds\(\[\]\)[\s\S]*?messageActionConversationId/,
  );
  assert.match(chatPanelSource, /data-timeline-anchor-id/);
  assert.match(chatPanelSource, /timelineAnchorMemberIds/);
  assert.match(chatPanelSource, /scrollIntoView/);
  assert.match(chatPanelSource, /\.focus\(\{ preventScroll: true \}\)/);
  assert.match(chatPanelSource, /chat-pinned-jump-target/);
  assert.match(chatTimelineSource, /onPinMessage/);
  assert.match(chatTimelineSource, /isPinned/);
  assert.match(chatTranscriptSource, /kind === 'agent'[\s\S]*?onPin/);
  assert.match(chatTranscriptSource, /aria-pressed=\{isPinned\}/);
  assert.match(chatTranscriptSource, /timelineItemId=\{message\.id\}/);
  assert.match(pinnedMessagesSource, /aria-expanded=\{!collapsed\}/);
  assert.match(pinnedMessagesSource, /aria-controls=/);
  assert.match(pinnedMessagesSource, /onJump\(message\)/);
  assert.match(pinnedMessagesSource, /onUnpin\(message\)/);
  assert.match(chatStyles, /\.chat-pinned-messages/);
  assert.match(chatStyles, /\.chat-pinned-jump-target/);
  assert.equal(i18nSource.match(/'chat\.pinnedMessages':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.pinMessage':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.unpinMessage':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.jumpToPinnedMessage':/g)?.length, 2);
});
