import { RuntimeV2Error } from '@agistack/plugin-runtime';
import type { AgentConversation, DesktopRuntimeConfig } from '../types';
import { canonicalIdentifierV2, isPlainRecordV2 } from './desktopNewTaskFlowContractV2';

export function cloneMessagingJsonV2<T>(value: T): T {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return Object.freeze(value.map(cloneMessagingJsonV2)) as T;
  if (!isPlainRecordV2(value)) throw bindingErrorV2('input_invalid');
  const copy: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (item !== undefined) copy[key] = cloneMessagingJsonV2(item);
  }
  return Object.freeze(copy) as T;
}

export function cloneMessagingConversationV2(
  value: AgentConversation,
  config: DesktopRuntimeConfig,
  allowUnbound = false,
): AgentConversation {
  if (!isPlainRecordV2(value)) throw bindingErrorV2('scope_mismatch');
  canonicalIdentifierV2(value.id);
  canonicalIdentifierV2(value.user_id);
  if (
    value.tenant_id !== config.tenantId ||
    value.project_id !== config.projectId ||
    !(
      value.workspace_id === (config.workspaceId || null) ||
      (allowUnbound && value.workspace_id === null)
    )
  )
    throw bindingErrorV2('scope_mismatch');
  return cloneMessagingJsonV2(value);
}

export function requireConversationWorkspaceBindingV2(
  value: unknown,
  config: DesktopRuntimeConfig,
  expected: AgentConversation,
): AgentConversation {
  if (
    !isPlainRecordV2(value) ||
    value.id !== expected.id ||
    value.user_id !== expected.user_id ||
    value.tenant_id !== config.tenantId ||
    value.project_id !== config.projectId ||
    value.workspace_id !== config.workspaceId ||
    typeof value.title !== 'string' ||
    typeof value.status !== 'string' ||
    !Number.isSafeInteger(value.message_count) ||
    Number(value.message_count) < 0 ||
    typeof value.created_at !== 'string'
  )
    throw bindingErrorV2('response_invalid');
  return cloneMessagingJsonV2(value) as unknown as AgentConversation;
}

function bindingErrorV2(reason: string): RuntimeV2Error {
  return new RuntimeV2Error(`desktop_conversation_workspace_binding_${reason}`, reason);
}
