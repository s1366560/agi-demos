import type { AgentConversation } from '../../types';
import type { AutomationConversationChoice } from './automationConversationModel';

type NavigationState = Readonly<{
  tenantId: string;
  projectId: string;
  contextRevision: number;
  scopeEpoch: number;
  conversations: readonly AgentConversation[];
}>;

export function createAutomationConversationOpener({
  current,
  open,
  unavailable,
}: {
  current: () => NavigationState;
  open: (
    projectId: string,
    workspaceId: string,
    conversation: AgentConversation,
    view: 'chat',
  ) => void;
  unavailable: () => void;
}): (choice: AutomationConversationChoice) => void {
  const { tenantId, projectId, contextRevision, scopeEpoch } = current();
  return (choice) => {
    const state = current();
    if (
      state.tenantId !== tenantId ||
      state.projectId !== projectId ||
      state.contextRevision !== contextRevision ||
      state.scopeEpoch !== scopeEpoch
    )
      return;
    const conversation = state.conversations.find(
      (candidate) =>
        candidate.id === choice.id &&
        candidate.tenant_id === tenantId &&
        candidate.project_id === projectId &&
        candidate.workspace_id === choice.workspaceId &&
        Boolean(choice.workspaceId.trim()),
    );
    if (!conversation) {
      unavailable();
      return;
    }
    open(projectId, choice.workspaceId, conversation, 'chat');
  };
}
