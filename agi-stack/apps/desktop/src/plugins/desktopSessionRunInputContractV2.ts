import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  AgentConversation,
  AgentRuntimeMode,
  ComposerContextItem,
  CreateRunInputRequest,
  DesktopRunInput,
  DesktopRuntimeConfig,
  PromoteRunInputResponse,
  RunInputAck,
  RunInputReference,
} from '../types';

export type DesktopSessionRunInputIdentityV2 = Readonly<{
  tenant_id: string;
  project_id: string;
  workspace_id: string | null;
  session_id: string;
}>;

export type DesktopSessionRunInputListResponseV2 = Readonly<{
  run_id: string;
  run_revision: number;
  inputs: DesktopRunInput[];
  total_count: number;
}>;

export type DesktopSessionRunInputConversationProjectionV2 = Readonly<{
  id: string;
  tenant_id: string;
  project_id: string;
  workspace_id: string | null;
  current_mode?: AgentRuntimeMode | null;
}>;

export type DesktopSessionRunInputSourceRunProjectionV2 = Readonly<{
  id: string;
  conversation_id: string;
  project_id: string;
  revision: number;
}>;

export type DesktopSessionRunInputPromotionResponseV2 = Readonly<{
  accepted: true;
  created: boolean;
  action: 'start_plan_turn';
  input: DesktopRunInput;
  conversation: DesktopSessionRunInputConversationProjectionV2;
  source_run: DesktopSessionRunInputSourceRunProjectionV2;
}>;

const CONFIG_KEYS_V2 = new Set([
  'apiBaseUrl',
  'deviceAuthorizationBaseUrl',
  'apiKey',
  'localApiToken',
  'tenantId',
  'projectId',
  'workspaceId',
  'mode',
  'workspaceRoot',
]);
const CREATE_REQUEST_KEYS_V2 = new Set([
  'expectedRunRevision',
  'message',
  'messageId',
  'idempotencyKey',
  'delivery',
  'references',
  'contextItems',
]);
const REFERENCE_KEYS_V2 = new Set([
  'type',
  'snapshot_id',
  'environment_id',
  'path',
  'start_line',
  'end_line',
  'side',
  'patch_digest',
]);
const CONTEXT_REQUIRED_KEYS_V2 = new Set(['kind', 'resource_id', 'label']);
const CONTEXT_OPTIONAL_KEYS_V2 = new Set(['metadata']);
const CONTEXT_KINDS_V2 = new Set([
  'attachment',
  'agent',
  'skill',
  'plugin',
  'command',
  'thread',
]);
const DELIVERIES_V2 = new Set(['steer_now', 'queue_next']);
const STATUSES_V2 = new Set([
  'pending_boundary',
  'queued',
  'applied',
  'ready',
  'blocked',
  'promoted_to_plan',
]);
const DISPATCH_STATUSES_V2 = new Set([
  'not_required',
  'dispatching',
  'dispatched',
  'failed',
]);
const RUNTIME_MODES_V2 = new Set(['plan', 'build', 'explore']);
const RECEIPT_REQUIRED_KEYS_V2 = new Set([
  'id',
  'conversation_id',
  'run_id',
  'expected_run_revision',
  'message_id',
  'idempotency_key',
  'delivery',
  'status',
  'sequence',
  'queue_position',
  'content',
  'references',
  'context_items',
  'applied_round',
  'applied_at',
  'created_at',
  'updated_at',
]);
const RECEIPT_OPTIONAL_KEYS_V2 = new Set([
  'injected_via',
  'dispatch_status',
  'dispatch_attempts',
  'dispatch_lease_expires_at',
  'dispatch_error_code',
  'promotion_idempotency_key',
  'promoted_at',
]);

export function cloneSessionRunInputRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (
    !isPlainRecordV2(config) ||
    !hasExactKeysV2(config, CONFIG_KEYS_V2)
  ) {
    throw sessionRunInputInputInvalidV2();
  }
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
    !isOptionalWorkspaceStringV2(copy.workspaceId)
  ) {
    throw sessionRunInputInputInvalidV2();
  }
  return Object.freeze(copy);
}

