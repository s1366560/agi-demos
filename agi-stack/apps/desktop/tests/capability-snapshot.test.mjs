import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  desktopCapability,
  parseDesktopCapabilitySnapshot,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js');
const fixture = JSON.parse(
  readFileSync(
    new URL(
      '../contracts/desktop-web-parity/fixtures/capability-snapshot.v1.json',
      import.meta.url,
    ),
    'utf8',
  ),
);

test('DesktopCapabilitySnapshot normalizes the shared versioned fixture', () => {
  const snapshot = parseDesktopCapabilitySnapshot(fixture.input.snapshot);
  assert.deepEqual(snapshot, fixture.input.snapshot);
  assert.deepEqual(desktopCapability(snapshot, 'sandbox_isolation'), {
    available: false,
    reason_code: 'local_isolation_not_applicable',
  });
  assert.deepEqual(desktopCapability(snapshot, 'search'), {
    available: false,
    reason_code: 'local_search_routes_unavailable',
  });
  assert.deepEqual(desktopCapability(snapshot, 'workspace_collaboration'), {
    available: false,
    reason_code: 'local_workspace_collaboration_unavailable',
  });
});

test('DesktopCapabilitySnapshot fails closed on missing, extra, or inconsistent fields', () => {
  const missing = structuredClone(fixture.input.snapshot);
  delete missing.capabilities.search;
  assert.equal(parseDesktopCapabilitySnapshot(missing), null);

  const extra = structuredClone(fixture.input.snapshot);
  extra.capabilities.search.hint = 'guess from a 404';
  assert.equal(parseDesktopCapabilitySnapshot(extra), null);

  const inconsistent = structuredClone(fixture.input.snapshot);
  inconsistent.capabilities.search.available = true;
  assert.equal(parseDesktopCapabilitySnapshot(inconsistent), null);

  assert.deepEqual(desktopCapability(null, 'search'), {
    available: false,
    reason_code: 'capability_snapshot_unavailable',
  });
});
