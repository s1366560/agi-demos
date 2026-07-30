import type {
  AutomationActionCapability,
  AutomationCapabilityEnvelope,
  AutomationCapabilities,
  AutomationJob,
  AutomationRun,
  AutomationTrigger,
} from '../../types';

export type AutomationTriggerKind = 'manual' | 'schedule' | 'event' | 'unknown';

export type AutomationAction = 'create' | 'edit' | 'toggle' | 'run_now' | 'delete';

export type AutomationActionRequirements = {
  handler_available: boolean;
  revision_required: boolean;
  durable_execution_required?: boolean;
};

export type AutomationCapabilityReasonCode =
  | 'durable_automation_runtime_unavailable'
  | 'durable_automation_execution_unavailable'
  | 'project_write_required'
  | 'capability_contract_unavailable'
  | 'client_handler_unavailable'
  | 'revision_guard_required'
  | 'idempotency_guard_required'
  | 'durable_execution_required';

export type AutomationRunStatus =
  | 'queued'
  | 'running'
  | 'waiting_human'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'cancelled'
  | 'unknown';

export type AutomationRunTrigger = 'manual' | 'scheduled' | 'event' | 'unknown';

const LEGACY_MUTATION_CAPABILITY: AutomationActionCapability = {
  allowed: false,
  reason_code: 'capability_contract_unavailable',
};

const CAPABILITY_REASON_CODES = new Set<AutomationCapabilityReasonCode>([
  'durable_automation_runtime_unavailable',
  'durable_automation_execution_unavailable',
  'project_write_required',
  'capability_contract_unavailable',
  'client_handler_unavailable',
  'revision_guard_required',
  'idempotency_guard_required',
  'durable_execution_required',
]);

export function automationTrigger(job: AutomationJob): AutomationTrigger {
  if (job.trigger) return job.trigger;
  if (job.schedule.kind === 'manual') return { kind: 'manual' };
  if (job.schedule.kind === 'event') {
    return {
      kind: 'event',
      source_id: stringValue(job.schedule.config.source_id),
      event_type:
        stringValue(job.schedule.config.event_type ?? job.schedule.config.event_name) ?? 'unknown',
    };
  }
  if (job.schedule.kind === 'at' || job.schedule.kind === 'every' || job.schedule.kind === 'cron') {
    return { kind: 'schedule', schedule: job.schedule };
  }
  return { kind: 'unknown', raw_kind: job.schedule.kind || null };
}

export function automationTriggerKind(job: AutomationJob): AutomationTriggerKind {
  return automationTrigger(job).kind;
}

export function automationScheduleValue(job: AutomationJob): string | null {
  const trigger = automationTrigger(job);
  if (trigger.kind === 'event') return trigger.event_type;
  if (trigger.kind !== 'schedule') return null;
  const config = trigger.schedule.config;
  if (trigger.schedule.kind === 'cron') return stringValue(config.expr ?? config.expression);
  if (trigger.schedule.kind === 'at') return stringValue(config.run_at ?? config.target_time);
  if (trigger.schedule.kind === 'every') return numberValue(config.interval_seconds);
  return null;
}

export function automationActionCapability(
  capabilities: AutomationCapabilities | null,
  action: AutomationAction,
): AutomationActionCapability {
  return capabilities?.[action] ?? LEGACY_MUTATION_CAPABILITY;
}

export function automationActionAvailability(
  capabilities: AutomationCapabilities | null,
  action: AutomationAction,
  requirements: AutomationActionRequirements,
): AutomationActionCapability {
  const declared = automationActionCapability(capabilities, action);
  if (!declared.allowed) return declared;
  if (!requirements.handler_available) {
    return { allowed: false, reason_code: 'client_handler_unavailable' };
  }
  if (!capabilities?.idempotency_guarded) {
    return { allowed: false, reason_code: 'idempotency_guard_required' };
  }
  if (requirements.durable_execution_required && !capabilities.durable_execution) {
    return { allowed: false, reason_code: 'durable_execution_required' };
  }
  if (requirements.revision_required && !capabilities.revision_guarded) {
    return { allowed: false, reason_code: 'revision_guard_required' };
  }
  return declared;
}

export function automationCapabilityReasonCode(
  reasonCode: string | null | undefined,
): AutomationCapabilityReasonCode {
  return CAPABILITY_REASON_CODES.has(reasonCode as AutomationCapabilityReasonCode)
    ? (reasonCode as AutomationCapabilityReasonCode)
    : 'capability_contract_unavailable';
}