export function cloneSessionRunInputIdentityV2(
  conversation: Pick<
    AgentConversation,
    'id' | 'tenant_id' | 'project_id' | 'workspace_id'
  >,
): DesktopSessionRunInputIdentityV2 {
  if (
    !isPlainRecordV2(conversation) ||
    !isCanonicalStringV2(conversation.id) ||
    !isCanonicalStringV2(conversation.tenant_id) ||
    !isCanonicalStringV2(conversation.project_id)
  ) {
    throw sessionRunInputInputInvalidV2();
  }
  const workspaceId = cloneWorkspaceIdV2(conversation.workspace_id);
  if (workspaceId === undefined) throw sessionRunInputInputInvalidV2();
  return Object.freeze({
    tenant_id: conversation.tenant_id,
    project_id: conversation.project_id,
    workspace_id: workspaceId,
    session_id: conversation.id,
  });
}

export function cloneSessionRunInputServiceIdentityV2(
  identity: DesktopSessionRunInputIdentityV2,
): DesktopSessionRunInputIdentityV2 {
  if (
    !isPlainRecordV2(identity) ||
    !hasExactKeysV2(
      identity,
      new Set(['tenant_id', 'project_id', 'workspace_id', 'session_id']),
    ) ||
    !isCanonicalStringV2(identity.tenant_id) ||
    !isCanonicalStringV2(identity.project_id) ||
    !isCanonicalStringV2(identity.session_id)
  ) {
    throw sessionRunInputInputInvalidV2();
  }
  const workspaceId = cloneWorkspaceIdV2(identity.workspace_id);
  if (workspaceId === undefined) throw sessionRunInputInputInvalidV2();
  return Object.freeze({
    tenant_id: identity.tenant_id,
    project_id: identity.project_id,
    workspace_id: workspaceId,
    session_id: identity.session_id,
  });
}

export function assertSessionRunInputScopeV2(
  config: DesktopRuntimeConfig,
  identity: DesktopSessionRunInputIdentityV2,
): void {
  const workspaceId = config.workspaceId.trim() || null;
  if (
    config.tenantId !== identity.tenant_id ||
    config.projectId !== identity.project_id ||
    workspaceId !== identity.workspace_id
  ) {
    throw new RuntimeV2Error(
      'desktop_session_run_input_scope_mismatch',
      'desktop session run-input scope differs from the conversation identity',
    );
  }
}

export function cloneSessionRunInputCreateRequestV2(
  request: CreateRunInputRequest,
): CreateRunInputRequest {
  if (
    !isPlainRecordV2(request) ||
    !hasExactKeysV2(request, CREATE_REQUEST_KEYS_V2) ||
    !isPositiveSafeIntegerV2(request.expectedRunRevision) ||
    !isNonemptyStringV2(request.message) ||
    request.message.length > 100_000 ||
    !isBoundedIdentifierV2(request.messageId, 255) ||
    !isBoundedIdentifierV2(request.idempotencyKey, 255) ||
    !DELIVERIES_V2.has(String(request.delivery)) ||
    !Array.isArray(request.references) ||
    request.references.length > 32 ||
    !Array.isArray(request.contextItems) ||
    request.contextItems.length > 32
  ) {
    throw sessionRunInputInputInvalidV2();
  }
  const references = request.references.map((value) =>
    cloneReferenceV2(value, sessionRunInputInputInvalidV2),
  );
  const contextItems = request.contextItems.map((value) =>
    cloneContextItemV2(value, sessionRunInputInputInvalidV2),
  );
  assertUniqueReferencesAndContextV2(
    references,
    contextItems,
    sessionRunInputInputInvalidV2,
  );
  return Object.freeze({
    expectedRunRevision: request.expectedRunRevision,
    message: request.message,
    messageId: request.messageId,
    idempotencyKey: request.idempotencyKey,
    delivery: request.delivery,
    references: Object.freeze(references) as RunInputReference[],
    contextItems: Object.freeze(contextItems) as ComposerContextItem[],
  });
}

