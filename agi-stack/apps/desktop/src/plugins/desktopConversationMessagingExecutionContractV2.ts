import { RuntimeV2Error } from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import type { NewThreadAgentExecutionV2 } from './desktopNewThreadCreationContractV2';
import { cloneMessagingJsonV2 } from './desktopConversationWorkspaceBindingContractV2';

export type ConversationMessagingExecutionV2 = NewThreadAgentExecutionV2 &
  Readonly<{
    mentions?: readonly string[];
    fileMetadata?: readonly unknown[];
    appModelContext?: unknown;
    permissionPreset?: 'default' | 'relaxed' | 'full';
    message?: string;
  }>;
export function assertLocalMessagingExecutionV2(
  config: DesktopRuntimeConfig,
  execution: ConversationMessagingExecutionV2,
): void {
  if (config.mode === 'local') requireHttpExecutionV2(cloneMessagingJsonV2(execution));
}

export function requireHttpExecutionV2(
  execution: ConversationMessagingExecutionV2 | undefined,
): NewThreadAgentExecutionV2 | undefined {
  if (execution === undefined) return undefined;
  if (
    typeof execution !== 'object' ||
    execution === null ||
    Array.isArray(execution) ||
    (execution.mentions !== undefined &&
      (!Array.isArray(execution.mentions) ||
        execution.mentions.some((value) => typeof value !== 'string'))) ||
    (execution.fileMetadata !== undefined && !Array.isArray(execution.fileMetadata)) ||
    (execution.message !== undefined && typeof execution.message !== 'string')
  )
    throw messagingErrorV2('input_invalid');
  if (
    (execution.mentions?.length ?? 0) > 0 ||
    (execution.fileMetadata?.length ?? 0) > 0 ||
    execution.appModelContext != null
  ) {
    throw new RuntimeV2Error(
      'local_conversation_message_context_unsupported',
      'HTTP conversation messages do not support composer context',
    );
  }
  if (execution.permissionPreset !== undefined && execution.permissionPreset !== 'default') {
    throw new RuntimeV2Error(
      'local_conversation_message_permission_unsupported',
      'HTTP conversation messages do not support permission overrides',
    );
  }
  const allowed = new Set([
    'agentId',
    'forcedSkillName',
    'subAgentId',
    'mentions',
    'fileMetadata',
    'appModelContext',
    'permissionPreset',
    'message',
  ]);
  if (Object.keys(execution).some((key) => !allowed.has(key)))
    throw messagingErrorV2('input_invalid');
  return Object.freeze({
    ...(execution.agentId === undefined ? {} : { agentId: execution.agentId }),
    ...(execution.forcedSkillName === undefined
      ? {}
      : { forcedSkillName: execution.forcedSkillName }),
    ...(execution.subAgentId === undefined ? {} : { subAgentId: execution.subAgentId }),
  });
}
function messagingErrorV2(suffix: string): RuntimeV2Error {
  return new RuntimeV2Error(`desktop_conversation_messaging_${suffix}`, suffix);
}
