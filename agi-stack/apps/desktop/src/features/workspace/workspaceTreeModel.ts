import type {
  AgentConversation,
  RuntimeNodeLoadState,
  RuntimeNodeState,
  WorkspaceSummary,
} from '../../types';

export type WorkspaceTreeNode = {
  workspace: WorkspaceSummary;
  conversations: AgentConversation[];
};

export type WorkspaceTreeSelectionMode = 'overview' | 'conversation' | 'my-work' | 'none';

export type WorkspaceTreeAvailability = 'loading' | 'error' | 'empty' | 'ready';

export type WorkspaceTreeSessionAvailability =
  | 'deferred'
  | 'loading'
  | 'error'
  | 'empty'
  | 'ready';

export type WorkspaceTreeStatusTone =
  | 'active'
  | 'idle'
  | 'queued'
  | 'paused'
  | 'attention'
  | 'ready'
  | 'completed'
  | 'danger'
  | 'offline'
  | 'unknown';

export type WorkspaceTreeStatusPresentation = {
  tone: WorkspaceTreeStatusTone;
  labelKey: string;
};

const CONVERSATION_STATUS_PRESENTATIONS: Readonly<
  Record<string, WorkspaceTreeStatusPresentation>
> = {
  active: { tone: 'idle', labelKey: 'workspaceTree.active' },
  running: { tone: 'active', labelKey: 'workspaceTree.running' },
  queued: { tone: 'queued', labelKey: 'workspaceTree.queued' },
  paused: { tone: 'paused', labelKey: 'workspaceTree.paused' },
  needs_input: { tone: 'attention', labelKey: 'workspaceTree.needsInput' },
  needs_approval: { tone: 'attention', labelKey: 'workspaceTree.needsApproval' },
  ready_review: { tone: 'ready', labelKey: 'workspaceTree.readyReview' },
  completed: { tone: 'completed', labelKey: 'workspaceTree.completed' },
  failed: { tone: 'danger', labelKey: 'workspaceTree.failed' },
  disconnected: { tone: 'danger', labelKey: 'workspaceTree.disconnected' },
  interrupted: { tone: 'danger', labelKey: 'workspaceTree.interrupted' },
  cancelled: { tone: 'offline', labelKey: 'workspaceTree.cancelled' },
  archived: { tone: 'offline', labelKey: 'workspaceTree.archived' },
  inactive: { tone: 'offline', labelKey: 'workspaceTree.offline' },
  offline: { tone: 'offline', labelKey: 'workspaceTree.offline' },
};

const ROOT_STATUS_PRIORITY: Readonly<Record<WorkspaceTreeStatusTone, number>> = {
  attention: 9,
  danger: 8,
  active: 7,
  queued: 6,
  paused: 5,
  ready: 4,
  completed: 3,
  idle: 2,
  offline: 2,
  unknown: 1,
};

const ROOT_AGGREGATE_PRESENTATIONS: Readonly<
  Partial<Record<WorkspaceTreeStatusTone, WorkspaceTreeStatusPresentation>>
> = {
  attention: { tone: 'attention', labelKey: 'workspaceTree.needsAttention' },
  danger: { tone: 'danger', labelKey: 'workspaceTree.issue' },
};

export function isWorkspaceOverviewSelected(
  currentWorkspaceId: string,
  workspaceId: string,
  selectionMode: WorkspaceTreeSelectionMode,
): boolean {
  return selectionMode === 'overview' && currentWorkspaceId === workspaceId;
}

export function isWorkspaceConversationSelected(
  currentConversationId: string | null,
  conversationId: string,
  selectionMode: WorkspaceTreeSelectionMode,
): boolean {
  return (
    (selectionMode === 'conversation' || selectionMode === 'my-work') &&
    currentConversationId === conversationId
  );
}

export function reconcileExpandedWorkspaceIds(
  current: ReadonlySet<string>,
  workspaceIds: readonly string[],
  selectedWorkspaceId: string,
  expandSelectedWorkspace: boolean,
): Set<string> {
  const validWorkspaceIds = new Set(workspaceIds);
  const next = new Set([...current].filter((workspaceId) => validWorkspaceIds.has(workspaceId)));
  if (
    expandSelectedWorkspace &&
    selectedWorkspaceId &&
    validWorkspaceIds.has(selectedWorkspaceId)
  ) {
    next.add(selectedWorkspaceId);
  }
  return next;
}

export function workspaceTreeRefreshFailed(
  nodeState: RuntimeNodeLoadState,
  projectId: string,
  error: string,
): RuntimeNodeLoadState {
  if (!projectId) return nodeState;
  return {
    projects: {
      ...nodeState.projects,
      [projectId]: { loading: false, error },
    },
    workspaces: nodeState.workspaces,
  };
}

