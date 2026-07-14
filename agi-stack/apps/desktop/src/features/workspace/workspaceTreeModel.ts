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
  return [...workspaces]
    .sort((left, right) => compareWorkspaces(left, right, conversationsByWorkspace, groupMode))
    .map((workspace) => ({
      workspace,
      conversations: sortConversations(conversationsByWorkspace[workspace.id] ?? [], groupMode),
    }));
}

function compareWorkspaces(
  left: WorkspaceSummary,
  right: WorkspaceSummary,
  conversationsByWorkspace: Record<string, AgentConversation[]>,
  groupMode: 'project' | 'recent',
): number {
  if (groupMode === 'recent') {
    return (
      latestWorkspaceTimestamp(right, conversationsByWorkspace) -
      latestWorkspaceTimestamp(left, conversationsByWorkspace)
    );
  }
  return workspaceLabel(left).localeCompare(workspaceLabel(right));
}

function sortConversations(
  conversations: AgentConversation[],
  groupMode: 'project' | 'recent',
): AgentConversation[] {
  const copy = [...conversations];
  if (groupMode === 'project') {
    return copy.sort((left, right) =>
      (left.title || left.id).localeCompare(right.title || right.id),
    );
  }
  return copy.sort((left, right) => timestamp(right.updated_at) - timestamp(left.updated_at));
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

function workspaceLabel(workspace: WorkspaceSummary): string {
  return workspace.name ?? workspace.title ?? workspace.id;
}

function timestamp(value: string | null | undefined): number {
  return value ? Date.parse(value) || 0 : 0;
}
