import assert from 'node:assert/strict';
import test from 'node:test';

import {
  automationActionCapability,
  automationActionAvailability,
  automationCapabilityReasonCode,
  automationEnvironmentId,
  automationLastRunAt,
  automationNextRunAt,
  automationPermissionProfile,
  automationRunStatus,
  automationRunTrigger,
  automationRunsForJob,
  automationScheduleValue,
  automationTrigger,
  automationTriggerKind,
} from '/tmp/agistack-desktop-test-dist/src/features/automations/automationModel.js';

const job = {
  id: 'automation-1',
  project_id: 'project-1',
  tenant_id: 'tenant-1',
  name: 'Nightly review',
  enabled: true,
  delete_after_run: false,
  schedule: { kind: 'cron', config: { expr: '0 2 * * *' } },
  payload: { kind: 'agent_turn', config: { message: 'Review work' } },
  delivery: { kind: 'announce', config: {} },
  conversation_mode: 'reuse',
  timezone: 'UTC',
  stagger_seconds: 0,
  timeout_seconds: 300,
  max_retries: 3,
  state: {
    last_run_at: '2026-07-13T02:00:00Z',
    last_run_status: 'success',
    next_run_at: '2026-07-14T02:00:00Z',
    environment_id: 'environment-1',
    permission_profile: 'workspace_write',
  },
  created_at: '2026-07-01T00:00:00Z',
};

test('automation presentation reads only explicit scheduler fields', () => {
  assert.equal(automationTriggerKind(job), 'schedule');
  assert.equal(automationScheduleValue(job), '0 2 * * *');
  assert.equal(automationLastRunAt(job), '2026-07-13T02:00:00Z');
  assert.equal(automationNextRunAt(job), '2026-07-14T02:00:00Z');
  assert.equal(automationEnvironmentId(job), 'environment-1');
  assert.equal(automationPermissionProfile(job), 'workspace_write');
});

test('missing authority and next-run fields remain unknown instead of being inferred', () => {
  const incomplete = { ...job, state: {}, schedule: { kind: 'manual', config: {} } };
  assert.equal(automationTriggerKind(incomplete), 'manual');
  assert.equal(automationScheduleValue(incomplete), null);
  assert.equal(automationLastRunAt(incomplete), null);
  assert.equal(automationNextRunAt(incomplete), null);
  assert.equal(automationEnvironmentId(incomplete), null);
  assert.equal(automationPermissionProfile(incomplete), null);
});

test('explicit trigger union takes precedence over legacy schedule storage', () => {
  const eventJob = {
    ...job,
    trigger: { kind: 'event', source_id: 'deployments', event_type: 'deployment.ready' },
  };
  assert.deepEqual(automationTrigger(eventJob), eventJob.trigger);
  assert.equal(automationTriggerKind(eventJob), 'event');
  assert.equal(automationScheduleValue(eventJob), 'deployment.ready');
});

test('mutation capabilities fail closed when the server contract is absent', () => {
  assert.deepEqual(automationActionCapability(null, 'run_now'), {
    allowed: false,
    reason_code: 'capability_contract_unavailable',
  });
  assert.deepEqual(
    automationActionCapability(
      {
        run_now: { allowed: false, reason_code: 'project_write_required' },
      },
      'run_now',
    ),
    { allowed: false, reason_code: 'project_write_required' },
  );
});

test('mutation controls require server guards and an implemented client handler', () => {
  const guarded = {
    schema_version: 1,
    read: true,
    revision_guarded: true,
    idempotency_guarded: true,
    durable_execution: true,
    supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
    create: { allowed: true, reason_code: null },
    edit: { allowed: true, reason_code: null },
    toggle: { allowed: true, reason_code: null },
    run_now: { allowed: true, reason_code: null },
    delete: { allowed: true, reason_code: null },
  };

  assert.deepEqual(
    automationActionAvailability(guarded, 'create', {
      handler_available: false,
      revision_required: false,
    }),
    { allowed: false, reason_code: 'client_handler_unavailable' },
  );
  assert.deepEqual(
    automationActionAvailability(
      { ...guarded, revision_guarded: false },
      'run_now',
      { handler_available: true, revision_required: true },
    ),
    { allowed: false, reason_code: 'revision_guard_required' },
  );
});

test('unknown capability reasons map to a stable localized fallback', () => {
  assert.equal(
    automationCapabilityReasonCode('future_server_reason'),
    'capability_contract_unavailable',
  );
  assert.equal(
    automationCapabilityReasonCode('project_write_required'),
    'project_write_required',
  );
});

test('run protocol values map to stable localized identifiers', () => {
  assert.equal(automationRunStatus('waiting_human'), 'waiting_human');
  assert.equal(automationRunStatus('unexpected'), 'unknown');
  assert.equal(automationRunTrigger('scheduled'), 'scheduled');
  assert.equal(automationRunTrigger('webhook'), 'unknown');
});

test('run history is kept inside the exact automation and project scope', () => {
  const runs = [
    { id: 'run-1', job_id: 'automation-1', project_id: 'project-1' },
    { id: 'run-2', job_id: 'automation-2', project_id: 'project-1' },
    { id: 'run-3', job_id: 'automation-1', project_id: 'project-2' },
  ];
  assert.deepEqual(
    automationRunsForJob(job, runs).map((run) => run.id),
    ['run-1'],
  );
});
