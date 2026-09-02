import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { DesktopApiClient } from '../api/client';
import type {
  AgentPlanMode,
  AgentPlanModeResponse,
  AgentPlanTaskListResponse,
  ApprovePlanAndStartRequest,
  ApprovePlanAndStartResponse,
  ComposerContextItem,
  ConversationMessagesResponse,
  CreateTaskSessionRequest,
  CreateTaskSessionResponse,
  DesktopRuntimeConfig,
  WorkspaceMessage,
  WorkspaceSummary,
} from '../types';

export type ConversationMessageOptionsV2 = Parameters<
  DesktopApiClient['getConversationMessages']
>[2];

export type ClonedMessageArgumentsV2 = Readonly<{
  content: string;
  parentMessageId?: string;
  contextItems: ComposerContextItem[];
  mentions: string[];
}>;

export type ClonedConversationArgumentsV2 = Readonly<{
  conversationId: string;
  projectId: string;
  options: ConversationMessageOptionsV2;
}>;

const CAPABILITY_MODES_V2 = new Set(['code', 'work']);
const COLLABORATION_MODES_V2 = new Set([
  'autonomous',
  'multi_agent_isolated',
  'multi_agent_shared',
  'single_agent',
]);
const ENVIRONMENT_KINDS_V2 = new Set(['local', 'worktree']);
const PERMISSION_PROFILES_V2 = new Set(['full_access', 'read_only', 'workspace_write']);
const PLAN_MODES_V2 = new Set(['build', 'plan']);
const USE_CASES_V2 = new Set([
  'conversation',
  'general',
  'operations',
  'programming',
  'research',
]);
const IDEMPOTENCY_KEY_V2 = /^[A-Za-z0-9._:-]{8,256}$/u;

export function cloneRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidInputV2();
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
    throw invalidInputV2();
  }
  return Object.freeze(copy);
}

export function cloneTaskSessionRequestV2(value: unknown): CreateTaskSessionRequest {
  const copy = cloneJsonV2(value);
  if (
    !isPlainRecordV2(copy) ||
    !validIdempotencyKeyV2(copy.idempotency_key) ||
    !isPlainRecordV2(copy.workspace) ||
    !isPlainRecordV2(copy.conversation) ||
    !isPlainRecordV2(copy.initial_message) ||
    !isCanonicalStringV2(copy.conversation.title) ||
    !CAPABILITY_MODES_V2.has(String(copy.conversation.capability_mode)) ||
    typeof copy.initial_message.content !== 'string' ||
    copy.initial_message.content.trim().length === 0
  ) {
    throw invalidInputV2();
  }
  if (
    (copy.workspace.kind === 'existing' &&
      !isCanonicalStringV2(copy.workspace.workspace_id)) ||
    (copy.workspace.kind === 'create' &&
      (!isCanonicalStringV2(copy.workspace.name) ||
        !USE_CASES_V2.has(String(copy.workspace.use_case)) ||
        !COLLABORATION_MODES_V2.has(String(copy.workspace.collaboration_mode)))) ||
    (copy.workspace.kind !== 'existing' && copy.workspace.kind !== 'create')
  ) {
    throw invalidInputV2();
  }
  return deepFreezeV2(copy) as unknown as CreateTaskSessionRequest;
}

export function cloneApprovalRequestV2(
  config: DesktopRuntimeConfig,
  value: unknown,
): ApprovePlanAndStartRequest {
  const copy = cloneJsonV2(value);
  if (
    !isPlainRecordV2(copy) ||
    !isCanonicalStringV2(copy.conversationId) ||
    !isCanonicalStringV2(copy.projectId) ||
    !isCanonicalStringV2(copy.planVersionId) ||
    !Number.isSafeInteger(copy.expectedPlanVersion) ||
    Number(copy.expectedPlanVersion) < 1 ||
    !PERMISSION_PROFILES_V2.has(String(copy.permissionProfile)) ||
    typeof copy.message !== 'string' ||
    copy.message.trim().length === 0 ||
    !isCanonicalStringV2(copy.messageId) ||
    !validIdempotencyKeyV2(copy.idempotencyKey) ||
    !ENVIRONMENT_KINDS_V2.has(String(copy.environmentKind))
  ) {
    throw invalidInputV2();
  }
  if (copy.projectId !== config.projectId) throw scopeMismatchV2();
  return deepFreezeV2(copy) as unknown as ApprovePlanAndStartRequest;
}