export function cloneSessionRunInputIdentifierV2(value: unknown): string {
  if (!isBoundedIdentifierV2(value, 512)) throw sessionRunInputInputInvalidV2();
  return value;
}

export function cloneSessionRunInputRevisionV2(value: unknown): number {
  if (!isPositiveSafeIntegerV2(value)) throw sessionRunInputInputInvalidV2();
  return value;
}

export function cloneSessionRunInputSignalV2(
  value: unknown,
): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw sessionRunInputInputInvalidV2();
  }
  return value;
}

export function cloneSessionRunInputAckV2(
  value: unknown,
  identity: DesktopSessionRunInputIdentityV2,
  runId: string,
  request: CreateRunInputRequest,
): RunInputAck {
  if (
    !isPlainRecordV2(value) ||
    value.accepted !== true ||
    typeof value.created !== 'boolean' ||
    value.action !== 'send_message' ||
    value.conversation_id !== identity.session_id ||
    value.message_id !== request.messageId ||
    value.delivery_mode !== request.delivery ||
    value.run_id !== runId ||
    value.run_revision !== request.expectedRunRevision ||
    !isNullablePositiveSafeIntegerV2(value.queue_position)
  ) {
    throw sessionRunInputResponseInvalidV2();
  }
  const input = cloneReceiptV2(value.input, identity, runId);
  if (
    input.expected_run_revision !== request.expectedRunRevision ||
    input.message_id !== request.messageId ||
    input.idempotency_key !== request.idempotencyKey ||
    input.delivery !== request.delivery ||
    input.content !== request.message ||
    input.queue_position !== value.queue_position ||
    !sameJsonV2(input.references, request.references) ||
    !sameJsonV2(input.context_items ?? [], request.contextItems)
  ) {
    throw sessionRunInputResponseInvalidV2();
  }
  return Object.freeze({
    accepted: true,
    created: value.created,
    action: 'send_message',
    conversation_id: identity.session_id,
    message_id: request.messageId,
    delivery_mode: request.delivery,
    run_id: runId,
    run_revision: request.expectedRunRevision,
    queue_position: value.queue_position,
    input,
  });
}

export function cloneSessionRunInputListResponseV2(
  value: unknown,
  identity: DesktopSessionRunInputIdentityV2,
  runId: string,
): DesktopSessionRunInputListResponseV2 {
  if (
    !isPlainRecordV2(value) ||
    value.run_id !== runId ||
    !isPositiveSafeIntegerV2(value.run_revision) ||
    !Array.isArray(value.inputs) ||
    !isNonnegativeSafeIntegerV2(value.total_count) ||
    value.total_count !== value.inputs.length
  ) {
    throw sessionRunInputResponseInvalidV2();
  }
  const inputs = value.inputs.map((input) => cloneReceiptV2(input, identity, runId));
  if (
    new Set(inputs.map((input) => input.id)).size !== inputs.length ||
    new Set(inputs.map((input) => input.sequence)).size !== inputs.length
  ) {
    throw sessionRunInputResponseInvalidV2();
  }
  return Object.freeze({
    run_id: runId,
    run_revision: value.run_revision,
    inputs: Object.freeze(inputs) as DesktopRunInput[],
    total_count: value.total_count,
  });
}

export function cloneSessionRunInputPromotionResponseV2(
  value: PromoteRunInputResponse | unknown,
  identity: DesktopSessionRunInputIdentityV2,
  runId: string,
  inputId: string,
  expectedRevision: number,
  idempotencyKey: string,
): DesktopSessionRunInputPromotionResponseV2 {
  if (
    !isPlainRecordV2(value) ||
    value.accepted !== true ||
    typeof value.created !== 'boolean' ||
    value.action !== 'start_plan_turn' ||
    !isPlainRecordV2(value.conversation) ||
    !isPlainRecordV2(value.source_run)
  ) {
    throw sessionRunInputResponseInvalidV2();
  }
  const input = cloneReceiptV2(value.input, identity, runId);
  const conversation = clonePromotionConversationV2(value.conversation, identity);
  const sourceRun = clonePromotionSourceRunV2(
    value.source_run,
    identity,
    runId,
    expectedRevision,
  );
  if (
    input.id !== inputId ||
    input.status !== 'promoted_to_plan' ||
    input.promotion_idempotency_key !== idempotencyKey
  ) {
    throw sessionRunInputResponseInvalidV2();
  }
  return Object.freeze({
    accepted: true,
    created: value.created,
    action: 'start_plan_turn',
    input,
    conversation,
    source_run: sourceRun,
  });
}

