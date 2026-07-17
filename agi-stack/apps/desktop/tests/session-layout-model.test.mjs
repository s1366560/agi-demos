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

test('conversation-first layout keeps the narrative thread beside its context rail', () => {
  assert.deepEqual(sessionSurfacePanes('conversation', false), {
    thread: true,
    canvas: false,
    contextRail: true,
  });
  assert.deepEqual(sessionSurfacePanes('conversation', true), {
    thread: true,
    canvas: false,
    contextRail: true,
  });
});

test('opening a canvas creates the only split layout', () => {
  const surface = nextSessionSurface('conversation', 'open_canvas');

  assert.equal(surface, 'split');
  assert.deepEqual(sessionSurfacePanes(surface, true), {
    thread: true,
    canvas: true,
    contextRail: false,
  });
});

test('focus and close transitions preserve the conversation-first return path', () => {
  assert.deepEqual(sessionSurfacePanes(nextSessionSurface('split', 'focus_canvas'), true), {
    thread: false,
    canvas: true,
    contextRail: false,
  });
  assert.equal(nextSessionSurface('canvas', 'close_canvas'), 'conversation');
  assert.equal(nextSessionSurface('split', 'select_session'), 'conversation');
});

test('canvas layouts fail closed when no canvas payload exists', () => {
  assert.deepEqual(sessionSurfacePanes('split', false), {
    thread: true,
    canvas: false,
    contextRail: true,
  });
  assert.deepEqual(sessionSurfacePanes('canvas', false), {
    thread: true,
    canvas: false,
    contextRail: true,
  });
});

test('the context rail is a conversation surface, never a second authority source', () => {
  assert.equal(sessionInspectorSurfaceIds, undefined);
  assert.equal(sessionSurfacePanes('conversation', true).contextRail, true);
  assert.equal(sessionSurfacePanes('split', true).contextRail, false);
});

test('a newly selected session renders conversation before any effect can run', () => {
  const previousSession = { sessionId: 'conversation-a', surface: 'canvas' };

  assert.equal(sessionSurfaceForSession(previousSession, 'conversation-b'), 'conversation');
  assert.deepEqual(transitionSessionSurface(previousSession, 'conversation-b', 'open_canvas'), {
    sessionId: 'conversation-b',
    surface: 'split',
  });
});
