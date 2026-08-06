import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  ARTIFACT_CANVAS_SAVE_CAPABILITY,
  applyArtifactCanvasWorkspaceAuthorityContent,
  applyArtifactCanvasStreamEvent,
  artifactCanvasDownloadDescriptor,
  cancelArtifactCanvasTabClose,
  confirmArtifactCanvasTabClose,
  createArtifactCanvasWorkspace,
  editArtifactCanvasWorkspaceContent,
  emptyArtifactCanvasState,
  formatArtifactCanvasData,
  markArtifactCanvasWorkspaceSaved,
  redoArtifactCanvasWorkspaceContent,
  reconcileArtifactCanvasWorkspace,
  replayArtifactCanvasEvents,
  requestArtifactCanvasTabClose,
  selectArtifactCanvasTab,
  selectArtifactCanvasWorkspaceTab,
  setArtifactCanvasViewMode,
  toggleArtifactCanvasTabPin,
  undoArtifactCanvasWorkspaceContent,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/artifactCanvasEventModel.js',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentSource = readFileSync(
  new URL('../src/features/chat/LiveArtifactCanvas.tsx', import.meta.url),
  'utf8',
);
const qaSource = readFileSync(new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url), 'utf8');
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

function apply(state, event) {
  return applyArtifactCanvasStreamEvent(state, event);
}

test('artifact_open creates and activates a safe canvas tab from nested server data', () => {
  const result = apply(emptyArtifactCanvasState(), {
    type: 'agent_event',
    data: {
      event_type: 'artifact_open',
      data: {
        artifact_id: 'artifact-release-notes',
        title: 'release-notes.md',
        content: '# Release\nCloud sessions are ready.',
        content_type: 'markdown',
        language: 'markdown',
      },
    },
  });

  assert.equal(result.handled, true);
  assert.equal(result.action, 'open');
  assert.equal(result.state.activeArtifactId, 'artifact-release-notes');
  assert.equal(result.state.openRevision, 1);
  assert.deepEqual(result.state.tabs, [
    {
      id: 'artifact-release-notes',
      title: 'release-notes.md',
      content: '# Release\nCloud sessions are ready.',
      contentType: 'markdown',
      language: 'markdown',
    },
  ]);
});

test('artifact_update appends or replaces immutable tab state without duplicating tabs', () => {
  let state = apply(emptyArtifactCanvasState(), {
    type: 'artifact_open',
    data: { artifact_id: 'artifact-1', title: 'report.md', content: 'First' },
  }).state;

  state = apply(state, {
    type: 'artifact_update',
    data: { artifact_id: 'artifact-1', content: ' second', append: true },
  }).state;
  assert.equal(state.tabs[0].content, 'First second');

  state = apply(state, {
    type: 'artifact_update',
    data: { artifact_id: 'artifact-1', content: 'Replacement', append: false },
  }).state;
  assert.equal(state.tabs.length, 1);
  assert.equal(state.tabs[0].content, 'Replacement');
});

test('artifact tabs preserve user selection and closing the active tab chooses a stable fallback', () => {
  let state = emptyArtifactCanvasState();
  for (const id of ['artifact-1', 'artifact-2']) {
    state = apply(state, {
      type: 'artifact_open',
      data: { artifact_id: id, title: `${id}.txt`, content: id },
    }).state;
  }
  state = selectArtifactCanvasTab(state, 'artifact-1');
  assert.equal(state.activeArtifactId, 'artifact-1');

  const closed = apply(state, {
    type: 'artifact_close',
    data: { artifact_id: 'artifact-1' },
  });
  assert.equal(closed.action, 'close');
  assert.equal(closed.state.activeArtifactId, 'artifact-2');
  assert.deepEqual(closed.state.tabs.map((tab) => tab.id), ['artifact-2']);
});

test('artifact lifecycle protocol events are consumed even when malformed or stale', () => {
  const malformed = apply(emptyArtifactCanvasState(), { type: 'artifact_open', data: {} });
  assert.equal(malformed.handled, true);
  assert.equal(malformed.state.tabs.length, 0);

  const stale = apply(emptyArtifactCanvasState(), {
    type: 'artifact_update',
    data: { artifact_id: 'missing', content: 'ignored' },
  });
  assert.equal(stale.handled, true);
  assert.equal(stale.state.tabs.length, 0);

  assert.equal(
    apply(emptyArtifactCanvasState(), { type: 'assistant_message', data: {} }).handled,
    false,
  );
});

