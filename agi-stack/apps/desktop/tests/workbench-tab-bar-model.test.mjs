import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  WORKBENCH_VIEW_TAB_ORDER,
  clearConversationTabs,
  closeTab,
  ensureConversationTab,
  ensureViewTab,
  isSameTab,
  removeTab,
  tabKey,
} = require('/tmp/agistack-desktop-test-dist/src/features/chrome/workbenchTabBarModel.js');

const viewTab = (section) => ({ kind: 'view', section });
const conversationTab = (id, title = `Session ${id}`) => ({
  kind: 'conversation',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  conversationId: id,
  title,
});

test('tabKey distinguishes view and conversation tabs', () => {
  assert.equal(tabKey(viewTab('board')), 'view:board');
  assert.equal(tabKey(conversationTab('c-1')), 'conversation:c-1');
  assert.ok(isSameTab(viewTab('board'), viewTab('board')));
  assert.ok(!isSameTab(viewTab('board'), viewTab('search')));
  assert.ok(!isSameTab(viewTab('board'), conversationTab('board')));
});

test('ensureViewTab dedupes by section and keeps the declaration order', () => {
  let tabs = [];
  tabs = ensureViewTab(tabs, 'search');
  tabs = ensureViewTab(tabs, 'workspace');
  tabs = ensureViewTab(tabs, 'board');
  assert.deepEqual(
    tabs.map((tab) => tab.section),
    ['workspace', 'board', 'search'],
  );
  const again = ensureViewTab(tabs, 'board');
  assert.deepEqual(again.map(tabKey), tabs.map(tabKey));
  // Views stay ahead of conversation tabs.
  tabs = ensureConversationTab(tabs, conversationTab('c-1'));
  tabs = ensureViewTab(tabs, 'activity');
  assert.deepEqual(
    tabs.map(tabKey),
    ['view:workspace', 'view:board', 'view:search', 'view:activity', 'conversation:c-1'],
  );
});

test('view tab order covers exactly the navigable sections', () => {
  assert.deepEqual(WORKBENCH_VIEW_TAB_ORDER, [
    'workspace',
    'home',
    'board',
    'automations',
    'search',
    'activity',
  ]);
});

test('ensureConversationTab dedupes, appends in open order, refreshes titles', () => {
  let tabs = [viewTab('workspace')];
  tabs = ensureConversationTab(tabs, conversationTab('c-1'));
  tabs = ensureConversationTab(tabs, conversationTab('c-2'));
  tabs = ensureConversationTab(tabs, conversationTab('c-1'));
  assert.deepEqual(
    tabs.map(tabKey),
    ['view:workspace', 'conversation:c-1', 'conversation:c-2'],
  );
  const renamed = ensureConversationTab(tabs, conversationTab('c-1', 'Renamed'));
  assert.equal(renamed[1].title, 'Renamed');
  assert.deepEqual(renamed.map(tabKey), tabs.map(tabKey));
});

test('closeTab on an inactive tab only removes it', () => {
  const tabs = [viewTab('workspace'), conversationTab('c-1'), conversationTab('c-2')];
  const result = closeTab(tabs, conversationTab('c-1'), 'conversation:c-2');
  assert.deepEqual(result.tabs.map(tabKey), ['view:workspace', 'conversation:c-2']);
  assert.equal(result.fallback, null);
});

test('closeTab on the active tab prefers the right neighbor, then the left', () => {
  const tabs = [viewTab('workspace'), conversationTab('c-1'), conversationTab('c-2')];
  const right = closeTab(tabs, conversationTab('c-1'), 'conversation:c-1');
  assert.deepEqual(right.fallback, conversationTab('c-2'));
  const left = closeTab(tabs, conversationTab('c-2'), 'conversation:c-2');
  assert.deepEqual(left.fallback, conversationTab('c-1'));
});

test('closeTab on the last tab falls back to the workspace view', () => {
  const result = closeTab([conversationTab('c-1')], conversationTab('c-1'), 'conversation:c-1');
  assert.deepEqual(result.tabs, []);
  assert.deepEqual(result.fallback, { kind: 'view', section: 'workspace' });
});

test('closeTab ignores unknown tabs', () => {
  const tabs = [viewTab('workspace')];
  const result = closeTab(tabs, conversationTab('missing'), 'view:workspace');
  assert.deepEqual(result.tabs.map(tabKey), ['view:workspace']);
  assert.equal(result.fallback, null);
});

test('clearConversationTabs keeps view tabs only', () => {
  const tabs = [viewTab('workspace'), conversationTab('c-1'), viewTab('board')];
  assert.deepEqual(
    clearConversationTabs(tabs).map(tabKey),
    ['view:workspace', 'view:board'],
  );
  assert.deepEqual(removeTab(tabs, viewTab('board')).map(tabKey), [
    'view:workspace',
    'conversation:c-1',
  ]);
});
