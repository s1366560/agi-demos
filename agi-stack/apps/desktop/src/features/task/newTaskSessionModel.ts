import type {
  CreateTaskSessionRequest,
  RuntimeNodeState,
  WorkspaceAuthorityCollection,
  WorkspaceSummary,
} from '../../types';
import type { NewTaskDefinition } from './newTaskPlanModel';

export const NEW_WORKSPACE_VALUE = '__new_workspace__';

export type TaskSessionCreationAttempt = {
  fingerprint: string;
  idempotencyKey: string;
};

export function resolveNewTaskWorkspaceAuthority(
  projectState: RuntimeNodeState | undefined,
  workspaces: WorkspaceSummary[],
): WorkspaceAuthorityCollection<WorkspaceSummary> {
  if (!projectState) return { status: 'unavailable', items: workspaces, error: null };
  if (projectState.loading) return { status: 'loading', items: workspaces, error: null };
  if (projectState.error) {
    return { status: 'error', items: workspaces, error: projectState.error };
  }
  return { status: 'ready', items: workspaces, error: null };
}

export function canUseNewTaskWorkspaceSelection(
  authority: WorkspaceAuthorityCollection<WorkspaceSummary>,
  workspaceSelection: string,
): boolean {
  if (authority.status !== 'ready') return false;
  if (workspaceSelection === NEW_WORKSPACE_VALUE) return true;
  return authority.items.some((workspace) => workspace.id === workspaceSelection);
}

export function newTaskWorkspaceLabel(
  sessionWorkspace: WorkspaceSummary | null,
  selectedWorkspace: WorkspaceSummary | null,
  workspaceSelection: string,
  newWorkspaceLabel: string,
): string {
  return (
    sessionWorkspace?.name ||
    sessionWorkspace?.title ||
    selectedWorkspace?.name ||
    selectedWorkspace?.title ||
    (workspaceSelection === NEW_WORKSPACE_VALUE ? newWorkspaceLabel : workspaceSelection)
  );
}

export function taskSessionCreationAttempt(
  current: TaskSessionCreationAttempt | null,
  fingerprint: string,
  createIdempotencyKey: () => string,
): TaskSessionCreationAttempt {
  if (current?.fingerprint === fingerprint) return current;
  return { fingerprint, idempotencyKey: createIdempotencyKey() };
}

export function buildLocalTaskSessionRequest(
  definition: NewTaskDefinition,
  workspaceSelection: string,
  idempotencyKey: string,
): CreateTaskSessionRequest {
  const title = definition.title.trim();
  const objective = definition.objective.trim();
  const workspaceRoot = definition.workspaceRoot?.trim() ?? '';
  const workspace =
    workspaceSelection === NEW_WORKSPACE_VALUE
      ? {
          kind: 'create' as const,
          name: title,
          description: objective,
          metadata: { source: 'desktop' },
          use_case: definition.kind,
          collaboration_mode: 'multi_agent_shared' as const,
          ...(definition.kind === 'programming' && workspaceRoot
            ? { sandbox_code_root: workspaceRoot }
            : {}),
        }
      : {
          kind: 'existing' as const,
          workspace_id: workspaceSelection,
        };

  return {
    idempotency_key: idempotencyKey,
    workspace,
    conversation: {
      title,
      capability_mode: definition.kind === 'programming' ? 'code' : 'work',
    },
    initial_message: { content: objective },
  };
}
