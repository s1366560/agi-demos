import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { nextSessionSurface, sessionInspectorSurfaceIds, sessionSurfacePanes } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionLayoutModel.js'
);

test('conversation-first layout keeps the thread and contextual inspector visible', () => {
  assert.deepEqual(sessionSurfacePanes('conversation', false), {
    thread: true,
    inspector: true,
    canvas: false,
  });
  assert.deepEqual(sessionSurfacePanes('conversation', true), {
    thread: true,
    inspector: true,
    canvas: false,
  });
});

test('opening a canvas replaces the inspector without creating a third permanent pane', () => {
  const surface = nextSessionSurface('conversation', 'open_canvas');

  assert.equal(surface, 'split');
  assert.deepEqual(sessionSurfacePanes(surface, true), {
    thread: true,
    inspector: false,
    canvas: true,
  });
});

test('focus and close transitions preserve the conversation-first return path', () => {
  assert.deepEqual(sessionSurfacePanes(nextSessionSurface('split', 'focus_canvas'), true), {
    thread: false,
    inspector: false,
    canvas: true,
  });
  assert.equal(nextSessionSurface('canvas', 'close_canvas'), 'conversation');
  assert.equal(nextSessionSurface('split', 'select_session'), 'conversation');
});

test('canvas layouts fail closed when no canvas payload exists', () => {
  assert.deepEqual(sessionSurfacePanes('split', false), {
    thread: true,
    inspector: true,
    canvas: false,
  });
  assert.deepEqual(sessionSurfacePanes('canvas', false), {
    thread: true,
    inspector: true,
    canvas: false,
  });
});

test('inspector surfaces follow the explicit Work or Code capability', () => {
  assert.deepEqual(sessionInspectorSurfaceIds('code'), ['plan', 'changes', 'checks']);
  assert.deepEqual(sessionInspectorSurfaceIds('work'), [
    'plan',
    'artifacts',
    'verification',
  ]);
  assert.deepEqual(sessionInspectorSurfaceIds('unavailable'), [
    'plan',
    'artifacts',
    'activity',
  ]);
});
