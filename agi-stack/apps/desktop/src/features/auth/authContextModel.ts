import type {
  AuthState,
  DesktopRuntimeConfig,
  LocalRuntimeStatus,
  ProjectSummary,
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
  if (!credentialRevoked) return 'blocked';
  return hasCredentialBroker && !persistedCredentialCleared
    ? 'complete_with_persistence_warning'
    : 'complete';
}

export function isIdentityAuthenticated(auth: AuthState): boolean {
  return auth.status === 'signed_in' && auth.credentialKind !== null && auth.user !== null;
}

export function findWorkspaceProject(
  projects: readonly ProjectSummary[],
  tenantId: string,
  projectId: string,
): ProjectSummary | undefined {
  if (!tenantId || !projectId) return undefined;
  return projects.find(
    (project) => project.id === projectId && project.tenant_id === tenantId,
  );
}

export function workspaceContextMatchesSelection(
  context: WorkspaceContextSnapshot,
  tenantId: string,
  projectId: string,
): boolean {
  return context.tenant_id === tenantId && context.project_id === projectId;
}

export function isWorkspaceReady(auth: AuthState, config: DesktopRuntimeConfig): boolean {
  if (!isIdentityAuthenticated(auth)) return false;
  const tenantId = auth.context?.tenant_id.trim() ?? '';
  const projectId = auth.context?.project_id.trim() ?? '';
  return (
    Boolean(tenantId) &&
    Boolean(projectId) &&
    config.tenantId.trim() === tenantId &&
    config.projectId.trim() === projectId &&
    auth.tenants.some((tenant) => tenant.id === tenantId) &&
    findWorkspaceProject(auth.projects, tenantId, projectId) !== undefined
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
    isSameDesktopProjectRequestScope(expected, current) &&
    expected.workspaceId === current.workspaceId
  );
}

export function isSameDesktopProjectRequestScope(
  expected: DesktopRuntimeConfig,
  current: DesktopRuntimeConfig,
): boolean {
  return (
    expected.mode === current.mode &&
    expected.apiBaseUrl === current.apiBaseUrl &&
    expected.apiKey === current.apiKey &&
    expected.localApiToken === current.localApiToken &&
    expected.tenantId === current.tenantId &&
    expected.projectId === current.projectId
  );
}
