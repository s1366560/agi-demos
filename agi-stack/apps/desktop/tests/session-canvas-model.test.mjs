import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { defaultSessionCanvasTab, hasAuthoritativeChangeReview, sessionCanvasTabs } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionCanvasModel.js'
);

test('standalone Code workspace drawer keeps its complete review inventory', () => {
  assert.deepEqual(
    sessionCanvasTabs('code').primary.map((tab) => tab.id),
    ['overview', 'plan', 'changes', 'terminal', 'checks']
  );
  assert.deepEqual(
    sessionCanvasTabs('code').secondary.map((tab) => tab.id),
    ['activity', 'artifacts']
  );
});

test('standalone Work workspace drawer keeps artifacts, sources, verification, and activity', () => {
  const tabs = sessionCanvasTabs('work');
  assert.deepEqual(
    tabs.primary.map((tab) => tab.id),
    ['overview', 'plan', 'artifacts', 'sources', 'verification']
  );
  assert.deepEqual(
    tabs.secondary.map((tab) => tab.id),
    ['activity']
  );
  assert.equal(tabs.primary.some((tab) => tab.id === 'terminal'), false);
});

test('standalone unclassified workspace drawer keeps its shared review inventory', () => {
  const tabs = sessionCanvasTabs('unavailable');
  assert.deepEqual(
    tabs.primary.map((tab) => tab.id),
    ['overview', 'plan', 'activity', 'artifacts']
  );
});

test('session Code canvas removes production-only Activity and Artifacts tabs', () => {
  const tabs = sessionCanvasTabs('code', 'session');

  assert.deepEqual(
    tabs.primary.map((tab) => tab.id),
    ['overview', 'plan', 'changes', 'terminal', 'checks']
  );
  assert.deepEqual(tabs.secondary, []);
});

test('session Work canvas keeps Artifact but removes production-only Activity', () => {
  const tabs = sessionCanvasTabs('work', 'session');

  assert.deepEqual(
    tabs.primary.map((tab) => tab.id),
    ['overview', 'plan', 'artifacts', 'sources', 'verification']
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
