import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  defaultSessionCanvasTab,
  hasAuthoritativeChangeReview,
  sessionCanvasTabs,
  shouldShowSessionCanvas,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionCanvasModel.js');

test('only a selected conversation can open the Thread and Canvas split', () => {
  const base = { authenticated: true, canvasOpen: true, sessionSelected: true };

  assert.equal(shouldShowSessionCanvas({ ...base, surface: 'conversation' }), true);
  assert.equal(shouldShowSessionCanvas({ ...base, surface: 'workspace' }), false);
  assert.equal(shouldShowSessionCanvas({ ...base, surface: 'other' }), false);
  assert.equal(
    shouldShowSessionCanvas({ ...base, surface: 'conversation', sessionSelected: false }),
    false
  );
  assert.equal(
    shouldShowSessionCanvas({ ...base, surface: 'conversation', canvasOpen: false }),
    false
  );
  assert.equal(
    shouldShowSessionCanvas({ ...base, surface: 'conversation', authenticated: false }),
    false
  );
});

test('Code conversation canvas exposes only the approved session surfaces', () => {
  assert.deepEqual(
    sessionCanvasTabs('code').primary.map((tab) => tab.id),
    ['overview', 'plan', 'changes', 'terminal', 'checks']
  );
  assert.deepEqual(sessionCanvasTabs('code').secondary, []);
});

test('Work conversation canvas exposes artifact, source, and verification surfaces', () => {
  const tabs = sessionCanvasTabs('work');
  assert.deepEqual(
    tabs.primary.map((tab) => tab.id),
    ['overview', 'plan', 'artifacts', 'sources', 'verification']
  );
  assert.deepEqual(tabs.secondary, []);
  assert.equal(tabs.primary.some((tab) => tab.id === 'terminal'), false);
});

test('unclassified conversation canvas fails closed to common evidence surfaces', () => {
  const tabs = sessionCanvasTabs('unavailable');
  assert.deepEqual(
    tabs.primary.map((tab) => tab.id),
    ['overview', 'plan', 'artifacts']
  );
  assert.deepEqual(tabs.secondary, []);
});

test('session canvas defaults to Plan for attention, then the mode-specific work surface', () => {
  assert.equal(defaultSessionCanvasTab('needs_input', 'code'), 'plan');
  assert.equal(defaultSessionCanvasTab('needs_approval', 'work'), 'plan');
  assert.equal(defaultSessionCanvasTab('running', 'code'), 'changes');
  assert.equal(defaultSessionCanvasTab('running', 'work'), 'artifacts');
  assert.equal(defaultSessionCanvasTab('running', 'unavailable'), 'plan');
});

test('Changes review stays empty until the backend supplies change or HITL evidence', () => {
  assert.equal(
    hasAuthoritativeChangeReview({ changedFileCount: 0, hasPendingHitlRequest: false }),
    false
  );
  assert.equal(
    hasAuthoritativeChangeReview({ changedFileCount: 0, hasPendingHitlRequest: true }),
    true
  );
  assert.equal(
    hasAuthoritativeChangeReview({ changedFileCount: 1, hasPendingHitlRequest: false }),
    true
  );
});
