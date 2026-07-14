import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { hasAuthoritativeChangeReview, sessionCanvasTabs } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionCanvasModel.js'
);

test('Code sessions expose the programming evidence surfaces first', () => {
  assert.deepEqual(
    sessionCanvasTabs('code').primary.map((tab) => tab.id),
    ['overview', 'plan', 'changes', 'terminal', 'checks']
  );
});

test('Work sessions expose artifacts, sources, and verification without code-only controls', () => {
  const tabs = sessionCanvasTabs('work');
  assert.deepEqual(
    tabs.primary.map((tab) => tab.id),
    ['overview', 'plan', 'artifacts', 'sources', 'verification']
  );
  assert.equal(tabs.primary.some((tab) => tab.id === 'terminal'), false);
});

test('Unclassified sessions keep only shared evidence surfaces until the mode is explicit', () => {
  const tabs = sessionCanvasTabs('unavailable');
  assert.deepEqual(
    tabs.primary.map((tab) => tab.id),
    ['overview', 'plan', 'activity', 'artifacts']
  );
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
