import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { workspaceReviewPanelChrome } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/workspaceReviewPanelModel.js'
);

test('session canvas uses one tab bar without workspace drawer chrome', () => {
  assert.deepEqual(workspaceReviewPanelChrome(true), {
    showHeader: false,
    showOverflowMenus: false,
    showPanelModeActions: false,
    showSessionLayoutActions: true,
  });
});

test('session canvas can omit layout actions until the host supplies controls', () => {
  assert.equal(workspaceReviewPanelChrome(false).showSessionLayoutActions, false);
});