test('persisted artifact lifecycle events rebuild the latest canvas state in order', () => {
  const state = replayArtifactCanvasEvents([
    {
      type: 'artifact_open',
      payload: {
        artifact_id: 'artifact-release-notes',
        title: 'release-notes.md',
        content: '# Release',
        content_type: 'markdown',
        language: 'markdown',
      },
    },
    {
      type: 'artifact_open',
      payload: {
        artifact_id: 'artifact-checklist',
        title: 'checklist.txt',
        content: 'Verify cloud session',
      },
    },
    {
      type: 'artifact_update',
      payload: {
        artifact_id: 'artifact-release-notes',
        content: '\nDesktop Canvas restored.',
        append: true,
      },
    },
    {
      type: 'artifact_close',
      payload: { artifact_id: 'artifact-checklist' },
    },
  ]);

  assert.equal(state.activeArtifactId, 'artifact-release-notes');
  assert.equal(state.openRevision, 2);
  assert.deepEqual(state.tabs, [
    {
      id: 'artifact-release-notes',
      title: 'release-notes.md',
      content: '# Release\nDesktop Canvas restored.',
      contentType: 'markdown',
      language: 'markdown',
    },
  ]);
});

test('A2UI canvas_updated events open, incrementally update, and delete the same Canvas tab', () => {
  const begin = [
    JSON.stringify({
      beginRendering: { surfaceId: 'release-surface', root: 'release-root' },
    }),
    JSON.stringify({
      surfaceUpdate: {
        surfaceId: 'release-surface',
        components: [
          {
            id: 'release-root',
            component: { Text: { text: { literalString: 'Review release' } } },
          },
        ],
      },
    }),
  ].join('\n');
  const update = JSON.stringify({
    surfaceUpdate: {
      surfaceId: 'release-surface',
      components: [
        {
          id: 'release-root',
          component: { Text: { text: { literalString: 'Approve release' } } },
        },
      ],
    },
  });

  let state = apply(emptyArtifactCanvasState(), {
    type: 'canvas_updated',
    payload: {
      action: 'created',
      block_id: 'release-approval',
      block: {
        id: 'release-approval',
        block_type: 'a2ui_surface',
        title: 'Release approval',
        content: begin,
      },
    },
  }).state;
  assert.equal(state.tabs.length, 1);
  assert.deepEqual(state.tabs[0], {
    id: 'release-approval',
    title: 'Release approval',
    content: begin,
    contentType: 'a2ui_surface',
    language: null,
  });
  assert.equal(createArtifactCanvasWorkspace(state).tabs[0].viewMode, 'preview');

  const updated = apply(state, {
    type: 'canvas_updated',
    data: {
      action: 'updated',
      block_id: 'release-approval',
      block: {
        id: 'release-approval',
        block_type: 'a2ui_surface',
        title: 'Release approval',
        content: update,
      },
    },
  });
  assert.equal(updated.action, 'update');
  assert.equal(updated.state.tabs[0].content, `${begin}\n${update}`);
  state = updated.state;

  const deleted = apply(state, {
    type: 'canvas_updated',
    data: {
      action: 'deleted',
      block_id: 'release-approval',
      block: null,
    },
  });
  assert.equal(deleted.action, 'close');
  assert.deepEqual(deleted.state.tabs, []);
});

test('Canvas ignores non-A2UI blocks and fails closed on malformed A2UI updates', () => {
  const nonA2UI = apply(emptyArtifactCanvasState(), {
    type: 'canvas_updated',
    data: {
      action: 'created',
      block_id: 'markdown-block',
      block: {
        id: 'markdown-block',
        block_type: 'markdown',
        content: '# Not an A2UI surface',
      },
    },
  });
  assert.equal(nonA2UI.handled, false);

  const malformed = apply(emptyArtifactCanvasState(), {
    type: 'canvas_updated',
    data: {
      action: 'updated',
      block_id: 'missing',
      block: {
        id: 'missing',
        block_type: 'a2ui_surface',
        content: '',
      },
    },
  });
  assert.equal(malformed.handled, true);
  assert.equal(malformed.action, null);
  assert.deepEqual(malformed.state.tabs, []);
});