export function sessionRunInputInputInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_session_run_input_input_invalid',
    'desktop session run-input operation input is invalid',
  );
}

export function sessionRunInputResponseInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_session_run_input_response_invalid',
    'desktop session run-input response is invalid',
  );
}

export function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function hasExactKeysV2(
  value: Record<string, unknown>,
  keys: ReadonlySet<string>,
): boolean {
  return Object.keys(value).length === keys.size && Object.keys(value).every((key) => keys.has(key));
}

function cloneReceiptV2(
  value: unknown,
  identity: DesktopSessionRunInputIdentityV2,
  runId: string,
): DesktopRunInput {
  if (
    !isPlainRecordV2(value) ||
    !hasRequiredAndOptionalKeysV2(value, RECEIPT_REQUIRED_KEYS_V2, RECEIPT_OPTIONAL_KEYS_V2) ||
    !isCanonicalStringV2(value.id) ||
    value.conversation_id !== identity.session_id ||
    value.run_id !== runId ||
    !isPositiveSafeIntegerV2(value.expected_run_revision) ||
    !isCanonicalStringV2(value.message_id) ||
    !isCanonicalStringV2(value.idempotency_key) ||
    !DELIVERIES_V2.has(String(value.delivery)) ||
    !STATUSES_V2.has(String(value.status)) ||
    !isPositiveSafeIntegerV2(value.sequence) ||
    !isNullablePositiveSafeIntegerV2(value.queue_position) ||
    typeof value.content !== 'string' ||
    !Array.isArray(value.references) ||
    !Array.isArray(value.context_items) ||
    !isNullableNonnegativeSafeIntegerV2(value.applied_round) ||
    !isNullableCanonicalStringV2(value.applied_at) ||
    !isOptionalNullableCanonicalStringV2(value.injected_via) ||
    !isOptionalDispatchStatusV2(value.dispatch_status) ||
    !isOptionalNonnegativeSafeIntegerV2(value.dispatch_attempts) ||
    !isOptionalNullableCanonicalStringV2(value.dispatch_lease_expires_at) ||
    !isOptionalNullableStringV2(value.dispatch_error_code) ||
    !isOptionalNullableCanonicalStringV2(value.promotion_idempotency_key) ||
    !isOptionalNullableCanonicalStringV2(value.promoted_at) ||
    !isCanonicalStringV2(value.created_at) ||
    !isCanonicalStringV2(value.updated_at)
  ) {
    throw sessionRunInputResponseInvalidV2();
  }
  const references = value.references.map((candidate) =>
    cloneReferenceV2(candidate, sessionRunInputResponseInvalidV2),
  );
  const contextItems = value.context_items.map((candidate) =>
    cloneContextItemV2(candidate, sessionRunInputResponseInvalidV2),
  );
  assertUniqueReferencesAndContextV2(
    references,
    contextItems,
    sessionRunInputResponseInvalidV2,
  );
  return Object.freeze({
    id: value.id,
    conversation_id: identity.session_id,
    run_id: runId,
    expected_run_revision: value.expected_run_revision,
    message_id: value.message_id,
    idempotency_key: value.idempotency_key,
    delivery: value.delivery as DesktopRunInput['delivery'],
    status: value.status as DesktopRunInput['status'],
    sequence: value.sequence,
    queue_position: value.queue_position,
    content: value.content,
    references: Object.freeze(references) as RunInputReference[],
    context_items: Object.freeze(contextItems) as ComposerContextItem[],
    applied_round: value.applied_round,
    applied_at: value.applied_at,
    ...(value.injected_via === undefined ? {} : { injected_via: value.injected_via }),
    ...(value.dispatch_status === undefined
      ? {}
      : { dispatch_status: value.dispatch_status as DesktopRunInput['dispatch_status'] }),
    ...(value.dispatch_attempts === undefined
      ? {}
      : { dispatch_attempts: value.dispatch_attempts }),
    ...(value.dispatch_lease_expires_at === undefined
      ? {}
      : { dispatch_lease_expires_at: value.dispatch_lease_expires_at }),
    ...(value.dispatch_error_code === undefined
      ? {}
      : { dispatch_error_code: value.dispatch_error_code }),
    ...(value.promotion_idempotency_key === undefined
      ? {}
      : { promotion_idempotency_key: value.promotion_idempotency_key }),
    ...(value.promoted_at === undefined ? {} : { promoted_at: value.promoted_at }),
    created_at: value.created_at,
    updated_at: value.updated_at,
  });
}

