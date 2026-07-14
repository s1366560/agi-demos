import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { visibleWorkspaceReviewTabs, workspaceReviewPanelChrome } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/workspaceReviewPanelModel.js'
);

const primary = ['overview', 'plan', 'changes', 'terminal', 'checks'].map((tab) => ({ tab }));
const secondary = ['activity', 'artifacts'].map((tab) => ({ tab }));

test('session canvas uses one tab bar without workspace drawer chrome', () => {
  assert.deepEqual(workspaceReviewPanelChrome('session', true), {
    showHeader: false,
    showOverflowMenus: false,
    showPanelModeActions: false,
    showSessionLayoutActions: true,
  });
  assert.deepEqual(
    visibleWorkspaceReviewTabs('session', primary, secondary, 'overview').map(({ tab }) => tab),
    ['overview', 'plan', 'changes', 'terminal', 'checks', 'activity', 'artifacts']
  );
});

test('session canvas can omit layout actions until the host supplies controls', () => {
  assert.equal(workspaceReviewPanelChrome('session', false).showSessionLayoutActions, false);
});

test('standalone workspace drawer preserves its compact overflow behavior', () => {
  assert.deepEqual(workspaceReviewPanelChrome('workspace', false), {
    showHeader: true,
    showOverflowMenus: true,
    showPanelModeActions: true,
    showSessionLayoutActions: false,
  });
  assert.deepEqual(
    visibleWorkspaceReviewTabs('workspace', primary, secondary, 'artifacts').map(({ tab }) => tab),
    ['overview', 'plan', 'changes', 'artifacts']
  );
});