test('artifact workspace preserves multi-tab selection, pinning, and stable close fallback', () => {
  const source = {
    tabs: [
      {
        id: 'artifact-1',
        title: 'one.ts',
        content: 'one',
        contentType: 'code',
        language: 'typescript',
      },
      {
        id: 'artifact-2',
        title: 'two.md',
        content: '# Two',
        contentType: 'markdown',
        language: 'markdown',
      },
    ],
    activeArtifactId: 'artifact-2',
    openRevision: 2,
  };
  let workspace = createArtifactCanvasWorkspace(source);

  assert.equal(workspace.activeArtifactId, 'artifact-2');
  assert.deepEqual(
    workspace.tabs.map((tab) => [tab.id, tab.viewMode, tab.pinned, tab.dirty]),
    [
      ['artifact-1', 'code', false, false],
      ['artifact-2', 'markdown', false, false],
    ]
  );

  workspace = selectArtifactCanvasWorkspaceTab(workspace, 'artifact-1');
  workspace = toggleArtifactCanvasTabPin(workspace, 'artifact-1');
  assert.equal(workspace.activeArtifactId, 'artifact-1');
  assert.equal(workspace.tabs[0].pinned, true);
  assert.equal(requestArtifactCanvasTabClose(workspace, 'artifact-1').status, 'blocked_pinned');

  workspace = toggleArtifactCanvasTabPin(workspace, 'artifact-1');
  const closed = requestArtifactCanvasTabClose(workspace, 'artifact-1');
  assert.equal(closed.status, 'closed');
  assert.equal(closed.state.activeArtifactId, 'artifact-2');
  assert.deepEqual(closed.state.tabs.map((tab) => tab.id), ['artifact-2']);
});

test('dirty artifact close requires explicit discard and cancel preserves the draft', () => {
  const source = {
    tabs: [
      {
        id: 'artifact-1',
        title: 'draft.ts',
        content: 'const ready = false;',
        contentType: 'code',
        language: 'typescript',
      },
    ],
    activeArtifactId: 'artifact-1',
    openRevision: 1,
  };
  let workspace = createArtifactCanvasWorkspace(source);
  workspace = editArtifactCanvasWorkspaceContent(
    workspace,
    'artifact-1',
    'const ready = true;'
  );
  assert.equal(workspace.tabs[0].dirty, true);
  assert.equal(workspace.tabs[0].draftContent, 'const ready = true;');

  const requested = requestArtifactCanvasTabClose(workspace, 'artifact-1');
  assert.equal(requested.status, 'confirmation_required');
  assert.equal(requested.state.pendingCloseArtifactId, 'artifact-1');
  assert.equal(requested.state.tabs.length, 1);

  workspace = cancelArtifactCanvasTabClose(requested.state);
  assert.equal(workspace.pendingCloseArtifactId, null);
  assert.equal(workspace.tabs[0].draftContent, 'const ready = true;');

  workspace = confirmArtifactCanvasTabClose(
    requestArtifactCanvasTabClose(workspace, 'artifact-1').state
  );
  assert.equal(workspace.tabs.length, 0);
  assert.equal(workspace.activeArtifactId, null);
});

test('artifact workspace reconciles authoritative updates without overwriting dirty drafts', () => {
  const initial = {
    tabs: [
      {
        id: 'artifact-1',
        title: 'draft.ts',
        content: 'server v1',
        contentType: 'code',
        language: 'typescript',
      },
    ],
    activeArtifactId: 'artifact-1',
    openRevision: 1,
  };
  let workspace = editArtifactCanvasWorkspaceContent(
    createArtifactCanvasWorkspace(initial),
    'artifact-1',
    'local draft'
  );

  workspace = reconcileArtifactCanvasWorkspace(workspace, {
    ...initial,
    tabs: [
      { ...initial.tabs[0], content: 'server v2' },
      {
        id: 'artifact-2',
        title: 'report.json',
        content: '{"ok":true}',
        contentType: 'data',
        language: 'json',
      },
    ],
    activeArtifactId: 'artifact-2',
    openRevision: 2,
  });

  assert.equal(workspace.activeArtifactId, 'artifact-2');
  assert.equal(workspace.tabs[0].draftContent, 'local draft');
  assert.equal(workspace.tabs[0].sourceContent, 'server v2');
  assert.equal(workspace.tabs[0].dirty, true);
  assert.equal(workspace.tabs[1].viewMode, 'data');

  const dismissed = requestArtifactCanvasTabClose(workspace, 'artifact-2').state;
  const sameSource = reconcileArtifactCanvasWorkspace(dismissed, {
    ...initial,
    tabs: [initial.tabs[0], workspace.tabs[1]],
    activeArtifactId: 'artifact-1',
    openRevision: 2,
  });
  assert.deepEqual(sameSource.tabs.map((tab) => tab.id), ['artifact-1']);
});

