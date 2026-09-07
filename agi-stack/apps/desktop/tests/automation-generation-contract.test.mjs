import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/src';
const { normalizeAutomationCapabilities, normalizeAutomationCapabilityEnvelope } = require(
  `${root}/features/automations/automationModel.js`,
);
const {
  normalizeAutomationCapabilityContract,
  normalizeProjectCronJobsCapabilityContract,
} = require(`${root}/features/runtime/workbenchCapabilityClient.js`);
const {
  assertAutomationCapabilitiesV2,
  assertAutomationRunListV2,
  assertAutomationRunReceiptV2,
} = require(`${root}/plugins/desktopAutomationContractV2.js`);

function capabilities(revision = 51) {
  return {
    schema_version: 3,
    authority_revision: revision,
    read: true,
    revision_guarded: true,
    idempotency_guarded: true,
    durable_execution: true,
    supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
    create: { allowed: true },
    edit: { allowed: true },
    toggle: { allowed: true },
    run_now: { allowed: true },
    delete: { allowed: true },
  };
}
function envelope(value) {
  return { service_version: '0.1.0', contract_version: '2.0.0', ...value };
}

test('automation v3 transports genuine generation revisions through all decoders', () => {
  for (const revision of [51, 52, Number.MAX_SAFE_INTEGER]) {
    const value = capabilities(revision);
    assert.deepEqual(normalizeAutomationCapabilities(value), value);
    assert.deepEqual(normalizeAutomationCapabilityEnvelope(envelope(value)), envelope(value));
    assert.deepEqual(assertAutomationCapabilitiesV2(value), value);
    for (const normalize of [
      normalizeAutomationCapabilityContract,
      normalizeProjectCronJobsCapabilityContract,
    ]) {
      const normalized = normalize(envelope(value));
      assert.equal(normalized.availability, 'available');
      assert.equal(normalized.authority_revision, revision);
    }
    const degraded = normalizeProjectCronJobsCapabilityContract(
      envelope({
        ...value,
        durable_execution: false,
        run_now: {
          allowed: false,
          reason_code: 'durable_automation_execution_unavailable',
        },
      }),
    );
    assert.equal(degraded.availability, 'degraded');
    assert.equal(degraded.authority_revision, revision);
  }
});

test('automation v3 rejects absent, malformed or fabricated legacy revisions', () => {
  for (const revision of [undefined, null, 0, -1, 1.5, '51', Number.MAX_SAFE_INTEGER + 1]) {
    const value = capabilities(revision);
    if (revision === undefined) delete value.authority_revision;
    assert.equal(normalizeAutomationCapabilities(value), null);
    assert.equal(normalizeAutomationCapabilityEnvelope(envelope(value)), null);
    assert.throws(() => assertAutomationCapabilitiesV2(value));
  }
  for (const schema_version of [1, 2]) {
    const legacy = { ...capabilities(), schema_version };
    assert.equal(normalizeAutomationCapabilities(legacy), null);
    assert.throws(() => assertAutomationCapabilitiesV2(legacy));
    delete legacy.authority_revision;
    assert.deepEqual(normalizeAutomationCapabilities(legacy), legacy);
    assert.equal(
      normalizeProjectCronJobsCapabilityContract(envelope(legacy)).authority_revision,
      null,
    );
  }
});

test('skipped history and receipts retain their wire fields while unknown statuses fail', () => {
  const config = { tenantId: 'tenant', projectId: 'project' };
  const skipped = {
    id: 'run',
    job_id: 'job',
    project_id: 'project',
    status: 'skipped',
    trigger: 'scheduled',
    result: { reason_code: 'scheduler_offline_missed_fire' },
    error: null,
    scheduled_at: '2026-09-07T00:00:00Z',
    started_at: null,
    completed_at: '2026-09-07T00:05:00Z',
    attempt: 0,
  };
  const history = { items: [skipped], total: 1 };
  assert.deepEqual(assertAutomationRunListV2(history, config, 'job'), history);
  const receipt = {
    receipt_id: 'receipt',
    run_id: 'run',
    job_id: 'job',
    status: 'skipped',
    duplicate: false,
  };
  assert.deepEqual(assertAutomationRunReceiptV2(receipt, 'job'), receipt);
  assert.throws(() =>
    assertAutomationRunListV2(
      { items: [{ ...skipped, status: 'future-state' }], total: 1 },
      config,
      'job',
    ),
  );
});
