import type {
  DesktopCapabilityMode,
  DesktopCapabilityView,
} from '../runtime/capabilitySnapshot';
import type {
  WorkspaceCollaborationClient,
  WorkspaceCollaborationSurface,
  WorkspaceSurfaceState,
} from './workspaceCollaborationClient';

export function createCapabilityWorkspaceCollaborationClient(
  authority: WorkspaceCollaborationClient,
  capability: DesktopCapabilityView,
  mode: DesktopCapabilityMode,
): WorkspaceCollaborationClient {
  const unavailable = (
    workspaceId: string,
    surface: WorkspaceCollaborationSurface,
    reasonCode = capability.reason_code ?? 'workspace_collaboration_unavailable',
  ): WorkspaceSurfaceState => ({
    workspace_id: workspaceId,
    surface,
    authority: mode === 'local' ? 'local' : mode === 'native' ? 'native' : 'cloud',
    status: 'unavailable',
    revision: null,
    cursor: null,
    data: null,
    reason_code: reasonCode,
  });

  if (!capability.available) {
    return Object.freeze({
      getSurface: async (workspaceId, surface) => unavailable(workspaceId, surface),
      refetchAuthority: async (workspaceId, surface) => unavailable(workspaceId, surface),
      mutateSurface: async (workspaceId, surface) => unavailable(workspaceId, surface),
    });
  }

  if (capability.status === 'degraded') {
    return Object.freeze({
      getSurface: (workspaceId, surface, cursor, signal) =>
        authority.getSurface(workspaceId, surface, cursor, signal),
      refetchAuthority: (workspaceId, surface, signal) =>
        authority.refetchAuthority(workspaceId, surface, signal),
      mutateSurface: async (workspaceId, surface) =>
        unavailable(
          workspaceId,
          surface,
          capability.reason_code ?? 'workspace_collaboration_mutation_unavailable',
        ),
    });
  }

  return authority;
}
