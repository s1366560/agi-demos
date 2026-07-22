import type { RuntimeDataset, WorkspaceSummary } from '../../types';

export type WorkspaceLifecycleScope = {
  tenantId: string;
  projectId: string;
  workspaceId: string;
};

export type WorkspaceLifecycleStreamResult = {
  handled: boolean;
  dataset: RuntimeDataset;
  activeWorkspaceDeleted: boolean;
  nextWorkspaceId: string;
};

export function applyWorkspaceLifecycleStreamEvent(
  dataset: RuntimeDataset,
  event: unknown,
  scope: WorkspaceLifecycleScope,
): WorkspaceLifecycleStreamResult {
  const unchanged = {
    handled: false,
    dataset,
    activeWorkspaceDeleted: false,
    nextWorkspaceId: scope.workspaceId,
  };
  const root = recordValue(event);
  const type = stringValue(root?.type ?? root?.event_type);
  if (!root || (type !== 'workspace_updated' && type !== 'workspace_deleted')) {
    return unchanged;
  }
  const data = recordValue(root.data) ?? recordValue(root.payload);
  const workspaceId = stringValue(data?.workspace_id ?? data?.workspaceId);
  const projectWorkspaces = dataset.workspacesByProject[scope.projectId] ?? [];
  if (!data || !workspaceId || !projectWorkspaces.some(({ id }) => id === workspaceId)) {
    return unchanged;
  }

  const embeddedWorkspace = data.workspace === undefined
    ? null
    : workspaceValue(data.workspace, scope, workspaceId);
  if (data.workspace !== undefined && !embeddedWorkspace) return unchanged;

  if (type === 'workspace_updated') {
    if (!embeddedWorkspace) return unchanged;
    return {
      handled: true,
      dataset: {
        ...dataset,
        workspaces: replaceWorkspace(dataset.workspaces, embeddedWorkspace),
        workspacesByProject: {
          ...dataset.workspacesByProject,
          [scope.projectId]: replaceWorkspace(projectWorkspaces, embeddedWorkspace),
        },
      },
      activeWorkspaceDeleted: false,
      nextWorkspaceId: scope.workspaceId,
    };
  }

  const remainingProjectWorkspaces = projectWorkspaces.filter(({ id }) => id !== workspaceId);
  const conversationsByWorkspace = { ...dataset.conversationsByWorkspace };
  const workspaceNodeState = { ...dataset.nodeState.workspaces };
  delete conversationsByWorkspace[workspaceId];
  delete workspaceNodeState[workspaceId];
  const activeWorkspaceDeleted = workspaceId === scope.workspaceId;
  const nextDataset: RuntimeDataset = {
    ...dataset,
    workspaces: dataset.workspaces.filter(({ id }) => id !== workspaceId),
    workspacesByProject: {
      ...dataset.workspacesByProject,
      [scope.projectId]: remainingProjectWorkspaces,
    },
    conversationsByWorkspace,
    nodeState: { ...dataset.nodeState, workspaces: workspaceNodeState },
    ...(activeWorkspaceDeleted
      ? {
          messages: [],
          tasks: [],
          plan: null,
          workspaceMembers: unavailableCollection(),
          workspaceAgents: unavailableCollection(),
        }
      : {}),
  };
  return {
    handled: true,
    dataset: nextDataset,
    activeWorkspaceDeleted,
    nextWorkspaceId: activeWorkspaceDeleted
      ? remainingProjectWorkspaces[0]?.id ?? ''
      : scope.workspaceId,
  };
}

function workspaceValue(
  value: unknown,
  scope: WorkspaceLifecycleScope,
  workspaceId: string,
): WorkspaceSummary | null {
  const workspace = recordValue(value);
  if (
    !workspace ||
    stringValue(workspace.id) !== workspaceId ||
    stringValue(workspace.tenant_id) !== scope.tenantId ||
    stringValue(workspace.project_id) !== scope.projectId ||
    !stringValue(workspace.name) ||
    !stringValue(workspace.created_by) ||
    !stringValue(workspace.created_at) ||
    typeof workspace.is_archived !== 'boolean'
  ) {
    return null;
  }
  return { ...workspace } as WorkspaceSummary;
}

function replaceWorkspace(items: WorkspaceSummary[], incoming: WorkspaceSummary) {
  return items.map((workspace) => (workspace.id === incoming.id ? incoming : workspace));
}

function unavailableCollection() {
  return { status: 'unavailable' as const, items: [], error: null };
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}
