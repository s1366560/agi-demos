import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  applyArtifactCanvasStreamEvent,
  emptyArtifactCanvasState,
  selectArtifactCanvasTab,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/artifactCanvasEventModel.js',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const componentSource = readFileSync(
  new URL('../src/features/chat/LiveArtifactCanvas.tsx', import.meta.url),
  'utf8',
);
const qaSource = readFileSync(new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url), 'utf8');

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

test('Desktop folds artifact canvas events out of the timeline and exposes Browser QA', () => {
  assert.match(appSource, /applyArtifactCanvasStreamEvent\(emptyArtifactCanvasState\(\), event\)/);
  assert.match(appSource, /artifactCanvasResult\.handled[\s\S]*return existing/);
  assert.match(appSource, /setReviewTab\('artifacts'\)/);
  assert.match(componentSource, /aria-label=\{t\('artifact\.liveCanvas'\)\}/);
  assert.doesNotMatch(componentSource, /dangerouslySetInnerHTML/);
  assert.match(qaSource, /artifact-canvas-events/);
  assert.match(qaSource, /Cloud session release notes/);
});
