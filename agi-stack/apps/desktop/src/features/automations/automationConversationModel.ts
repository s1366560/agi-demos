import type { AgentConversation, AutomationJob } from '../../types';

export type AutomationConversationChoice = Readonly<{
  id: string;
  title: string;
  workspaceId: string;
}>;

export const EMPTY_AUTOMATION_CONVERSATIONS: readonly AutomationConversationChoice[] =
  Object.freeze([]);

export function automationConversationChoices(
  conversations: readonly AgentConversation[],
  scope: Readonly<{ tenantId: string; projectId: string }>,
): readonly AutomationConversationChoice[] {
  return Object.freeze(
    conversations
      .filter(
        (conversation) =>
          conversation.tenant_id === scope.tenantId &&
          conversation.project_id === scope.projectId &&
          Boolean(conversation.workspace_id?.trim()),
      )
      .map((conversation) =>
        Object.freeze({
          id: conversation.id,
          title: conversation.title || conversation.id,
          workspaceId: conversation.workspace_id!,
        }),
      ),
  );
}

export function automationConversationBinding(
  mode: 'fresh' | 'reuse',
  selectedId: string,
  choices: readonly AutomationConversationChoice[],
  job: Pick<AutomationJob, 'conversation_id' | 'workspace_id'> | null,
): { conversation_id?: string; workspace_id?: string } | null {
  if (mode === 'fresh') return {};
  const selected = choices.find((choice) => choice.id === selectedId);
  if (selected) {
    return { conversation_id: selected.id, workspace_id: selected.workspaceId };
  }
  // Preserve a persisted binding while its conversation is outside the loaded
  // catalog. The execution authority still validates its current scope/access.
  if (selectedId && job?.conversation_id === selectedId) {
    return {
      conversation_id: selectedId,
      ...(job.workspace_id ? { workspace_id: job.workspace_id } : {}),
    };
  }
  return null;
}
