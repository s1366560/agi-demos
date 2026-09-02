import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { DesktopApiClient } from '../api/client';
import type {
  AgentCapabilityMode,
  AgentConversation,
  CreateTaskSessionRequest,
  CreateTaskSessionResponse,
  DesktopRuntimeConfig,
  LlmRoutingRole,
} from '../types';
import {
  assertTaskSessionResponseV2,
  canonicalIdentifierV2,
  cloneRuntimeConfigV2,
  cloneTaskSessionRequestV2,
  isPlainRecordV2,
} from './desktopNewTaskFlowContractV2';

export type NewThreadAgentConfigV2 = Parameters<
  DesktopApiClient['createAgentConversation']
>[4];
export type NewThreadAgentExecutionV2 = Parameters<
  DesktopApiClient['runAgentMessage']
>[5];

export type ClonedAgentConversationArgumentsV2 = Readonly<{
  title: string;
  projectId: string;
  expectedUserId: string;
  capabilityMode?: AgentCapabilityMode;
  agentConfig?: NewThreadAgentConfigV2;
}>;

export type ClonedAgentMessageArgumentsV2 = Readonly<{
  conversationId: string;
  message: string;
  messageId?: string;
  projectId: string;
  workloadRole?: LlmRoutingRole;
  execution?: NewThreadAgentExecutionV2;
}>;

const CAPABILITY_MODES_V2 = new Set<AgentCapabilityMode>(['code', 'work']);
const ROUTING_ROLES_V2 = new Set<LlmRoutingRole>([
  'coding',
  'default',
  'fast',
  'vision',
]);

export function cloneNewThreadRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  try {
    return cloneRuntimeConfigV2(config);
  } catch {
    throw newThreadInputInvalidV2();
  }
}

export function cloneAgentConversationArgumentsV2(
  config: DesktopRuntimeConfig,
  title: unknown,
  projectId: unknown,
  expectedUserId: unknown,
  capabilityMode?: unknown,
  agentConfig?: unknown,
): ClonedAgentConversationArgumentsV2 {
  const checkedTitle = canonicalTextV2(title);
  const checkedProjectId = canonicalIdentifierV2(projectId);
  const checkedUserId = canonicalIdentifierV2(expectedUserId);
  if (config.workspaceId !== '' || checkedProjectId !== config.projectId) {
    throw newThreadScopeMismatchV2();
  }
  if (
    capabilityMode !== undefined &&
    !CAPABILITY_MODES_V2.has(capabilityMode as AgentCapabilityMode)
  ) {
    throw newThreadInputInvalidV2();
  }
  return Object.freeze({
    title: checkedTitle,
    projectId: checkedProjectId,
    expectedUserId: checkedUserId,
    ...(capabilityMode === undefined
      ? {}
      : { capabilityMode: capabilityMode as AgentCapabilityMode }),
    ...(agentConfig === undefined
      ? {}
      : { agentConfig: cloneAgentConfigV2(agentConfig) }),
  });
}

export function cloneTaskSessionArgumentsV2(
  config: DesktopRuntimeConfig,
  input: unknown,
): CreateTaskSessionRequest {
  let request: CreateTaskSessionRequest;
  try {
    request = cloneTaskSessionRequestV2(input);
  } catch {
    throw newThreadInputInvalidV2();
  }
  if (
    request.workspace.kind === 'existing' &&
    config.workspaceId !== '' &&
    request.workspace.workspace_id !== config.workspaceId
  ) {
    throw newThreadScopeMismatchV2();
  }
  return request;
}

export function cloneAgentMessageArgumentsV2(
  config: DesktopRuntimeConfig,
  conversationId: unknown,
  message: unknown,
  messageId?: unknown,
  projectId?: unknown,
  workloadRole?: unknown,
  execution?: unknown,
): ClonedAgentMessageArgumentsV2 {
  const checkedProjectId =
    projectId === undefined
      ? config.projectId
      : canonicalIdentifierV2(projectId);
  if (checkedProjectId !== config.projectId) throw newThreadScopeMismatchV2();
  if (
    workloadRole !== undefined &&
    !ROUTING_ROLES_V2.has(workloadRole as LlmRoutingRole)
  ) {
    throw newThreadInputInvalidV2();
  }
  return Object.freeze({
    conversationId: canonicalIdentifierV2(conversationId),
    message: canonicalTextV2(message),
    ...(messageId === undefined
      ? {}
      : { messageId: canonicalIdentifierV2(messageId) }),
    projectId: checkedProjectId,
    ...(workloadRole === undefined
      ? {}
      : { workloadRole: workloadRole as LlmRoutingRole }),
    ...(execution === undefined
      ? {}
      : { execution: cloneAgentExecutionV2(execution) }),
  });
}

