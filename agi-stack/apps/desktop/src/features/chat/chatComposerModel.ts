import type { ComposerContextItem, WorkspaceMessage } from '../../types';

export type ChatComposerVariant = 'workspace' | 'session';

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

export function workspaceMessageRequiresDefaultAgentLaunch(
  message: Pick<WorkspaceMessage, 'mentions'>,
): boolean {
  return !message.mentions?.length;
}
