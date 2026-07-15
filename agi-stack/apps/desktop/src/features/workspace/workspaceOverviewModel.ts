import type {
  AgentCapabilityMode,
  AgentConversation,
  ConnectionState,
  DesktopRuntimeConfig,
  PlanSnapshot,
  ProjectSummary,
  RuntimeDataset,
  WorkspaceAgentBinding,
  WorkspaceAuthorityCollection,
  WorkspaceAuthorityStatus,
  WorkspaceMemberSummary,
  WorkspaceSummary,
} from '../../types';

export type WorkspaceSessionSummary = {
  id: string;
  title: string;
  status: string;
  capabilityMode: AgentCapabilityMode | null;
  updatedAt: string | null;
};

export type WorkspaceActivitySummary = {
  title: string;
  detail: string | null;
};

export type WorkspaceOverviewModel = {
  workspaceName: string | null;
  workspaceDescription: string | null;
  officeStatus: string | null;
  collaborationMode: string | null;
  updatedAt: string | null;
  rootGoal: string | null;
  sessionCounts: {
    total: number;
    running: number;
    attention: number;
    ready: number;
  };
  memberCount: number | null;
  activeAgentCount: number | null;
  memberRosterStatus: WorkspaceAuthorityStatus;
  agentRosterStatus: WorkspaceAuthorityStatus;
  agentRosterNames: string[];
  knowledge: {
    memories: number | null;
    graphNodes: number | null;
    storageBytes: number | null;
  };
  environment: {
    sandboxStatus: string | null;
    connection: ConnectionState;
  };
  recentSessions: WorkspaceSessionSummary[];
  recentActivity: WorkspaceActivitySummary[];
};

type BuildWorkspaceOverviewModelInput = {
  workspace: WorkspaceSummary | null;
  project: ProjectSummary | null;
  conversations: AgentConversation[];
  members: WorkspaceAuthorityCollection<WorkspaceMemberSummary>;
  agents: WorkspaceAuthorityCollection<WorkspaceAgentBinding>;
  plan: PlanSnapshot | null;
  sandboxStatus: string | null;
  connection: ConnectionState;
};

const ATTENTION_STATUSES = new Set(['needs_input', 'needs_approval']);
const READY_STATUSES = new Set(['ready_review', 'completed']);

export function beginWorkspaceRuntimeTransition(dataset: RuntimeDataset): RuntimeDataset {
  return {
    ...dataset,
    messages: [],
    tasks: [],
    plan: null,
    workspaceMembers: unavailableAuthorityCollection(),
    workspaceAgents: unavailableAuthorityCollection(),
  };
}

export function beginDesktopRuntimeScopeTransition(
  dataset: RuntimeDataset,
  previousConfig: DesktopRuntimeConfig,
  nextConfig: DesktopRuntimeConfig,
): RuntimeDataset {
  if (!sameProjectRuntimeScope(previousConfig, nextConfig)) {
    return {
      workspaces: [],
      workspacesByProject: {},
      conversationsByWorkspace: {},
      nodeState: { projects: {}, workspaces: {} },
      messages: [],
      tasks: [],
      plan: null,
      workspaceMembers: unavailableAuthorityCollection(),
      workspaceAgents: unavailableAuthorityCollection(),
      sandbox: null,
      myWork: [],
      myWorkError: null,
    };
  }
  if (previousConfig.workspaceId !== nextConfig.workspaceId) {
    return beginWorkspaceRuntimeTransition(dataset);
  }
  return dataset;
}

export function buildWorkspaceOverviewModel({
  workspace,
  project,
  conversations,
  members,
  agents,
  plan,
  sandboxStatus,
  connection,
}: BuildWorkspaceOverviewModelInput): WorkspaceOverviewModel {
  const sessions = conversations.map(projectConversation);
  const metadata = workspace?.metadata ?? null;
  const stats = project?.stats ?? null;
  const activeAgents =
    agents.status === 'ready' ? agents.items.filter((agent) => agent.is_active) : [];

  return {
    workspaceName: workspace ? workspace.name ?? workspace.title ?? workspace.id : null,
    workspaceDescription: workspace?.description ?? null,
    officeStatus: stringValue(workspace?.office_status),
    collaborationMode: stringValue(metadata?.collaboration_mode),
    updatedAt: workspace?.updated_at ?? workspace?.created_at ?? null,
    rootGoal: readRootGoal(plan) ?? stringValue(metadata?.root_goal),
    sessionCounts: {
      total: sessions.length,
      running: sessions.filter((session) => session.status === 'running').length,
      attention: sessions.filter((session) => ATTENTION_STATUSES.has(session.status)).length,
      ready: sessions.filter((session) => READY_STATUSES.has(session.status)).length,
    },
    memberCount: members.status === 'ready' ? members.items.length : null,
    activeAgentCount: agents.status === 'ready' ? activeAgents.length : null,
    memberRosterStatus: members.status,
    agentRosterStatus: agents.status,
    agentRosterNames: activeAgents.map(agentBindingName),
    knowledge: {
      memories: numberValue(stats?.memory_count),
      graphNodes: numberValue(stats?.node_count),
      storageBytes: numberValue(stats?.storage_used),
    },
    environment: { sandboxStatus, connection },
    recentSessions: sessions.slice(0, 5),
    recentActivity: readRecentActivity(stats?.recent_activity),
  };
}

function unavailableAuthorityCollection<T>(): WorkspaceAuthorityCollection<T> {
  return { status: 'unavailable', items: [], error: null };
}

function agentBindingName(agent: WorkspaceAgentBinding): string {
  return stringValue(agent.display_name) ?? stringValue(agent.label) ?? agent.agent_id;
}

function projectConversation(conversation: AgentConversation): WorkspaceSessionSummary {
  return {
    id: conversation.id,
    title: conversation.title || conversation.id,
    status: conversationRunStatus(conversation) ?? conversation.status,
    capabilityMode: conversationCapabilityMode(conversation),
    updatedAt: conversation.updated_at ?? conversation.created_at ?? null,
  };
}

function conversationRunStatus(conversation: AgentConversation): string | null {
  const metadata = conversation.metadata;
  if (!metadata || typeof metadata !== 'object') return null;
  const run = metadata.run;
  if (!run || typeof run !== 'object' || Array.isArray(run)) return null;
  return stringValue((run as Record<string, unknown>).status);
}

function conversationCapabilityMode(
  conversation: AgentConversation,
): AgentCapabilityMode | null {
  const value = conversation.agent_config?.capability_mode;
  return value === 'work' || value === 'code' ? value : null;
}

function readRootGoal(plan: PlanSnapshot | null): string | null {
  const value = plan?.root_goal;
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  return stringValue(record.title) ?? stringValue(record.content) ?? stringValue(record.goal);
}

function readRecentActivity(value: unknown): WorkspaceActivitySummary[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const title = stringValue(record.title) ?? stringValue(record.label);
    if (!title) return [];
    return [
      {
        title,
        detail:
          stringValue(record.detail) ??
          stringValue(record.meta) ??
          stringValue(record.timestamp),
      },
    ];
  });
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function sameProjectRuntimeScope(
  previousConfig: DesktopRuntimeConfig,
  nextConfig: DesktopRuntimeConfig,
): boolean {
  return (
    previousConfig.mode === nextConfig.mode &&
    previousConfig.apiBaseUrl === nextConfig.apiBaseUrl &&
    previousConfig.apiKey === nextConfig.apiKey &&
    previousConfig.localApiToken === nextConfig.localApiToken &&
    previousConfig.tenantId === nextConfig.tenantId &&
    previousConfig.projectId === nextConfig.projectId
  );
}