export function workspaceTreeAvailability(
  projectState: RuntimeNodeState | undefined,
  workspaceCount: number,
): WorkspaceTreeAvailability {
  if (workspaceCount > 0) return 'ready';
  if (projectState?.loading) return 'loading';
  if (projectState?.error) return 'error';
  return 'empty';
}

export function workspaceConversationLoadTargets(
  workspaces: WorkspaceSummary[],
  selectedWorkspaceId: string,
  expandedWorkspaceIds: ReadonlySet<string>,
): string[] {
  const requestedWorkspaceIds = new Set(expandedWorkspaceIds);
  if (selectedWorkspaceId) requestedWorkspaceIds.add(selectedWorkspaceId);
  return workspaces
    .map((workspace) => workspace.id)
    .filter((workspaceId) => requestedWorkspaceIds.has(workspaceId));
}

export function shouldLoadWorkspaceConversations(
  state: RuntimeNodeState | undefined,
): boolean {
  return !state || (!state.loading && Boolean(state.error));
}

export function beginWorkspaceConversationRequest(
  generations: Map<string, number>,
  workspaceId: string,
): number {
  const generation = (generations.get(workspaceId) ?? 0) + 1;
  generations.set(workspaceId, generation);
  return generation;
}

export function isCurrentWorkspaceConversationRequest(
  generations: ReadonlyMap<string, number>,
  workspaceId: string,
  generation: number,
): boolean {
  return generations.get(workspaceId) === generation;
}

export function supersedeWorkspaceConversationRequests(
  generations: Map<string, number>,
  activeRequests: ReadonlyMap<string, number>,
): Map<string, number> {
  const nextRequests = new Map<string, number>();
  for (const [workspaceId, generation] of activeRequests) {
    if (!isCurrentWorkspaceConversationRequest(generations, workspaceId, generation)) continue;
    nextRequests.set(
      workspaceId,
      beginWorkspaceConversationRequest(generations, workspaceId),
    );
  }
  return nextRequests;
}

export function workspaceTreeSessionAvailability(
  workspaceState: RuntimeNodeState | undefined,
  conversationCount: number,
): WorkspaceTreeSessionAvailability {
  if (conversationCount > 0) return 'ready';
  if (!workspaceState) return 'deferred';
  if (workspaceState.loading) return 'loading';
  if (workspaceState.error) return 'error';
  return 'empty';
}

export function conversationTreeStatusValue(conversation: AgentConversation): string {
  return conversationTreeRunStatusValue(conversation) ?? conversation.status.trim().toLowerCase();
}

function conversationTreeRunStatusValue(conversation: AgentConversation): string | null {
  const run = conversation.metadata?.run;
  if (run && typeof run === 'object' && !Array.isArray(run)) {
    const status = (run as Record<string, unknown>).status;
    if (typeof status === 'string' && status.trim()) return status.trim().toLowerCase();
  }
  return null;
}

export function conversationTreeStatusPresentation(
  status: string | null | undefined,
): WorkspaceTreeStatusPresentation {
  const normalizedStatus = status?.trim().toLowerCase() ?? '';
  return (
    CONVERSATION_STATUS_PRESENTATIONS[normalizedStatus] ?? {
      tone: 'unknown',
      labelKey: 'workspaceTree.unknown',
    }
  );
}

export function workspaceTreeRootStatusPresentation(
  officeStatus: string | null | undefined,
  conversations: AgentConversation[],
): WorkspaceTreeStatusPresentation {
  const rawOfficePresentation =
    officeStatus?.trim().toLowerCase() === 'online'
      ? { tone: 'active' as const, labelKey: 'workspaceTree.online' }
      : conversationTreeStatusPresentation(officeStatus);
  const officePresentation = rootAggregatePresentation(rawOfficePresentation);
  return conversations.reduce((current, conversation) => {
    const runStatus = conversationTreeRunStatusValue(conversation);
    if (!runStatus) return current;
    const candidate = rootAggregatePresentation(conversationTreeStatusPresentation(runStatus));
    return ROOT_STATUS_PRIORITY[candidate.tone] > ROOT_STATUS_PRIORITY[current.tone]
      ? candidate
      : current;
  }, officePresentation);
}

function rootAggregatePresentation(
  presentation: WorkspaceTreeStatusPresentation,
): WorkspaceTreeStatusPresentation {
  return ROOT_AGGREGATE_PRESENTATIONS[presentation.tone] ?? presentation;
}

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
