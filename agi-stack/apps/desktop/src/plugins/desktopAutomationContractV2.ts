import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  AutomationCapabilities,
  AutomationCreateInput,
  AutomationDeleteInput,
  AutomationJob,
  AutomationJobListResponse,
  AutomationRunListResponse,
  AutomationToggleInput,
  AutomationUpdateInput,
  DesktopRuntimeConfig,
} from '../types';
import type {
  AutomationRunInput,
  AutomationRunReceipt,
} from '../features/automations/automationClient';

const ACTION_KEYS_V2 = ['create', 'delete', 'edit', 'run_now', 'toggle'] as const;
const RUN_STATUSES_V2 = new Set([
  'cancelled',
  'failed',
  'queued',
  'running',
  'success',
  'timeout',
  'waiting_human',
]);

export function cloneAutomationRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidAutomationInputV2();
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !isCanonicalStringV2(copy.apiBaseUrl) ||
    !isCanonicalStringV2(copy.tenantId) ||
    !isCanonicalStringV2(copy.projectId) ||
    (copy.workspaceId !== '' && !isCanonicalStringV2(copy.workspaceId))
  ) {
    throw invalidAutomationInputV2();
  }
  return Object.freeze(copy);
}

export function resolveAutomationProjectIdV2(
  config: DesktopRuntimeConfig,
  projectId: unknown,
): string {
  const resolved =
    projectId === undefined ? config.projectId : canonicalAutomationIdentifierV2(projectId);
  if (resolved !== config.projectId) throw automationScopeMismatchV2();
  return resolved;
}

export function cloneAutomationCreateInputV2(value: unknown): AutomationCreateInput {
  const copy = cloneJsonV2(value);
  if (
    !isPlainRecordV2(copy) ||
    !validIdempotencyKeyV2(copy.idempotency_key) ||
    !isCanonicalStringV2(copy.name) ||
    !validAutomationConfigV2(copy.schedule) ||
    !validAutomationConfigV2(copy.payload) ||
    (copy.delivery !== undefined && !validAutomationConfigV2(copy.delivery)) ||
    !validOptionalBooleanV2(copy.enabled) ||
    !validOptionalBooleanV2(copy.delete_after_run) ||
    !validOptionalNullableStringV2(copy.description) ||
    !validOptionalNullableIdentifierV2(copy.workspace_id) ||
    !validOptionalNullableIdentifierV2(copy.conversation_id) ||
    !validOptionalEnumV2(copy.conversation_mode, new Set(['fresh', 'reuse'])) ||
    !validOptionalCanonicalStringV2(copy.timezone) ||
    !validOptionalIntegerV2(copy.stagger_seconds, 0) ||
    !validOptionalIntegerV2(copy.timeout_seconds, 1) ||
    !validOptionalIntegerV2(copy.max_retries, 0)
  ) {
    throw invalidAutomationInputV2();
  }
  return deepFreezeV2(copy) as unknown as AutomationCreateInput;
}

export function cloneAutomationUpdateInputV2(value: unknown): AutomationUpdateInput {
  const copy = cloneJsonV2(value);
  if (
    !isPlainRecordV2(copy) ||
    !validIdempotencyKeyV2(copy.idempotency_key) ||
    !isPositiveIntegerV2(copy.expected_revision) ||
    (copy.name !== undefined && !isCanonicalStringV2(copy.name)) ||
    (copy.schedule !== undefined && !validAutomationConfigV2(copy.schedule)) ||
    (copy.payload !== undefined && !validAutomationConfigV2(copy.payload)) ||
    (copy.delivery !== undefined && !validAutomationConfigV2(copy.delivery)) ||
    !validOptionalBooleanV2(copy.enabled) ||
    !validOptionalBooleanV2(copy.delete_after_run) ||
    !validOptionalNullableStringV2(copy.description) ||
    !validOptionalNullableIdentifierV2(copy.workspace_id) ||
    !validOptionalNullableIdentifierV2(copy.conversation_id) ||
    !validOptionalEnumV2(copy.conversation_mode, new Set(['fresh', 'reuse'])) ||
    !validOptionalCanonicalStringV2(copy.timezone) ||
    !validOptionalIntegerV2(copy.stagger_seconds, 0) ||
    !validOptionalIntegerV2(copy.timeout_seconds, 1) ||
    !validOptionalIntegerV2(copy.max_retries, 0)
  ) {
    throw invalidAutomationInputV2();
  }
  return deepFreezeV2(copy) as unknown as AutomationUpdateInput;
}

