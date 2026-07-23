import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  conversationComparisonAvailable,
  conversationComparisonCandidates,
  conversationComparisonMessages,
  conversationComparisonRequestMatches,
  conversationComparisonScope,
  conversationComparisonScopeKey,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/conversationComparisonModel.js');

const readSource = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

const chatPanelSource = readSource('features/chat/ChatPanel.tsx');
const comparisonSource = readSource('features/chat/ConversationComparison.tsx');
const catalogSource = readSource('features/chat/composerCatalogModel.ts');
const chatStyles = readSource('features/chat/ChatPanel.css');
const i18nSource = readSource('i18n.tsx');

const currentConversation = {
  id: 'conversation-current',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  user_id: 'user-1',
  title: 'Current investigation',
  status: 'active',
  message_count: 2,
  created_at: '2026-07-24T00:00:00Z',
  workspace_id: 'workspace-1',
};

const comparisonConversation = {
  ...currentConversation,
  id: 'conversation-target',
  title: 'Release verification',
  message_count: 4,
  updated_at: '2026-07-24T02:00:00Z',
};

const otherConversation = {
  ...currentConversation,
  id: 'conversation-other',
  title: 'Incident review',
  message_count: 6,
  updated_at: '2026-07-24T01:00:00Z',
};

test('comparison remains available for an authoritative empty conversation', () => {
  assert.equal(
    conversationComparisonAvailable({ ...currentConversation, message_count: 0 }, true),
    true,
  );
  assert.equal(conversationComparisonAvailable(null, true), false);
  assert.equal(conversationComparisonAvailable(currentConversation, false), false);
});

test('comparison candidates stay in scope, exclude the current identity, and search title or id', () => {
  const crossTenant = {
    ...comparisonConversation,
    id: 'conversation-cross-tenant',
    tenant_id: 'tenant-2',
  };
  const crossProject = {
    ...comparisonConversation,
    id: 'conversation-cross-project',
    project_id: 'project-2',
  };
  const catalog = [
    currentConversation,
    comparisonConversation,
    crossTenant,
    otherConversation,
    crossProject,
  ];

  assert.deepEqual(
    conversationComparisonCandidates(catalog, currentConversation, '').map(
      (conversation) => conversation.id,
    ),
    ['conversation-target', 'conversation-other'],
  );
  assert.deepEqual(
    conversationComparisonCandidates(catalog, currentConversation, 'release').map(
      (conversation) => conversation.id,
    ),
    ['conversation-target'],
  );
  assert.deepEqual(
    conversationComparisonCandidates(catalog, currentConversation, 'OTHER').map(
      (conversation) => conversation.id,
    ),
    ['conversation-other'],
  );
});

test('comparison scope snapshots exact authority and rejects identity or scope drift', () => {
  const scope = conversationComparisonScope(currentConversation, comparisonConversation);
  assert.deepEqual(scope, {
    tenantId: 'tenant-1',
    projectId: 'project-1',
    leftConversationId: 'conversation-current',
    rightConversationId: 'conversation-target',
  });
  assert.equal(conversationComparisonScope(currentConversation, currentConversation), null);
  assert.equal(
    conversationComparisonScope(currentConversation, {
      ...comparisonConversation,
      project_id: 'project-2',
    }),
    null,
  );
  assert.equal(
    conversationComparisonScopeKey(scope),
    'tenant-1:project-1:conversation-current:conversation-target',
  );
});

test('comparison transcript keeps ordered user and assistant events without sharing source objects', () => {
  const source = [
    {
      id: 'user-1',
      type: 'user_message',
      eventTimeUs: 3_000,
      eventCounter: 1,
      content: 'Inspect the release.',
    },
    {
      id: 'thought-1',
      type: 'thought',
      eventTimeUs: 4_000,
      eventCounter: 2,
      content: 'Internal reasoning',
    },
    {
      id: 'assistant-1',
      type: 'assistant_message',
      eventTimeUs: 5_000,
      eventCounter: 3,
      content: 'Release verified.',
    },
  ];

  const messages = conversationComparisonMessages(source);
  assert.deepEqual(messages, [
    {
      id: 'user-1',
      role: 'user',
      content: 'Inspect the release.',
      timestampMs: 3,
    },
    {
      id: 'assistant-1',
      role: 'assistant',
      content: 'Release verified.',
      timestampMs: 5,
    },
  ]);
  source[0].content = 'Changed later';
  assert.equal(messages[0].content, 'Inspect the release.');
});

test('late comparison responses cannot replace the latest target or scope', () => {
  const scope = conversationComparisonScope(currentConversation, comparisonConversation);
  assert.equal(
    conversationComparisonRequestMatches({
      requestId: 7,
      currentRequestId: 7,
      expectedConversationId: 'conversation-target',
      responseConversationId: 'conversation-target',
      expectedScopeKey: conversationComparisonScopeKey(scope),
      currentScopeKey: conversationComparisonScopeKey(scope),
    }),
    true,
  );
  assert.equal(
    conversationComparisonRequestMatches({
      requestId: 6,
      currentRequestId: 7,
      expectedConversationId: 'conversation-target',
      responseConversationId: 'conversation-target',
      expectedScopeKey: conversationComparisonScopeKey(scope),
      currentScopeKey: conversationComparisonScopeKey(scope),
    }),
    false,
  );
  assert.equal(
    conversationComparisonRequestMatches({
      requestId: 7,
      currentRequestId: 7,
      expectedConversationId: 'conversation-target',
      responseConversationId: 'conversation-other',
      expectedScopeKey: conversationComparisonScopeKey(scope),
      currentScopeKey: conversationComparisonScopeKey(scope),
    }),
    false,
  );
});

test('Desktop comparison surface preserves Web behavior and native request boundaries', () => {
  assert.match(chatPanelSource, /<ConversationComparison/);
  assert.match(chatPanelSource, /<ConversationComparisonPicker/);
  assert.match(comparisonSource, /new AbortController\(\)/);
  assert.match(comparisonSource, /requestGenerationRef/);
  assert.match(comparisonSource, /getConversationMessages/);
  assert.match(comparisonSource, /listConversations/);
  assert.match(comparisonSource, /<Dialog\.Root/);
  assert.match(comparisonSource, /aria-label=\{t\('chat\.comparison\.search'\)\}/);
  assert.match(comparisonSource, /role="status"/);
  assert.match(comparisonSource, /role="alert"/);
  assert.match(comparisonSource, /\.focus\(\)/);
  assert.match(catalogSource, /getConversationMessages\?/);
  assert.match(catalogSource, /listConversations\?/);
  assert.match(chatStyles, /\.conversation-comparison/);
  assert.equal(i18nSource.match(/'chat\.comparison\.title':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.comparison\.search':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.comparison\.retry':/g)?.length, 2);
  assert.doesNotMatch(comparisonSource, /ipcRenderer|window\.desktop|window\.electron/);
});
