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
