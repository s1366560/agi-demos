import type {
  WorkspaceCollaborationSurface,
  WorkspaceSurfaceMutation,
  WorkspaceSurfaceState,
} from './workspaceCollaborationClient';

export const WORKSPACE_COLLABORATION_TABS: ReadonlyArray<{
  id: WorkspaceCollaborationSurface;
  labelKey: string;
}> = Object.freeze([
  { id: 'goals', labelKey: 'workspaceCollaboration.tabs.goals' },
  { id: 'discussion', labelKey: 'workspaceCollaboration.tabs.discussion' },
  { id: 'status', labelKey: 'workspaceCollaboration.tabs.status' },
  { id: 'collaboration', labelKey: 'workspaceCollaboration.tabs.collaboration' },
  { id: 'members', labelKey: 'workspaceCollaboration.tabs.members' },
  { id: 'genes', labelKey: 'workspaceCollaboration.tabs.genes' },
  { id: 'files', labelKey: 'workspaceCollaboration.tabs.files' },
  { id: 'notes', labelKey: 'workspaceCollaboration.tabs.notes' },
  { id: 'topology', labelKey: 'workspaceCollaboration.tabs.topology' },
  { id: 'settings', labelKey: 'workspaceCollaboration.tabs.settings' },
]);

export type WorkspaceAuthorityInvalidationTrigger =
  | 'reconnect'
  | 'cursor_gap'
  | 'mutation_ack';

export type WorkspaceCollaborationCanvasState = {
  workspaceId: string;
  activeSurface: WorkspaceCollaborationSurface;
  surfaces: Partial<Record<WorkspaceCollaborationSurface, WorkspaceSurfaceState>>;
  requestGenerations: Partial<Record<WorkspaceCollaborationSurface, number>>;
};

export type WorkspaceSurfaceMutationResult =
  | { ok: true; mutation: WorkspaceSurfaceMutation }
  | {
      ok: false;
      reasonCode:
        | 'workspace_surface_revision_required'
        | 'workspace_surface_action_invalid'
        | 'workspace_surface_idempotency_invalid';
    };

const SURFACES = new Set<WorkspaceCollaborationSurface>(
  WORKSPACE_COLLABORATION_TABS.map(({ id }) => id),
);

export function createWorkspaceCollaborationCanvasState(
  workspaceId: string,
): WorkspaceCollaborationCanvasState {
  return {
    workspaceId: workspaceId.trim(),
    activeSurface: 'goals',
    surfaces: {},
    requestGenerations: {},
  };
}

export function selectWorkspaceCollaborationTab(
  state: WorkspaceCollaborationCanvasState,
  surface: string,
): WorkspaceCollaborationCanvasState {
  if (!SURFACES.has(surface as WorkspaceCollaborationSurface)) return state;
  const activeSurface = surface as WorkspaceCollaborationSurface;
  return state.activeSurface === activeSurface ? state : { ...state, activeSurface };
}

export function beginWorkspaceSurfaceLoad(
  state: WorkspaceCollaborationCanvasState,
  surface: WorkspaceCollaborationSurface,
): WorkspaceCollaborationCanvasState {
  const generation = (state.requestGenerations[surface] ?? 0) + 1;
  const existing = state.surfaces[surface];
  return {
    ...state,
    requestGenerations: { ...state.requestGenerations, [surface]: generation },
    surfaces: {
      ...state.surfaces,
      [surface]: existing
        ? {
            ...existing,
            status: existing.data === null ? 'loading' : 'stale',
            reason_code:
              existing.data === null ? null : 'workspace_surface_refresh_in_progress',
          }
        : {
            workspace_id: state.workspaceId,
            surface,
            authority: 'cloud',
            status: 'loading',
            revision: null,
            cursor: null,
            data: null,
            reason_code: null,
          },
    },
  };
}

export function resolveWorkspaceSurfaceLoad(
  state: WorkspaceCollaborationCanvasState,
  surface: WorkspaceCollaborationSurface,
  generation: number,
  snapshot: WorkspaceSurfaceState,
): WorkspaceCollaborationCanvasState {
  if (state.requestGenerations[surface] !== generation) return state;
  if (snapshot.workspace_id !== state.workspaceId || snapshot.surface !== surface) {
    return {
      ...state,
      surfaces: {
        ...state.surfaces,
        [surface]: {
          workspace_id: state.workspaceId,
          surface,
          authority: snapshot.authority,
          status: 'error',
          revision: state.surfaces[surface]?.revision ?? null,
          cursor: state.surfaces[surface]?.cursor ?? null,
          data: state.surfaces[surface]?.data ?? null,
          reason_code: 'workspace_surface_scope_mismatch',
        },
      },
    };
  }
  const currentRevision = state.surfaces[surface]?.revision;
  if (
    currentRevision !== null &&
    currentRevision !== undefined &&
    snapshot.revision !== null &&
    snapshot.revision < currentRevision
  ) {
    return state;
  }
  return {
    ...state,
    surfaces: { ...state.surfaces, [surface]: snapshot },
  };
}

export function failWorkspaceSurfaceLoad(
  state: WorkspaceCollaborationCanvasState,
  surface: WorkspaceCollaborationSurface,
  generation: number,
  reasonCode: string,
): WorkspaceCollaborationCanvasState {
  if (state.requestGenerations[surface] !== generation) return state;
  const existing = state.surfaces[surface];
  return {
    ...state,
    surfaces: {
      ...state.surfaces,
      [surface]: {
        workspace_id: state.workspaceId,
        surface,
        authority: existing?.authority ?? 'cloud',
        status: 'error',
        revision: existing?.revision ?? null,
        cursor: existing?.cursor ?? null,
        data: existing?.data ?? null,
        reason_code: reasonCode.trim() || 'workspace_surface_load_failed',
      },
    },
  };
}

export function invalidateWorkspaceSurfaceAuthority(
  state: WorkspaceCollaborationCanvasState,
  surface: WorkspaceCollaborationSurface,
  trigger: WorkspaceAuthorityInvalidationTrigger,
): WorkspaceCollaborationCanvasState {
  const existing = state.surfaces[surface];
  if (!existing) return state;
  return {
    ...state,
    surfaces: {
      ...state.surfaces,
      [surface]: {
        ...existing,
        status: 'stale',
        reason_code: `workspace_surface_${trigger}_refetch_required`,
      },
    },
  };
}

export function buildWorkspaceSurfaceMutation(
  state: WorkspaceCollaborationCanvasState,
  surface: WorkspaceCollaborationSurface,
  action: string,
  idempotencyKey: string,
  payload: Record<string, unknown>,
): WorkspaceSurfaceMutationResult {
  const revision = state.surfaces[surface]?.revision;
  if (revision === null || revision === undefined || !Number.isSafeInteger(revision)) {
    return { ok: false, reasonCode: 'workspace_surface_revision_required' };
  }
  const normalizedAction = action.trim();
  if (!normalizedAction || normalizedAction.length > 128) {
    return { ok: false, reasonCode: 'workspace_surface_action_invalid' };
  }
  const normalizedKey = idempotencyKey.trim();
  if (normalizedKey.length < 8 || normalizedKey.length > 256) {
    return { ok: false, reasonCode: 'workspace_surface_idempotency_invalid' };
  }
  return {
    ok: true,
    mutation: {
      action: normalizedAction,
      expected_revision: revision,
      idempotency_key: normalizedKey,
      payload,
    },
  };
}
