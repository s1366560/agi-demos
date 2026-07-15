import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  nextSessionSurface,
  sessionInspectorSurfaceIds,
  sessionSurfaceForSession,
  sessionSurfacePanes,
  transitionSessionSurface,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionLayoutModel.js');

test('conversation-first layout keeps a full-width thread until a canvas is requested', () => {
  assert.deepEqual(sessionSurfacePanes('conversation', false), {
    thread: true,
    canvas: false,
  });
  assert.deepEqual(sessionSurfacePanes('conversation', true), {
    thread: true,
    canvas: false,
  });
});

test('opening a canvas creates the only split layout', () => {
  const surface = nextSessionSurface('conversation', 'open_canvas');

  assert.equal(surface, 'split');
  assert.deepEqual(sessionSurfacePanes(surface, true), {
    thread: true,
    canvas: true,
  });
});

test('focus and close transitions preserve the conversation-first return path', () => {
  assert.deepEqual(sessionSurfacePanes(nextSessionSurface('split', 'focus_canvas'), true), {
    thread: false,
    canvas: true,
  });
  assert.equal(nextSessionSurface('canvas', 'close_canvas'), 'conversation');
  assert.equal(nextSessionSurface('split', 'select_session'), 'conversation');
});

test('canvas layouts fail closed when no canvas payload exists', () => {
  assert.deepEqual(sessionSurfacePanes('split', false), {
    thread: true,
    canvas: false,
  });
  assert.deepEqual(sessionSurfacePanes('canvas', false), {
    thread: true,
    canvas: false,
  });
});

test('the retired passive inspector is not part of the layout contract', () => {
  assert.equal(sessionInspectorSurfaceIds, undefined);
});

test('a newly selected session renders conversation before any effect can run', () => {
  const previousSession = { sessionId: 'conversation-a', surface: 'canvas' };

  assert.equal(sessionSurfaceForSession(previousSession, 'conversation-b'), 'conversation');
  assert.deepEqual(transitionSessionSurface(previousSession, 'conversation-b', 'open_canvas'), {
    sessionId: 'conversation-b',
    surface: 'split',
  });
});
