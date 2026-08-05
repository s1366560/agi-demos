import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('Desktop validates HITL commands against request authority instead of run revision', () => {
  assert.match(
    appSource,
    /request\?\.authority_revision === submission\.expectedRevision/u,
  );
  assert.doesNotMatch(
    appSource,
    /request\.run_revision === submission\.expectedRevision/u,
  );
});

test('permission deny feedback is submitted atomically with the HITL response', () => {
  const callback = appSource.match(
    /const respondToHitlWithSteering = useCallback\([\s\S]*?\n  \);/u,
  )?.[0];

  assert.ok(callback);
  assert.match(callback, /await respondToHitl\(submission\)/u);
  assert.doesNotMatch(callback, /sendChatMessage/u);
  assert.doesNotMatch(callback, /denialSteeringFeedback/u);
});
