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
      '../contracts/desktop-web-parity/fixtures/capability-snapshot.v2.json',
      import.meta.url,
    ),
    'utf8',
  ),
);

test('DesktopCapabilitySnapshot v2 normalizes the shared versioned fixture', () => {
  const snapshot = parseDesktopCapabilitySnapshot(fixture.input.snapshot);
  assert.deepEqual(snapshot, fixture.input.snapshot);
  assert.deepEqual(desktopCapability(snapshot, 'sandbox_isolation'), {
    status: 'not_applicable',
    available: false,
    reason_code: 'local_isolation_not_applicable',
    service_version: null,
    contract_version: null,
    minimum_contract_version: '2.0.0',
  });
  assert.deepEqual(desktopCapability(snapshot, 'search'), {
    status: 'degraded',
    available: true,
    reason_code: 'local_search_keyword_only',
    service_version: '0.1.0',
    contract_version: '2.0.0',
    minimum_contract_version: '2.0.0',
  });
  assert.deepEqual(desktopCapability(snapshot, 'workspace_collaboration'), {
    status: 'unavailable',
    available: false,
    reason_code: 'local_workspace_collaboration_unavailable',
    service_version: null,
    contract_version: null,
    minimum_contract_version: '2.0.0',
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
  inconsistent.capabilities.search.status = 'available';
  assert.equal(parseDesktopCapabilitySnapshot(inconsistent), null);

  assert.deepEqual(desktopCapability(null, 'search'), {
    status: 'unavailable',
    available: false,
    reason_code: 'capability_snapshot_unavailable',
    service_version: null,
    contract_version: null,
    minimum_contract_version: '2.0.0',
  });
});