export function normalizeAutomationCapabilities(
  input: unknown,
): AutomationCapabilities | null {
  if (
    !isExactRecord(input, [
      'schema_version',
      'read',
      'revision_guarded',
      'idempotency_guarded',
      'durable_execution',
      'supported_read_trigger_kinds',
      'create',
      'edit',
      'toggle',
      'run_now',
      'delete',
    ]) ||
    (input.schema_version !== 1 && input.schema_version !== 2) ||
    typeof input.read !== 'boolean' ||
    typeof input.revision_guarded !== 'boolean' ||
    typeof input.idempotency_guarded !== 'boolean' ||
    typeof input.durable_execution !== 'boolean' ||
    !isExactStringSet(input.supported_read_trigger_kinds, ['manual', 'schedule', 'event'])
  ) {
    return null;
  }

  const create = normalizeAutomationActionCapability(input.create);
  const edit = normalizeAutomationActionCapability(input.edit);
  const toggle = normalizeAutomationActionCapability(input.toggle);
  const runNow = normalizeAutomationActionCapability(input.run_now);
  const deleteCapability = normalizeAutomationActionCapability(input.delete);
  if (!create || !edit || !toggle || !runNow || !deleteCapability) return null;
  return {
    schema_version: input.schema_version,
    read: input.read,
    revision_guarded: input.revision_guarded,
    idempotency_guarded: input.idempotency_guarded,
    durable_execution: input.durable_execution,
    supported_read_trigger_kinds: input.supported_read_trigger_kinds,
    create,
    edit,
    toggle,
    run_now: runNow,
    delete: deleteCapability,
  };
}

export function normalizeAutomationCapabilityEnvelope(
  input: unknown,
): AutomationCapabilityEnvelope | null {
  if (
    !isExactRecord(input, [
      'service_version',
      'contract_version',
      'schema_version',
      'read',
      'revision_guarded',
      'idempotency_guarded',
      'durable_execution',
      'supported_read_trigger_kinds',
      'create',
      'edit',
      'toggle',
      'run_now',
      'delete',
    ]) ||
    typeof input.service_version !== 'string' ||
    !input.service_version.trim() ||
    typeof input.contract_version !== 'string' ||
    !input.contract_version.trim()
  ) {
    return null;
  }
  const {
    service_version: serviceVersion,
    contract_version: contractVersion,
    ...capabilityPayload
  } = input;
  const capabilities = normalizeAutomationCapabilities(capabilityPayload);
  if (!capabilities) return null;
  return {
    service_version: serviceVersion,
    contract_version: contractVersion,
    ...capabilities,
  };
}

export function automationRunStatus(status: string): AutomationRunStatus {
  if (
    status === 'queued' ||
    status === 'running' ||
    status === 'waiting_human' ||
    status === 'success' ||
    status === 'failed' ||
    status === 'timeout' ||
    status === 'cancelled'
  ) {
    return status;
  }
  return 'unknown';
}

export function automationRunTrigger(triggerType: string): AutomationRunTrigger {
  if (triggerType === 'manual' || triggerType === 'scheduled' || triggerType === 'event') {
    return triggerType;
  }
  return 'unknown';
}

export function automationLastRunAt(job: AutomationJob): string | null {
  return stringValue(job.state.last_run_at);
}

export function automationNextRunAt(job: AutomationJob): string | null {
  return stringValue(job.state.next_run_at);
}

export function automationLastRunStatus(job: AutomationJob): string | null {
  return stringValue(job.state.last_run_status);
}

export function automationEnvironmentId(job: AutomationJob): string | null {
  return stringValue(job.state.environment_id);
}

export function automationPermissionProfile(job: AutomationJob): string | null {
  return stringValue(job.state.permission_profile);
}

export function automationRunsForJob(job: AutomationJob, runs: AutomationRun[]): AutomationRun[] {
  return runs.filter((run) => run.job_id === job.id && run.project_id === job.project_id);
}

export function automationMutationKey(
  keys: Map<string, string>,
  operation: string,
  payload: unknown,
  createKey: () => string = () => crypto.randomUUID(),
): string {
  const fingerprint = `${operation}:${JSON.stringify(payload)}`;
  const existing = keys.get(fingerprint);
  if (existing) return existing;
  const key = `${operation.split(':', 1)[0]}-${createKey()}`;
  keys.set(fingerprint, key);
  return key;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function numberValue(value: unknown): string | null {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : null;
}

function normalizeAutomationActionCapability(
  input: unknown,
): AutomationActionCapability | null {
  if (
    !isRecord(input) ||
    !Object.keys(input).every((key) => key === 'allowed' || key === 'reason_code') ||
    typeof input.allowed !== 'boolean'
  ) {
    return null;
  }
  if (input.allowed) {
    if (input.reason_code !== undefined && input.reason_code !== null) return null;
    return { allowed: true, ...(input.reason_code === null ? { reason_code: null } : {}) };
  }
  if (typeof input.reason_code !== 'string' || !input.reason_code.trim()) return null;
  return { allowed: false, reason_code: input.reason_code };
}

function isExactRecord(
  input: unknown,
  expectedKeys: readonly string[],
): input is Record<string, unknown> {
  if (!isRecord(input)) return false;
  const keys = Object.keys(input).sort();
  const expected = [...expectedKeys].sort();
  return keys.length === expected.length && keys.every((key, index) => key === expected[index]);
}

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === 'object' && input !== null && !Array.isArray(input);
}

function isExactStringSet(input: unknown, expectedValues: readonly string[]): input is string[] {
  if (!Array.isArray(input) || !input.every((item) => typeof item === 'string')) return false;
  const values = [...input].sort();
  const expected = [...expectedValues].sort();
  return (
    values.length === expected.length &&
    values.every((value, index) => value === expected[index])
  );
}
