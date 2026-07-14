import type { AgentConversation, WorkspaceSummary } from '../../types';

export type WorkspaceTreeNode = {
  workspace: WorkspaceSummary;
  conversations: AgentConversation[];
};

export function buildWorkspaceTree(
  workspaces: WorkspaceSummary[],
  conversationsByWorkspace: Record<string, AgentConversation[]>,
  groupMode: 'project' | 'recent',
): WorkspaceTreeNode[] {
  if (groupMode === 'recent') {
    return [...workspaces]
      .sort(
        (left, right) =>
          latestWorkspaceTimestamp(right, conversationsByWorkspace) -
          latestWorkspaceTimestamp(left, conversationsByWorkspace),
      )
      .map((workspace) => ({
        workspace,
        conversations: [...(conversationsByWorkspace[workspace.id] ?? [])].sort(
          (left, right) => timestamp(right.updated_at) - timestamp(left.updated_at),
        ),
      }));
  }

  return workspaces.map((workspace) => ({
    workspace,
    conversations: conversationsByWorkspace[workspace.id] ?? [],
  }));
}

function latestWorkspaceTimestamp(
  workspace: WorkspaceSummary,
  conversationsByWorkspace: Record<string, AgentConversation[]>,
): number {
  return Math.max(
    timestamp(workspace.updated_at),
    timestamp(workspace.created_at),
    0,
    ...(conversationsByWorkspace[workspace.id] ?? []).map((conversation) =>
      timestamp(conversation.updated_at ?? conversation.created_at),
    ),
  );
}

function timestamp(value: string | null | undefined): number {
  return value ? Date.parse(value) || 0 : 0;
}