export function assertUnboundAgentConversationV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  expected: ClonedAgentConversationArgumentsV2,
): AgentConversation {
  if (
    !isPlainRecordV2(value) ||
    !canonicalIdentifierOrNullV2(value.id) ||
    value.tenant_id !== config.tenantId ||
    value.project_id !== config.projectId ||
    value.user_id !== expected.expectedUserId ||
    value.title !== expected.title ||
    value.workspace_id !== null ||
    !canonicalIdentifierOrNullV2(value.status) ||
    !Number.isSafeInteger(value.message_count) ||
    Number(value.message_count) < 0 ||
    !canonicalIdentifierOrNullV2(value.created_at)
  ) {
    throw newThreadResponseInvalidV2();
  }
  return deepFreezeV2(cloneValueV2(value)) as unknown as AgentConversation;
}

export function assertNewThreadTaskSessionResponseV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  request: CreateTaskSessionRequest,
): CreateTaskSessionResponse {
  let response: CreateTaskSessionResponse;
  try {
    response = assertTaskSessionResponseV2(value, config);
  } catch {
    throw newThreadResponseInvalidV2();
  }
  if (
    request.workspace.kind === 'existing' &&
    response.workspace.id !== request.workspace.workspace_id
  ) {
    throw newThreadResponseInvalidV2();
  }
  return response;
}

export function assertQueuedAgentMessageV2(
  value: unknown,
): Readonly<{ queued: boolean }> {
  if (!isPlainRecordV2(value) || typeof value.queued !== 'boolean') {
    throw newThreadResponseInvalidV2();
  }
  return Object.freeze({ queued: value.queued });
}

export function newThreadInputInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_new_thread_creation_input_invalid',
    'desktop new-thread creation authority received invalid input',
  );
}

export function newThreadScopeMismatchV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_new_thread_creation_scope_mismatch',
    'desktop new-thread creation operation does not match its configured scope',
  );
}

export function isNewThreadPlainRecordV2(
  value: unknown,
): value is Record<string, unknown> {
  return isPlainRecordV2(value);
}

function cloneAgentConfigV2(value: unknown): NewThreadAgentConfigV2 {
  if (!isPlainRecordV2(value)) throw newThreadInputInvalidV2();
  const allowed = new Set(['llm_model_override', 'llm_route_override']);
  if (Object.keys(value).some((key) => !allowed.has(key)))
    throw newThreadInputInvalidV2();
  const model = value.llm_model_override;
  const route = value.llm_route_override;
  if (
    model !== undefined &&
    model !== null &&
    !canonicalIdentifierOrNullV2(model)
  ) {
    throw newThreadInputInvalidV2();
  }
  if (route !== undefined && route !== null) {
    if (
      !isPlainRecordV2(route) ||
      Object.keys(route).some(
        (key) => key !== 'provider_id' && key !== 'model_id',
      ) ||
      !canonicalIdentifierOrNullV2(route.provider_id) ||
      !canonicalIdentifierOrNullV2(route.model_id)
    ) {
      throw newThreadInputInvalidV2();
    }
  }
  return deepFreezeV2(cloneValueV2(value)) as NewThreadAgentConfigV2;
}

function cloneAgentExecutionV2(value: unknown): NewThreadAgentExecutionV2 {
  if (!isPlainRecordV2(value)) throw newThreadInputInvalidV2();
  const copy: Record<string, string> = {};
  for (const [sourceKey, targetKey] of [
    ['agentId', 'agentId'],
    ['forcedSkillName', 'forcedSkillName'],
    ['subAgentId', 'subAgentId'],
  ] as const) {
    const candidate = value[sourceKey];
    if (candidate === undefined) continue;
    if (!canonicalIdentifierOrNullV2(candidate))
      throw newThreadInputInvalidV2();
    copy[targetKey] = candidate;
  }
  return Object.freeze(copy) as NewThreadAgentExecutionV2;
}

function canonicalTextV2(value: unknown): string {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw newThreadInputInvalidV2();
  }
  return value;
}

function canonicalIdentifierOrNullV2(value: unknown): value is string {
  return (
    typeof value === 'string' && value.length > 0 && value === value.trim()
  );
}

function cloneValueV2<T>(value: T): T {
  try {
    return structuredClone(value);
  } catch {
    throw newThreadInputInvalidV2();
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

function newThreadResponseInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_new_thread_creation_response_invalid',
    'desktop new-thread creation authority returned an invalid response',
  );
}