test('artifact workspace keeps per-tab undo/redo history and commits saved authority', () => {
  const source = {
    tabs: [
      {
        id: 'artifact-history',
        title: 'history.md',
        content: 'server',
        contentType: 'markdown',
        language: 'markdown',
      },
    ],
    activeArtifactId: 'artifact-history',
    openRevision: 1,
  };
  let workspace = createArtifactCanvasWorkspace(source);
  workspace = editArtifactCanvasWorkspaceContent(workspace, 'artifact-history', 'draft one');
  workspace = editArtifactCanvasWorkspaceContent(workspace, 'artifact-history', 'draft two');
  assert.deepEqual(workspace.tabs[0].undoStack, ['server', 'draft one']);

  workspace = undoArtifactCanvasWorkspaceContent(workspace, 'artifact-history');
  assert.equal(workspace.tabs[0].draftContent, 'draft one');
  workspace = redoArtifactCanvasWorkspaceContent(workspace, 'artifact-history');
  assert.equal(workspace.tabs[0].draftContent, 'draft two');

  workspace = applyArtifactCanvasWorkspaceAuthorityContent(
    workspace,
    'artifact-history',
    'server v2',
    'text/markdown',
    true,
  );
  assert.equal(workspace.tabs[0].sourceContent, 'server v2');
  assert.equal(workspace.tabs[0].draftContent, 'draft two');
  assert.equal(workspace.tabs[0].dirty, true);

  workspace = markArtifactCanvasWorkspaceSaved(workspace, 'artifact-history');
  assert.equal(workspace.tabs[0].sourceContent, 'draft two');
  assert.equal(workspace.tabs[0].dirty, false);
});

test('artifact workspace keeps a dirty orphan when authority closes the source tab', () => {
  const initial = {
    tabs: [
      {
        id: 'artifact-dirty-orphan',
        title: 'draft.md',
        content: 'server draft',
        contentType: 'markdown',
        language: 'markdown',
      },
    ],
    activeArtifactId: 'artifact-dirty-orphan',
    openRevision: 1,
    openGenerations: { 'artifact-dirty-orphan': 1 },
  };
  const dirty = editArtifactCanvasWorkspaceContent(
    createArtifactCanvasWorkspace(initial),
    'artifact-dirty-orphan',
    'local unsaved draft',
  );

  const reconciled = reconcileArtifactCanvasWorkspace(dirty, {
    tabs: [],
    activeArtifactId: null,
    openRevision: 1,
    openGenerations: {},
  });

  assert.equal(reconciled.tabs.length, 1);
  assert.equal(reconciled.tabs[0].id, 'artifact-dirty-orphan');
  assert.equal(reconciled.tabs[0].draftContent, 'local unsaved draft');
  assert.equal(reconciled.tabs[0].dirty, true);
  assert.equal(reconciled.tabs[0].authorityState, 'closed');
  assert.equal(reconciled.activeArtifactId, 'artifact-dirty-orphan');
  assert.equal(
    requestArtifactCanvasTabClose(reconciled, 'artifact-dirty-orphan').status,
    'confirmation_required',
  );
});

test('artifact workspace reopens identical content for a new authority open generation', () => {
  let source = apply(emptyArtifactCanvasState(), {
    type: 'artifact_open',
    data: {
      artifact_id: 'artifact-reopened',
      title: 'same.md',
      content: 'identical content',
      content_type: 'markdown',
      language: 'markdown',
    },
  }).state;
  let workspace = createArtifactCanvasWorkspace(source);
  workspace = requestArtifactCanvasTabClose(workspace, 'artifact-reopened').state;

  workspace = reconcileArtifactCanvasWorkspace(workspace, source);
  assert.equal(workspace.tabs.length, 0);

  source = apply(source, {
    type: 'artifact_open',
    data: {
      artifact_id: 'artifact-reopened',
      title: 'same.md',
      content: 'identical content',
      content_type: 'markdown',
      language: 'markdown',
    },
  }).state;
  workspace = reconcileArtifactCanvasWorkspace(workspace, source);

  assert.equal(source.openGenerations['artifact-reopened'], 2);
  assert.equal(workspace.tabs.length, 1);
  assert.equal(workspace.tabs[0].id, 'artifact-reopened');
  assert.equal(workspace.tabs[0].authorityState, 'open');
});

