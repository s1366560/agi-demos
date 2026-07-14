import type { AuthState, WorkspaceContextSnapshot } from '../../types';

export function isWorkspaceAuthenticated(auth: AuthState): boolean {
  return (
    auth.status === 'signed_in' &&
    auth.credentialKind !== null &&
    auth.user !== null &&
    Boolean(auth.context?.tenant_id.trim()) &&
    Boolean(auth.context?.project_id.trim())
  );
}

export function isCurrentContextRevision(expected: number, current: number): boolean {
  return expected === current;
}

export function nextRemoteWorkspaceContext(
  current: WorkspaceContextSnapshot,
  tenantId: string,
  projectId: string,
  updatedAt: string,
): WorkspaceContextSnapshot {
  return {
    tenant_id: tenantId,
    project_id: projectId,
    revision: current.revision + 1,
    updated_at: updatedAt,
  };
}