export function cloneMessageArgumentsV2(
  config: DesktopRuntimeConfig,
  content: unknown,
  parentMessageId: unknown,
  contextItems: unknown = [],
  mentions: unknown = [],
): ClonedMessageArgumentsV2 {
  if (
    !isCanonicalStringV2(config.workspaceId) ||
    typeof content !== 'string' ||
    content.trim().length === 0 ||
    (parentMessageId !== undefined && !isCanonicalStringV2(parentMessageId)) ||
    !Array.isArray(contextItems) ||
    !Array.isArray(mentions) ||
    !mentions.every(isCanonicalStringV2)
  ) {
    throw invalidInputV2();
  }
  const clonedContextItems = cloneJsonV2(contextItems);
  if (!Array.isArray(clonedContextItems)) throw invalidInputV2();
  return Object.freeze({
    content,
    ...(parentMessageId === undefined ? {} : { parentMessageId }),
    contextItems: deepFreezeV2(clonedContextItems) as unknown as ComposerContextItem[],
    mentions: Object.freeze([...mentions]) as unknown as string[],
  });
}

export function cloneConversationArgumentsV2(
  config: DesktopRuntimeConfig,
  conversationId: unknown,
  projectId: unknown,
  options: unknown = {},
): ClonedConversationArgumentsV2 {
  const checkedConversationId = canonicalIdentifierV2(conversationId);
  const checkedProjectId =
    projectId === undefined ? config.projectId : canonicalIdentifierV2(projectId);
  if (checkedProjectId !== config.projectId) throw scopeMismatchV2();
  if (!isPlainRecordV2(options)) throw invalidInputV2();
  for (const key of ['limit', 'fromTimeUs', 'fromCounter', 'beforeTimeUs', 'beforeCounter']) {
    const candidate = options[key];
    if (candidate !== undefined && (!Number.isSafeInteger(candidate) || Number(candidate) < 0)) {
      throw invalidInputV2();
    }
  }
  const signal = cloneSignalV2(options.signal);
  return Object.freeze({
    conversationId: checkedConversationId,
    projectId: checkedProjectId,
    options: Object.freeze({
      ...(options.limit === undefined ? {} : { limit: Number(options.limit) }),
      ...(options.fromTimeUs === undefined ? {} : { fromTimeUs: Number(options.fromTimeUs) }),
      ...(options.fromCounter === undefined ? {} : { fromCounter: Number(options.fromCounter) }),
      ...(options.beforeTimeUs === undefined ? {} : { beforeTimeUs: Number(options.beforeTimeUs) }),
      ...(options.beforeCounter === undefined ? {} : { beforeCounter: Number(options.beforeCounter) }),
      ...(signal === undefined ? {} : { signal }),
    }),
  });
}

export function assertWorkspaceListV2(
  value: unknown,
  config: DesktopRuntimeConfig,
): WorkspaceSummary[] {
  if (!Array.isArray(value)) throw invalidResponseV2();
  for (const item of value) {
    if (
      !isPlainRecordV2(item) ||
      !isCanonicalStringV2(item.id) ||
      (item.tenant_id !== undefined && item.tenant_id !== config.tenantId) ||
      (item.project_id !== undefined && item.project_id !== config.projectId)
    ) {
      throw invalidResponseV2();
    }
  }
  return deepFreezeV2(cloneJsonV2(value)) as unknown as WorkspaceSummary[];
}

export function assertCapabilityV2(value: unknown): boolean {
  if (typeof value !== 'boolean') throw invalidResponseV2();
  return value;
}

export function assertTaskSessionResponseV2(
  value: unknown,
  config: DesktopRuntimeConfig,
): CreateTaskSessionResponse {
  if (
    !isPlainRecordV2(value) ||
    typeof value.replayed !== 'boolean' ||
    !isPlainRecordV2(value.workspace) ||
    !isCanonicalStringV2(value.workspace.id) ||
    value.workspace.tenant_id !== config.tenantId ||
    value.workspace.project_id !== config.projectId ||
    !isPlainRecordV2(value.conversation) ||
    !isCanonicalStringV2(value.conversation.id) ||
    value.conversation.tenant_id !== config.tenantId ||
    value.conversation.project_id !== config.projectId ||
    value.conversation.workspace_id !== value.workspace.id ||
    !isPlainRecordV2(value.initial_message) ||
    !isCanonicalStringV2(value.initial_message.id) ||
    value.initial_message.workspace_id !== value.workspace.id
  ) {
    throw invalidResponseV2();
  }
  return deepFreezeV2(cloneJsonV2(value)) as unknown as CreateTaskSessionResponse;
}