function cloneReferenceV2(
  value: unknown,
  errorFactory: () => RuntimeV2Error,
): RunInputReference {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, REFERENCE_KEYS_V2) ||
    value.type !== 'code_range' ||
    !isCanonicalStringV2(value.snapshot_id) ||
    !isCanonicalStringV2(value.environment_id) ||
    !isCanonicalStringV2(value.path) ||
    !isPositiveSafeIntegerV2(value.start_line) ||
    !isPositiveSafeIntegerV2(value.end_line) ||
    value.end_line < value.start_line ||
    (value.side !== 'old' && value.side !== 'new') ||
    !isCanonicalStringV2(value.patch_digest)
  ) {
    throw errorFactory();
  }
  return Object.freeze({
    type: 'code_range',
    snapshot_id: value.snapshot_id,
    environment_id: value.environment_id,
    path: value.path,
    start_line: value.start_line,
    end_line: value.end_line,
    side: value.side,
    patch_digest: value.patch_digest,
  });
}

function cloneContextItemV2(
  value: unknown,
  errorFactory: () => RuntimeV2Error,
): ComposerContextItem {
  if (
    !isPlainRecordV2(value) ||
    !hasRequiredAndOptionalKeysV2(value, CONTEXT_REQUIRED_KEYS_V2, CONTEXT_OPTIONAL_KEYS_V2) ||
    !CONTEXT_KINDS_V2.has(String(value.kind)) ||
    !isCanonicalStringV2(value.resource_id) ||
    !isCanonicalStringV2(value.label) ||
    !isOptionalNullablePrimitiveRecordV2(value.metadata)
  ) {
    throw errorFactory();
  }
  return Object.freeze({
    kind: value.kind as ComposerContextItem['kind'],
    resource_id: value.resource_id,
    label: value.label,
    ...(value.metadata === undefined || value.metadata === null
      ? {}
      : { metadata: clonePrimitiveRecordV2(value.metadata, errorFactory) }),
  });
}

function clonePromotionConversationV2(
  value: Record<string, unknown>,
  identity: DesktopSessionRunInputIdentityV2,
): DesktopSessionRunInputConversationProjectionV2 {
  const workspaceId = cloneWorkspaceIdV2(value.workspace_id);
  const currentMode = value.current_mode;
  if (
    value.id !== identity.session_id ||
    value.tenant_id !== identity.tenant_id ||
    value.project_id !== identity.project_id ||
    workspaceId !== identity.workspace_id ||
    !(
      currentMode === undefined ||
      currentMode === null ||
      RUNTIME_MODES_V2.has(String(currentMode))
    )
  ) {
    throw sessionRunInputResponseInvalidV2();
  }
  return Object.freeze({
    id: identity.session_id,
    tenant_id: identity.tenant_id,
    project_id: identity.project_id,
    workspace_id: identity.workspace_id,
    ...(currentMode === undefined
      ? {}
      : { current_mode: currentMode as AgentRuntimeMode | null }),
  });
}

