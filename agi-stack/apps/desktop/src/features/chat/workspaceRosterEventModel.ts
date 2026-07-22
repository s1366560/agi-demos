import type {
  WorkspaceAgentBinding,
  WorkspaceAuthorityCollection,
  WorkspaceMemberSummary,
} from '../../types';

export type WorkspaceRosterStreamResult = {
  handled: boolean;
  members: WorkspaceAuthorityCollection<WorkspaceMemberSummary>;
  agents: WorkspaceAuthorityCollection<WorkspaceAgentBinding>;
};

const rosterEventTypes = new Set([
  'workspace_member_joined',
  'workspace_member_updated',
  'workspace_member_left',
  'workspace_agent_bound',
  'workspace_agent_unbound',
]);

export function applyWorkspaceRosterStreamEvent(
  members: WorkspaceAuthorityCollection<WorkspaceMemberSummary>,
  agents: WorkspaceAuthorityCollection<WorkspaceAgentBinding>,
  event: unknown,
  workspaceId: string,
): WorkspaceRosterStreamResult {
  const unchanged = { handled: false, members, agents };
  const root = recordValue(event);
  const type = stringValue(root?.type ?? root?.event_type);
  if (!root || !type || !rosterEventTypes.has(type)) return unchanged;
  const data = recordValue(root.data) ?? recordValue(root.payload);
  if (!data || stringValue(data.workspace_id ?? data.workspaceId) !== workspaceId) {
    return unchanged;
  }

  if (type === 'workspace_member_joined' || type === 'workspace_member_updated') {
    const member = memberValue(data.member, workspaceId);
    if (!member) return unchanged;
    return {
      handled: true,
      members: { ...members, items: upsertById(members.items, member) },
      agents,
    };
  }
  if (type === 'workspace_member_left') {
    const memberId = stringValue(data.member_id ?? data.memberId);
    const userId = stringValue(data.user_id ?? data.userId);
    if (!memberId && !userId) return unchanged;
    const items = members.items.filter(
      (member) => member.id !== memberId && member.user_id !== userId,
    );
    return {
      handled: true,
      members: items.length === members.items.length ? members : { ...members, items },
      agents,
    };
  }
  if (type === 'workspace_agent_bound') {
    const agent = agentValue(data.agent, workspaceId);
    if (!agent) return unchanged;
    return {
      handled: true,
      members,
      agents: { ...agents, items: upsertById(agents.items, agent) },
    };
  }

  const bindingId = stringValue(data.workspace_agent_id ?? data.workspaceAgentId);
  if (!bindingId) return unchanged;
  const items = agents.items.filter((agent) => agent.id !== bindingId);
  return {
    handled: true,
    members,
    agents: items.length === agents.items.length ? agents : { ...agents, items },
  };
}

function memberValue(value: unknown, workspaceId: string): WorkspaceMemberSummary | null {
  const member = recordValue(value);
  if (
    !member ||
    !stringValue(member.id) ||
    stringValue(member.workspace_id) !== workspaceId ||
    !stringValue(member.user_id) ||
    !stringValue(member.role)
  ) {
    return null;
  }
  return { ...member } as WorkspaceMemberSummary;
}

function agentValue(value: unknown, workspaceId: string): WorkspaceAgentBinding | null {
  const agent = recordValue(value);
  if (
    !agent ||
    !stringValue(agent.id) ||
    stringValue(agent.workspace_id) !== workspaceId ||
    !stringValue(agent.agent_id) ||
    typeof agent.is_active !== 'boolean'
  ) {
    return null;
  }
  return { ...agent } as WorkspaceAgentBinding;
}

function upsertById<T extends { id: string }>(items: T[], incoming: T): T[] {
  const index = items.findIndex((item) => item.id === incoming.id);
  return index < 0
    ? [...items, incoming]
    : items.map((item, itemIndex) => (itemIndex === index ? incoming : item));
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
