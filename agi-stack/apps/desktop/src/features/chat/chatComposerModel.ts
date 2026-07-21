import type {
  AgentInputFileMetadata,
  ComposerContextItem,
  WorkspaceMessage,
} from '../../types';

export type ChatComposerVariant = 'workspace' | 'session';

export type ComposerAgentExecutionContext = {
  message: string;
  mentions: string[];
  agentId?: string;
  forcedSkillName?: string;
  fileMetadata?: AgentInputFileMetadata[];
  appModelContext?: {
    desktop_composer_context: {
      resources: Array<Pick<ComposerContextItem, 'kind' | 'resource_id'>>;
    };
  };
};

export type ChatComposerPresentation = Readonly<{
  placeholderKey: 'session.steerComposerPlaceholder' | null;
  showCommands: boolean;
  showPaneHeader: boolean;
  showQueueHandoff: boolean;
  showRuntimeControls: boolean;
  showRuntimeStatus: boolean;
  showWorkflowStrip: boolean;
}>;

const SESSION_COMPOSER_PRESENTATION: ChatComposerPresentation = Object.freeze({
  placeholderKey: 'session.steerComposerPlaceholder',
  showCommands: false,
  showPaneHeader: false,
  showQueueHandoff: true,
  showRuntimeControls: false,
  showRuntimeStatus: false,
  showWorkflowStrip: false,
});

const WORKSPACE_COMPOSER_PRESENTATION: ChatComposerPresentation = Object.freeze({
  placeholderKey: null,
  showCommands: true,
  showPaneHeader: true,
  showQueueHandoff: false,
  showRuntimeControls: true,
  showRuntimeStatus: true,
  showWorkflowStrip: true,
});

export function chatComposerPresentation(
  variant: ChatComposerVariant,
): ChatComposerPresentation {
  return variant === 'session'
    ? SESSION_COMPOSER_PRESENTATION
    : WORKSPACE_COMPOSER_PRESENTATION;
}

export function composerMentionIds(contextItems: readonly ComposerContextItem[]): string[] {
  const seen = new Set<string>();
  const mentions: string[] = [];
  for (const item of contextItems) {
    if (item.kind !== 'agent' || item.metadata?.mention_target !== true) continue;
    const agentId = item.resource_id.trim();
    if (!agentId || seen.has(agentId)) continue;
    seen.add(agentId);
    mentions.push(agentId);
  }
  return mentions;
}

export function composerFileMetadata(
  contextItems: readonly ComposerContextItem[],
): AgentInputFileMetadata[] {
  const files: AgentInputFileMetadata[] = [];
  for (const item of contextItems) {
    if (item.kind !== 'attachment') continue;
    const filename = metadataText(item, 'filename');
    const sandboxPath = metadataText(item, 'sandbox_path');
    const mimeType = metadataText(item, 'mime_type');
    const sizeBytes = item.metadata?.size_bytes;
    if (
      !filename ||
      !sandboxPath ||
      !mimeType ||
      typeof sizeBytes !== 'number' ||
      !Number.isSafeInteger(sizeBytes) ||
      sizeBytes < 0
    ) {
      continue;
    }
    files.push({
      filename,
      sandbox_path: sandboxPath,
      mime_type: mimeType,
      size_bytes: sizeBytes,
    });
  }
  return files;
}

export function composerHasSendableAttachment(
  contextItems: readonly ComposerContextItem[],
): boolean {
  return composerFileMetadata(contextItems).length > 0;
}

export function appendComposerContextItem(
  current: ComposerContextItem[],
  item: ComposerContextItem,
): ComposerContextItem[] {
  const duplicate = current.find(
    (candidate) => candidate.kind === item.kind && candidate.resource_id === item.resource_id,
  );
  if (duplicate) return current;
  const executionSlot = metadataText(item, 'execution_slot');
  return [
    ...current.filter(
      (candidate) => !executionSlot || metadataText(candidate, 'execution_slot') !== executionSlot,
    ),
    item,
  ];
}

export function composerAgentExecutionContext(
  rawMessage: string,
  contextItems: readonly ComposerContextItem[],
): ComposerAgentExecutionContext {
  const agentId = lastExecutionMetadata(contextItems, 'agent', 'execution_agent_id');
  const forcedSkillName = lastExecutionMetadata(
    contextItems,
    'skill',
    'execution_skill_name',
  );
  const subAgentName = lastExecutionMetadata(
    contextItems,
    'subagent',
    'execution_subagent_name',
  );
  const command = lastExecutionResourceId(contextItems, 'command');
  const content = rawMessage.trim();
  const fileMetadata = composerFileMetadata(contextItems);
  const commandMessage = command ? `${command} ${content}` : content;
  const message = subAgentName
    ? `[System Instruction: Delegate this task strictly to SubAgent ${JSON.stringify(
        subAgentName,
      )}]\n${commandMessage}`
    : commandMessage;
  const resources = contextItems
    .filter(
      (item) =>
        item.kind !== 'attachment' && item.kind !== 'command' && item.resource_id.trim(),
    )
    .map((item) => ({ kind: item.kind, resource_id: item.resource_id.trim() }));
  return {
    message,
    mentions: composerMentionIds(contextItems),
    ...(agentId ? { agentId } : {}),
    ...(forcedSkillName ? { forcedSkillName } : {}),
    ...(fileMetadata.length ? { fileMetadata } : {}),
    ...(resources.length
      ? { appModelContext: { desktop_composer_context: { resources } } }
      : {}),
  };
}

export function workspaceMessageRequiresDefaultAgentLaunch(
  message: Pick<WorkspaceMessage, 'mentions'>,
): boolean {
  return !message.mentions?.length;
}

function lastExecutionMetadata(
  contextItems: readonly ComposerContextItem[],
  executionSlot: string,
  metadataKey: string,
): string {
  for (let index = contextItems.length - 1; index >= 0; index -= 1) {
    const item = contextItems[index];
    if (metadataText(item, 'execution_slot') !== executionSlot) continue;
    const value = metadataText(item, metadataKey);
    if (value) return value;
  }
  return '';
}

function lastExecutionResourceId(
  contextItems: readonly ComposerContextItem[],
  executionSlot: string,
): string {
  for (let index = contextItems.length - 1; index >= 0; index -= 1) {
    const item = contextItems[index];
    if (metadataText(item, 'execution_slot') !== executionSlot) continue;
    const value = item.resource_id.trim();
    if (value) return value;
  }
  return '';
}

function metadataText(item: ComposerContextItem, key: string): string {
  const value = item.metadata?.[key];
  return typeof value === 'string' ? value.trim() : '';
}
