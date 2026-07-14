import assert from 'node:assert/strict';
import test from 'node:test';

import {
  chatComposerPresentation,
} from '/tmp/agistack-desktop-test-dist/src/features/chat/chatComposerModel.js';

test('session composer keeps only conversation steering affordances', () => {
  assert.deepEqual(chatComposerPresentation('session'), {
    placeholderKey: 'session.steerComposerPlaceholder',
    showCommands: false,
    showRuntimeControls: false,
    showRuntimeStatus: false,
    showWorkflowStrip: false,
    showPaneHeader: false,
    showQueueHandoff: false,
  });
});

test('workspace composer retains workspace navigation and runtime affordances', () => {
  assert.deepEqual(chatComposerPresentation('workspace'), {
    placeholderKey: null,
    showCommands: true,
    showRuntimeControls: true,
    showRuntimeStatus: true,
    showWorkflowStrip: true,
    showPaneHeader: true,
    showQueueHandoff: true,
  });
});