function clonePromotionSourceRunV2(
  value: Record<string, unknown>,
  identity: DesktopSessionRunInputIdentityV2,
  runId: string,
  expectedRevision: number,
): DesktopSessionRunInputSourceRunProjectionV2 {
  if (
    value.id !== runId ||
    value.conversation_id !== identity.session_id ||
    value.project_id !== identity.project_id ||
    value.revision !== expectedRevision
  ) {
    throw sessionRunInputResponseInvalidV2();
  }
  return Object.freeze({
    id: runId,
    conversation_id: identity.session_id,
    project_id: identity.project_id,
    revision: expectedRevision,
  });
}

function assertUniqueReferencesAndContextV2(
  references: RunInputReference[],
  contextItems: ComposerContextItem[],
  errorFactory: () => RuntimeV2Error,
): void {
  const referenceKeys = references.map((reference) =>
    [
      reference.snapshot_id,
      reference.environment_id,
      reference.path,
      reference.start_line,
      reference.end_line,
      reference.side,
      reference.patch_digest,
    ].join('\u0000'),
  );
  const contextKeys = contextItems.map((item) => `${item.kind}\u0000${item.resource_id}`);
  if (
    new Set(referenceKeys).size !== referenceKeys.length ||
    new Set(contextKeys).size !== contextKeys.length
  ) {
    throw errorFactory();
  }
}

function clonePrimitiveRecordV2(
  value: unknown,
  errorFactory: () => RuntimeV2Error,
): Record<string, string | number | boolean | null> {
  if (!isPlainRecordV2(value)) throw errorFactory();
  const result: Record<string, string | number | boolean | null> = {};
  for (const [key, item] of Object.entries(value)) {
    if (
      key === '__proto__' ||
      key === 'constructor' ||
      key === 'prototype' ||
      !(
        item === null ||
        typeof item === 'string' ||
        typeof item === 'boolean' ||
        (typeof item === 'number' && Number.isFinite(item))
      )
    ) {
      throw errorFactory();
    }
    result[key] = item as string | number | boolean | null;
  }
  return Object.freeze(result);
}

function hasRequiredAndOptionalKeysV2(
  value: Record<string, unknown>,
  required: ReadonlySet<string>,
  optional: ReadonlySet<string>,
): boolean {
  return (
    [...required].every((key) => Object.hasOwn(value, key)) &&
    Object.keys(value).every((key) => required.has(key) || optional.has(key))
  );
}

function sameJsonV2(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function cloneWorkspaceIdV2(value: unknown): string | null | undefined {
  if (value === undefined || value === null || value === '') return null;
  return isCanonicalStringV2(value) ? value : undefined;
}

function isOptionalWorkspaceStringV2(value: unknown): value is string {
  return value === '' || isCanonicalStringV2(value);
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isNonemptyStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function isBoundedIdentifierV2(value: unknown, maxLength: number): value is string {
  return isCanonicalStringV2(value) && value.length <= maxLength;
}

function isPositiveSafeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 1;
}

function isNonnegativeSafeIntegerV2(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function isNullablePositiveSafeIntegerV2(value: unknown): value is number | null {
  return value === null || isPositiveSafeIntegerV2(value);
}

function isNullableNonnegativeSafeIntegerV2(value: unknown): value is number | null {
  return value === null || isNonnegativeSafeIntegerV2(value);
}

function isOptionalNonnegativeSafeIntegerV2(value: unknown): value is number | undefined {
  return value === undefined || isNonnegativeSafeIntegerV2(value);
}

function isNullableCanonicalStringV2(value: unknown): value is string | null {
  return value === null || isCanonicalStringV2(value);
}

function isOptionalNullableCanonicalStringV2(
  value: unknown,
): value is string | null | undefined {
  return value === undefined || isNullableCanonicalStringV2(value);
}

function isOptionalNullableStringV2(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === 'string';
}

function isOptionalDispatchStatusV2(value: unknown): boolean {
  return value === undefined || DISPATCH_STATUSES_V2.has(String(value));
}

function isOptionalNullablePrimitiveRecordV2(value: unknown): boolean {
  if (value === undefined || value === null) return true;
  try {
    clonePrimitiveRecordV2(value, sessionRunInputResponseInvalidV2);
    return true;
  } catch {
    return false;
  }
}