export function cloneAutomationToggleInputV2(value: unknown): AutomationToggleInput {
  const copy = cloneJsonV2(value);
  if (
    !isPlainRecordV2(copy) ||
    !validIdempotencyKeyV2(copy.idempotency_key) ||
    !isPositiveIntegerV2(copy.expected_revision) ||
    typeof copy.enabled !== 'boolean'
  ) {
    throw invalidAutomationInputV2();
  }
  return deepFreezeV2(copy) as unknown as AutomationToggleInput;
}

export function cloneAutomationDeleteInputV2(value: unknown): AutomationDeleteInput {
  const copy = cloneJsonV2(value);
  if (
    !isPlainRecordV2(copy) ||
    !validIdempotencyKeyV2(copy.idempotency_key) ||
    !isPositiveIntegerV2(copy.expected_revision)
  ) {
    throw invalidAutomationInputV2();
  }
  return deepFreezeV2(copy) as unknown as AutomationDeleteInput;
}

export function cloneAutomationRunInputV2(value: unknown): AutomationRunInput {
  const copy = cloneJsonV2(value);
  if (
    !isPlainRecordV2(copy) ||
    !validIdempotencyKeyV2(copy.idempotency_key) ||
    !isPositiveIntegerV2(copy.expected_revision) ||
    !validOptionalNullableIdentifierV2(copy.conversation_id)
  ) {
    throw invalidAutomationInputV2();
  }
  return deepFreezeV2(copy) as unknown as AutomationRunInput;
}

export function assertAutomationCapabilitiesV2(value: unknown): AutomationCapabilities {
  if (
    !isPlainRecordV2(value) ||
    !Number.isSafeInteger(value.schema_version) ||
    Number(value.schema_version) < 1 ||
    typeof value.read !== 'boolean' ||
    typeof value.revision_guarded !== 'boolean' ||
    typeof value.idempotency_guarded !== 'boolean' ||
    typeof value.durable_execution !== 'boolean' ||
    !Array.isArray(value.supported_read_trigger_kinds) ||
    !value.supported_read_trigger_kinds.every(isCanonicalStringV2) ||
    ACTION_KEYS_V2.some((key) => !validActionCapabilityV2(value[key]))
  ) {
    throw invalidAutomationResponseV2();
  }
  return deepFreezeV2(cloneJsonV2(value)) as unknown as AutomationCapabilities;
}

export function assertAutomationJobV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  expectedAutomationId?: string,
): AutomationJob {
  if (
    !isPlainRecordV2(value) ||
    !isCanonicalStringV2(value.id) ||
    value.project_id !== config.projectId ||
    value.tenant_id !== config.tenantId ||
    (expectedAutomationId !== undefined && value.id !== expectedAutomationId) ||
    !isCanonicalStringV2(value.name) ||
    typeof value.enabled !== 'boolean' ||
    !isPositiveIntegerV2(value.revision)
  ) {
    throw invalidAutomationResponseV2();
  }
  return deepFreezeV2(cloneJsonV2(value)) as unknown as AutomationJob;
}

export function assertAutomationJobListV2(
  value: unknown,
  config: DesktopRuntimeConfig,
): AutomationJobListResponse {
  if (
    !isPlainRecordV2(value) ||
    !Array.isArray(value.items) ||
    !Number.isSafeInteger(value.total) ||
    Number(value.total) < 0
  ) {
    throw invalidAutomationResponseV2();
  }
  const items = value.items.map((item) => assertAutomationJobV2(item, config));
  return Object.freeze({
    items: Object.freeze(items),
    total: Number(value.total),
  }) as unknown as AutomationJobListResponse;
}

