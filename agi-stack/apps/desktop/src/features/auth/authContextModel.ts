import type {
  AuthState,
  DesktopRuntimeConfig,
  LocalRuntimeStatus,
  WorkspaceContextSnapshot,
} from '../../types';

export type SignOutDisposition = 'complete' | 'complete_with_persistence_warning' | 'blocked';

export function isCurrentLocalRuntimeAuthority(
  config: DesktopRuntimeConfig,
  status: LocalRuntimeStatus | null,
  runsInTauri: boolean,
): boolean {
  return Boolean(
    runsInTauri &&
      config.mode === 'local' &&
      status?.running &&
      status.api_base_url === config.apiBaseUrl &&
      status.api_token === config.localApiToken,
  );
}

export function resolveSignOutDisposition(
  hasCredentialBroker: boolean,
  persistedCredentialCleared: boolean,
  credentialRevoked: boolean,
): SignOutDisposition {
  if (!hasCredentialBroker || persistedCredentialCleared) return 'complete';
  return credentialRevoked ? 'complete_with_persistence_warning' : 'blocked';
}

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

export function isSameDesktopRequestScope(
  expected: DesktopRuntimeConfig,
  current: DesktopRuntimeConfig,
): boolean {
  return (
    expected.mode === current.mode &&
    expected.apiBaseUrl === current.apiBaseUrl &&
    expected.apiKey === current.apiKey &&
    expected.localApiToken === current.localApiToken &&
    expected.tenantId === current.tenantId &&
    expected.projectId === current.projectId &&
    expected.workspaceId === current.workspaceId
  );
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