export function assertMessageResponseV2(
  value: unknown,
  config: DesktopRuntimeConfig,
): WorkspaceMessage {
  if (
    !isPlainRecordV2(value) ||
    !isCanonicalStringV2(value.id) ||
    value.workspace_id !== config.workspaceId ||
    typeof value.content !== 'string'
  ) {
    throw invalidResponseV2();
  }
  return deepFreezeV2(cloneJsonV2(value)) as unknown as WorkspaceMessage;
}

export function assertTimelineResponseV2(
  value: unknown,
  conversationId: string,
): ConversationMessagesResponse {
  if (
    !isPlainRecordV2(value) ||
    value.conversationId !== conversationId ||
    !Array.isArray(value.timeline) ||
    !Number.isSafeInteger(value.total) ||
    Number(value.total) < 0 ||
    typeof value.has_more !== 'boolean'
  ) {
    throw invalidResponseV2();
  }
  return deepFreezeV2(cloneJsonV2(value)) as unknown as ConversationMessagesResponse;
}

export function assertPlanTasksResponseV2(
  value: unknown,
  conversationId: string,
): AgentPlanTaskListResponse {
  if (
    !isPlainRecordV2(value) ||
    value.conversation_id !== conversationId ||
    !Array.isArray(value.tasks) ||
    !Number.isSafeInteger(value.total_count) ||
    Number(value.total_count) < 0 ||
    value.tasks.some(
      (task) => !isPlainRecordV2(task) || task.conversation_id !== conversationId,
    ) ||
    (value.plan_version !== undefined &&
      value.plan_version !== null &&
      (!isPlainRecordV2(value.plan_version) ||
        value.plan_version.conversation_id !== conversationId))
  ) {
    throw invalidResponseV2();
  }
  return deepFreezeV2(cloneJsonV2(value)) as unknown as AgentPlanTaskListResponse;
}

export function assertPlanModeResponseV2(
  value: unknown,
  conversationId: string,
  mode: AgentPlanMode,
): AgentPlanModeResponse {
  if (!isPlainRecordV2(value) || value.conversation_id !== conversationId || value.mode !== mode) {
    throw invalidResponseV2();
  }
  return deepFreezeV2(cloneJsonV2(value)) as unknown as AgentPlanModeResponse;
}

export function assertApprovalResponseV2(
  value: unknown,
  request: ApprovePlanAndStartRequest,
): ApprovePlanAndStartResponse {
  if (
    !isPlainRecordV2(value) ||
    typeof value.queued !== 'boolean' ||
    typeof value.created !== 'boolean' ||
    !isPlainRecordV2(value.conversation) ||
    value.conversation.id !== request.conversationId ||
    value.conversation.project_id !== request.projectId ||
    !isPlainRecordV2(value.plan_version) ||
    value.plan_version.id !== request.planVersionId ||
    value.plan_version.conversation_id !== request.conversationId ||
    value.plan_version.version !== request.expectedPlanVersion ||
    !isPlainRecordV2(value.run) ||
    value.run.conversation_id !== request.conversationId ||
    value.run.project_id !== request.projectId ||
    value.run.plan_version_id !== request.planVersionId
  ) {
    throw invalidResponseV2();
  }
  return deepFreezeV2(cloneJsonV2(value)) as unknown as ApprovePlanAndStartResponse;
}

export function assertPlanModeInputV2(value: unknown): AgentPlanMode {
  if (typeof value !== 'string' || !PLAN_MODES_V2.has(value)) throw invalidInputV2();
  return value as AgentPlanMode;
}

export function cloneSignalV2(value: unknown): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw invalidInputV2();
  }
  return value;
}

export function canonicalIdentifierV2(value: unknown): string {
  if (!isCanonicalStringV2(value) || value.length > 256) throw invalidInputV2();
  return value;
}

export function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_new_task_flow_input_invalid',
    'desktop new-task flow operation input is invalid',
  );
}

export function scopeMismatchV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_new_task_flow_scope_mismatch',
    'desktop new-task flow operation differs from its configured scope',
  );
}

function invalidResponseV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_new_task_flow_response_invalid',
    'desktop new-task flow authority returned an invalid response',
  );
}

function validIdempotencyKeyV2(value: unknown): value is string {
  return typeof value === 'string' && IDEMPOTENCY_KEY_V2.test(value);
}

function cloneJsonV2<T>(value: T): T {
  try {
    return structuredClone(value);
  } catch {
    throw invalidInputV2();
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

export function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}