export function assertAutomationRunListV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  automationId: string,
): AutomationRunListResponse {
  if (
    !isPlainRecordV2(value) ||
    !Array.isArray(value.items) ||
    !Number.isSafeInteger(value.total) ||
    Number(value.total) < 0 ||
    value.items.some(
      (item) =>
        !isPlainRecordV2(item) ||
        !isCanonicalStringV2(item.id) ||
        item.job_id !== automationId ||
        item.project_id !== config.projectId ||
        !isCanonicalStringV2(item.status),
    )
  ) {
    throw invalidAutomationResponseV2();
  }
  return deepFreezeV2(cloneJsonV2(value)) as unknown as AutomationRunListResponse;
}

export function assertAutomationRunReceiptV2(
  value: unknown,
  automationId: string,
): AutomationRunReceipt {
  if (
    !isPlainRecordV2(value) ||
    !isCanonicalStringV2(value.receipt_id) ||
    !isCanonicalStringV2(value.run_id) ||
    value.job_id !== automationId ||
    typeof value.status !== 'string' ||
    !RUN_STATUSES_V2.has(value.status) ||
    typeof value.duplicate !== 'boolean'
  ) {
    throw invalidAutomationResponseV2();
  }
  return deepFreezeV2(cloneJsonV2(value)) as unknown as AutomationRunReceipt;
}

export function assertAutomationDeleteResponseV2(value: unknown): void {
  if (value !== undefined) throw invalidAutomationResponseV2();
}

export function cloneAutomationSignalV2(value: unknown): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw invalidAutomationInputV2();
  }
  return value;
}

export function canonicalAutomationIdentifierV2(value: unknown): string {
  if (!isCanonicalStringV2(value) || value.length > 256) throw invalidAutomationInputV2();
  return value;
}

export function invalidAutomationInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_automation_input_invalid',
    'desktop Automation operation input is invalid',
  );
}

export function automationScopeMismatchV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_automation_scope_mismatch',
    'desktop Automation operation differs from its configured project scope',
  );
}

function invalidAutomationResponseV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_automation_response_invalid',
    'desktop Automation authority returned an invalid response',
  );
}

function validAutomationConfigV2(value: unknown): boolean {
  return (
    isPlainRecordV2(value) &&
    isCanonicalStringV2(value.kind) &&
    isPlainRecordV2(value.config)
  );
}

function validActionCapabilityV2(value: unknown): boolean {
  return (
    isPlainRecordV2(value) &&
    typeof value.allowed === 'boolean' &&
    validOptionalNullableStringV2(value.reason_code)
  );
}

function validIdempotencyKeyV2(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length >= 1 &&
    value.length <= 255 &&
    [...value].every((character) => {
      const code = character.charCodeAt(0);
      return code >= 33 && code <= 126;
    })
  );
}

function validOptionalBooleanV2(value: unknown): boolean {
  return value === undefined || typeof value === 'boolean';
}

function validOptionalNullableStringV2(value: unknown): boolean {
  return value === undefined || value === null || typeof value === 'string';
}

function validOptionalNullableIdentifierV2(value: unknown): boolean {
  return value === undefined || value === null || isCanonicalStringV2(value);
}

function validOptionalCanonicalStringV2(value: unknown): boolean {
  return value === undefined || isCanonicalStringV2(value);
}

function validOptionalEnumV2(value: unknown, values: ReadonlySet<string>): boolean {
  return value === undefined || (typeof value === 'string' && values.has(value));
}

function validOptionalIntegerV2(value: unknown, minimum: number): boolean {
  return value === undefined || (Number.isSafeInteger(value) && Number(value) >= minimum);
}

function isPositiveIntegerV2(value: unknown): boolean {
  return Number.isSafeInteger(value) && Number(value) >= 1;
}

function cloneJsonV2<T>(value: T): T {
  try {
    return structuredClone(value);
  } catch {
    throw invalidAutomationInputV2();
  }
}

function deepFreezeV2<T>(value: T): T {
  if (Array.isArray(value)) {
    for (const item of value) deepFreezeV2(item);
    return Object.freeze(value);
  }
  if (isPlainRecordV2(value)) {
    for (const item of Object.values(value)) deepFreezeV2(item);
    return Object.freeze(value) as T;
  }
  return value;
}

export function isAutomationPlainRecordV2(value: unknown): value is Record<string, unknown> {
  return isPlainRecordV2(value);
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}
