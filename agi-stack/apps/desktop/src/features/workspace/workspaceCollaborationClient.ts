export type WorkspaceCollaborationSurface =
  | 'goals'
  | 'discussion'
  | 'status'
  | 'collaboration'
  | 'members'
  | 'genes'
  | 'files'
  | 'notes'
  | 'topology'
  | 'settings';

export type WorkspaceSurfaceAuthority = 'cloud' | 'local' | 'native';

export type WorkspaceSurfaceStatus =
  | 'loading'
  | 'ready'
  | 'empty'
  | 'stale'
  | 'error'
  | 'unavailable';

export type WorkspaceSurfaceState<T = unknown> = {
  workspace_id: string;
  surface: WorkspaceCollaborationSurface;
  authority: WorkspaceSurfaceAuthority;
  status: WorkspaceSurfaceStatus;
  revision: number | null;
  cursor: string | null;
  data: T | null;
  reason_code: string | null;
};

export type WorkspaceSurfaceMutation = {
  action: string;
  expected_revision: number;
  idempotency_key: string;
  payload: Record<string, unknown>;
};

export type WorkspaceCollaborationClient = {
  getSurface(
    workspaceId: string,
    surface: WorkspaceCollaborationSurface,
    cursor?: string | null,
    signal?: AbortSignal,
  ): Promise<WorkspaceSurfaceState>;
  refetchAuthority(
    workspaceId: string,
    surface: WorkspaceCollaborationSurface,
    signal?: AbortSignal,
  ): Promise<WorkspaceSurfaceState>;
  mutateSurface(
    workspaceId: string,
    surface: WorkspaceCollaborationSurface,
    mutation: WorkspaceSurfaceMutation,
    signal?: AbortSignal,
  ): Promise<WorkspaceSurfaceState>;
};

export function createWorkspaceCollaborationClient(
  authority: WorkspaceCollaborationClient,
): WorkspaceCollaborationClient {
  return Object.freeze({
    getSurface: (
      workspaceId: string,
      surface: WorkspaceCollaborationSurface,
      cursor?: string | null,
      signal?: AbortSignal,
    ) => authority.getSurface(workspaceId, surface, cursor, signal),
    refetchAuthority: (
      workspaceId: string,
      surface: WorkspaceCollaborationSurface,
      signal?: AbortSignal,
    ) => authority.refetchAuthority(workspaceId, surface, signal),
    mutateSurface: (
      workspaceId: string,
      surface: WorkspaceCollaborationSurface,
      mutation: WorkspaceSurfaceMutation,
      signal?: AbortSignal,
    ) => authority.mutateSurface(workspaceId, surface, mutation, signal),
  });
}