test('artifact view modes, data formatting, download, and save authority remain deterministic', () => {
  const source = {
    tabs: [
      {
        id: 'artifact-data',
        title: '../unsafe:report.json',
        content: '{"ready":true,"count":2}',
        contentType: 'data',
        language: 'json',
      },
    ],
    activeArtifactId: 'artifact-data',
    openRevision: 1,
  };
  let workspace = createArtifactCanvasWorkspace(source);
  for (const mode of ['code', 'markdown', 'data', 'preview']) {
    workspace = setArtifactCanvasViewMode(workspace, 'artifact-data', mode);
    assert.equal(workspace.tabs[0].viewMode, mode);
  }

  assert.equal(
    formatArtifactCanvasData('{"ready":true,"count":2}'),
    '{\n  "ready": true,\n  "count": 2\n}'
  );
  assert.equal(formatArtifactCanvasData('not-json'), 'not-json');
  assert.deepEqual(artifactCanvasDownloadDescriptor(workspace.tabs[0]), {
    filename: 'unsafe_report.json',
    mimeType: 'application/json',
    content: '{"ready":true,"count":2}',
  });
  assert.deepEqual(ARTIFACT_CANVAS_SAVE_CAPABILITY, {
    available: true,
    contractVersion: 2,
  });
  assert.equal(Object.isFrozen(ARTIFACT_CANVAS_SAVE_CAPABILITY), true);
});

test('Desktop folds artifact canvas events out of the timeline and exposes Browser QA', () => {
  assert.match(appSource, /applyArtifactCanvasStreamEvent\(emptyArtifactCanvasState\(\), event\)/);
  assert.match(appSource, /artifactCanvasResult\.handled[\s\S]*return existing/);
  assert.match(appSource, /setReviewTab\('artifacts'\)/);
  assert.match(appSource, /replayArtifactCanvasEvents\(responseItems\)/);
  assert.match(componentSource, /aria-label=\{t\('artifact\.liveCanvas'\)\}/);
  assert.doesNotMatch(componentSource, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(componentSource, /<iframe|srcDoc=|window\.open|location\.href/);
  assert.match(componentSource, /role="alertdialog"/);
  assert.match(componentSource, /role="radiogroup"/);
  assert.match(componentSource, /navigator\.clipboard\.writeText/);
  assert.match(componentSource, /saveBlobWithDesktopDialog/);
  assert.doesNotMatch(componentSource, /URL\.createObjectURL|createElement\('a'\)/);
  assert.match(componentSource, /createArtifactSaveCommandV2/);
  assert.match(componentSource, /ArtifactPreviewSurface/);
  assert.match(componentSource, /event\.metaKey \|\| event\.ctrlKey/);
  assert.match(qaSource, /artifact-canvas-events/);
  assert.match(qaSource, /Cloud session release notes/);
});

test('artifact workspace controls are localized in both dictionaries', () => {
  const keys = [
    'artifact.pinTab',
    'artifact.unpinTab',
    'artifact.closeTab',
    'artifact.unsavedTitle',
    'artifact.unsavedDescription',
    'artifact.discardChanges',
    'artifact.viewModeGroup',
    'artifact.viewMode.code',
    'artifact.viewMode.markdown',
    'artifact.viewMode.data',
    'artifact.viewMode.preview',
    'artifact.copy',
    'artifact.download',
    'artifact.save',
    'artifact.saveUnavailable',
    'artifact.undo',
    'artifact.redo',
    'artifact.saveConflict',
    'artifact.reloadServer',
    'artifact.saveCopy',
    'artifact.copyDraft',
  ];
  for (const key of keys) {
    const occurrences = i18nSource.split(`'${key}':`).length - 1;
    assert.ok(occurrences >= 2, `${key} must exist in enUS and zhCN (found ${occurrences})`);
  }
});
