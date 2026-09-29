import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  emptyArtifactCanvasState,
  createArtifactCanvasWorkspace,
  reconcileArtifactCanvasWorkspace,
  requestArtifactCanvasTabClose,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/artifactCanvasEventModel.js');
const {
  LOCAL_SNIPPET_TAB_ID_PREFIX,
  isLocalSnippetCanvasTab,
  openSnippetCanvasTab,
  publishSnippetCanvasRequest,
  snippetCanvasTabId,
  subscribeSnippetCanvasRequests,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/snippetCanvasModel.js');

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const highlightedCodeSource = readFileSync(
  new URL('../src/features/chat/HighlightedCode.tsx', import.meta.url),
  'utf8',
);
const liveArtifactCanvasSource = readFileSync(
  new URL('../src/features/chat/LiveArtifactCanvas.tsx', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

function streamOpenedState() {
  // Simulate a canvas that already hosts a backend artifact tab.
  return {
    tabs: [
      {
        id: 'artifact-1',
        title: 'server.ts',
        content: 'export {};',
        contentType: 'code',
        language: 'typescript',
      },
    ],
    activeArtifactId: 'artifact-1',
    openRevision: 1,
    openGenerations: { 'artifact-1': 1 },
  };
}

test('opening a snippet adds an active local scratch tab with the snippet content', () => {
  const result = openSnippetCanvasTab(
    streamOpenedState(),
    { code: 'const x = 1;\nconsole.log(x);', language: 'typescript', title: 'typescript snippet' },
    1,
  );

  assert.equal(result.tabId, snippetCanvasTabId(1));
  assert.ok(result.tabId.startsWith(LOCAL_SNIPPET_TAB_ID_PREFIX));
  const tab = result.state.tabs.find((candidate) => candidate.id === result.tabId);
  assert.equal(tab.content, 'const x = 1;\nconsole.log(x);');
  assert.equal(tab.language, 'typescript');
  assert.equal(tab.contentType, 'code');
  assert.equal(tab.local, true, 'scratch tab must be flagged local, never artifact-backed');
  assert.equal(result.state.activeArtifactId, result.tabId);
  // Existing backend tabs are preserved untouched.
  assert.ok(result.state.tabs.some((candidate) => candidate.id === 'artifact-1'));
});

test('empty or whitespace snippets never open a tab', () => {
  const state = emptyArtifactCanvasState();
  for (const code of ['', '   ', '\n\t ']) {
    const result = openSnippetCanvasTab(state, { code, language: 'python' }, 1);
    assert.equal(result.tabId, null);
    assert.equal(result.state, state);
  }
});

test('snippet tab ids are unique per open and a missing title falls back to the language', () => {
  let state = emptyArtifactCanvasState();
  const first = openSnippetCanvasTab(state, { code: 'a', language: 'rust' }, 1);
  state = first.state;
  const second = openSnippetCanvasTab(state, { code: 'b', language: 'go' }, 2);
  assert.notEqual(first.tabId, second.tabId);
  assert.equal(second.state.tabs.length, 2);
  const titles = second.state.tabs.map((tab) => tab.title).sort();
  assert.deepEqual(titles, ['go snippet', 'rust snippet']);
});

test('local scratch tabs survive canvas reconcile and close without a dirty confirmation', () => {
  const { state } = openSnippetCanvasTab(
    streamOpenedState(),
    { code: 'SELECT 1;', language: 'sql' },
    7,
  );
  const workspace = reconcileArtifactCanvasWorkspace(createArtifactCanvasWorkspace(state), state);
  const scratch = workspace.tabs.find((tab) => tab.id === snippetCanvasTabId(7));
  assert.ok(scratch, 'scratch tab must survive reconciliation');
  assert.equal(scratch.local, true, 'local flag must flow into the workspace tab');
  assert.equal(scratch.dirty, false);

  const close = requestArtifactCanvasTabClose(workspace, scratch.id);
  assert.equal(close.status, 'closed', 'pristine scratch tab closes without confirmation');
  assert.ok(!close.state.tabs.some((tab) => tab.id === scratch.id));
});

test('stream events cannot collide with or hijack local scratch tabs', () => {
  const { applyArtifactCanvasStreamEvent } = require(
    '/tmp/agistack-desktop-test-dist/src/features/chat/artifactCanvasEventModel.js'
  );
  const { state } = openSnippetCanvasTab(
    emptyArtifactCanvasState(),
    { code: 'local()', language: 'python' },
    3,
  );
  const afterClose = applyArtifactCanvasStreamEvent(state, {
    type: 'artifact_close',
    data: { artifact_id: snippetCanvasTabId(3) },
  });
  // artifact_close events only target real artifacts; the scratch tab id is
  // client-only, but even a matching close removes just that tab honestly.
  assert.equal(afterClose.handled, true);
  assert.equal(afterClose.state.tabs.length, 0);
  // An update for a non-existent id never recreates a scratch tab.
  const afterUpdate = applyArtifactCanvasStreamEvent(state, {
    type: 'artifact_update',
    data: { artifact_id: 'artifact-ghost', content: 'ghost' },
  });
  assert.equal(afterUpdate.state.tabs.length, 1);
});

test('the request channel delivers published snippets to subscribers exactly once', () => {
  const received = [];
  const unsubscribe = subscribeSnippetCanvasRequests((request) => received.push(request));
  const delivered = publishSnippetCanvasRequest({ code: 'x = 1', language: 'python' });
  assert.equal(delivered, true);
  assert.deepEqual(received, [{ code: 'x = 1', language: 'python' }]);
  unsubscribe();
  assert.equal(
    publishSnippetCanvasRequest({ code: 'y = 2', language: 'python' }),
    false,
    'no subscribers → publish reports not delivered',
  );
  assert.equal(received.length, 1);
});

test('the channel rejects empty snippets instead of opening blank tabs', () => {
  const received = [];
  const unsubscribe = subscribeSnippetCanvasRequests((request) => received.push(request));
  assert.equal(publishSnippetCanvasRequest({ code: '  ', language: 'python' }), false);
  assert.equal(received.length, 0);
  unsubscribe();
});

test('click → canvas tab: a published snippet flows through the App wiring into the canvas state', () => {
  // Reproduce the App subscriber wiring (subscribeSnippetCanvasRequests +
  // openSnippetCanvasTab) and drive it with a code-block publish.
  let state = emptyArtifactCanvasState();
  let sequence = 0;
  const unsubscribe = subscribeSnippetCanvasRequests((request) => {
    sequence += 1;
    state = openSnippetCanvasTab(state, request, sequence).state;
  });
  const delivered = publishSnippetCanvasRequest({
    code: 'print("hi")',
    language: 'python',
    title: 'python 代码片段',
  });
  unsubscribe();

  assert.equal(delivered, true);
  assert.equal(state.tabs.length, 1);
  assert.equal(state.tabs[0].content, 'print("hi")');
  assert.equal(state.tabs[0].language, 'python');
  assert.equal(state.tabs[0].title, 'python 代码片段');
  assert.equal(state.tabs[0].local, true);
  assert.equal(state.activeArtifactId, state.tabs[0].id);
});

test('isLocalSnippetCanvasTab recognises flagged and prefix-matched tabs only', () => {
  assert.equal(isLocalSnippetCanvasTab({ id: snippetCanvasTabId(2) }), true);
  assert.equal(isLocalSnippetCanvasTab({ id: 'artifact-1', local: true }), true);
  assert.equal(isLocalSnippetCanvasTab({ id: 'artifact-1' }), false);
  assert.equal(isLocalSnippetCanvasTab({ id: 'local-snippetish' }), false);
});

test('code blocks publish snippet canvas requests and App subscribes to open scratch tabs', () => {
  assert.match(highlightedCodeSource, /publishSnippetCanvasRequest/);
  assert.match(highlightedCodeSource, /chat\.openInCanvas/);
  assert.match(highlightedCodeSource, /code-block-open-canvas/);
  assert.match(appSource, /subscribeSnippetCanvasRequests/);
  assert.match(appSource, /openSnippetCanvasTab/);
  assert.match(appSource, /openRightCanvasPanel\('artifacts'\)/);
});

test('the canvas surface never treats a local scratch tab as a persisted artifact', () => {
  // Authority load, server download, and preview fetches are all gated off for
  // local tabs; the save tooltip explains scratch tabs cannot be persisted.
  assert.match(liveArtifactCanvasSource, /activeIsLocal/);
  assert.match(liveArtifactCanvasSource, /artifactClient && !active\.local/);
  assert.match(liveArtifactCanvasSource, /artifact\.localSaveUnavailable/);
  assert.match(liveArtifactCanvasSource, /artifact\.localBadge/);
  assert.match(liveArtifactCanvasSource, /artifact\.localCanvasDescription/);
});

test('snippet canvas i18n keys exist in both dictionaries', () => {
  const keys = [
    'chat.openInCanvas',
    'chat.openInCanvasHint',
    'chat.canvasSnippetTitle',
    'chat.openInCanvasUnavailable',
    'artifact.localBadge',
    'artifact.localCanvasDescription',
    'artifact.localSaveUnavailable',
  ];
  for (const key of keys) {
    assert.equal(
      (i18nSource.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) ?? []).length,
      2,
      `${key} must exist in both the English and Chinese dictionaries`,
    );
  }
});
