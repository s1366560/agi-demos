import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  chatComposerPresentation,
} from '/tmp/agistack-desktop-test-dist/src/features/chat/chatComposerModel.js';

const chatPanelSource = readFileSync(
  new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
  'utf8',
);
const composerControlsSource = readFileSync(
  new URL('../src/features/chat/ComposerControls.tsx', import.meta.url),
  'utf8',
);

test('session composer keeps run-scoped steering and queue handoff affordances', () => {
  assert.deepEqual(chatComposerPresentation('session'), {
    placeholderKey: 'session.steerComposerPlaceholder',
    showCommands: false,
    showRuntimeControls: false,
    showRuntimeStatus: false,
    showWorkflowStrip: false,
    showPaneHeader: false,
    showQueueHandoff: true,
  });
});

test('workspace composer omits run-scoped queue handoff without a selected session', () => {
  assert.deepEqual(chatComposerPresentation('workspace'), {
    placeholderKey: null,
    showCommands: true,
    showRuntimeControls: true,
    showRuntimeStatus: true,
    showWorkflowStrip: true,
    showPaneHeader: true,
    showQueueHandoff: false,
  });
});

test('session and workspace composers expose a controlled model switch backed by real options', () => {
  assert.match(chatPanelSource, /modelOptions\?: readonly ComposerModelOption\[\]/);
  assert.match(chatPanelSource, /selectedModelValue\?: string \| null/);
  assert.match(chatPanelSource, /onModelChange\?: \(value: string\) => Promise<void>/);
  assert.match(
    chatPanelSource,
    /composerVariant === 'session'[\s\S]*?<ComposerControls[\s\S]*?onModelChange=\{onModelChange\}/,
  );
  assert.match(composerControlsSource, /role="listbox"/);
  assert.match(composerControlsSource, /type="search"/);
  assert.doesNotMatch(composerControlsSource, /Workspace model|Cloud model/);
});
