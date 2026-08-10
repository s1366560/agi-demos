import type { CloudSessionProjection } from '../../api/cloudSessionProjectionClient';
import type { AuthState, DesktopRuntimeConfig } from '../../types';
import {
  buildDesktopRoutePath,
  restoreDesktopRoute,
  type DesktopRouteMatch,
  type DesktopRouteRegistry,
} from '../navigation/desktopRouteRegistry';

const PROJECT_OVERVIEW_ROUTE_ID = 'project-project-overview';
const TENANT_OVERVIEW_ROUTE_ID = 'tenant-tenant-overview';

export type NativeOAuthSessionProjection = Readonly<
  Omit<CloudSessionProjection, 'workspaceContext'> & {
    workspaceContext: Readonly<
      Omit<CloudSessionProjection['workspaceContext'], 'projectId'> & {
        projectId: string | null;
      }
    >;
  }
>;

export type ProjectedCloudSessionState = Readonly<{
  config: DesktopRuntimeConfig;
  auth: AuthState;
}>;

export function createProjectedCloudSessionState(
  projection: NativeOAuthSessionProjection,
  currentConfig: DesktopRuntimeConfig,
): ProjectedCloudSessionState {
  const { tenantId, projectId, revision, updatedAt } = projection.workspaceContext;
  if (
    !projection.tenants.some((tenant) => tenant.id === tenantId) ||
    (projectId !== null &&
      !projection.projects.some(
        (project) => project.id === projectId && project.tenant_id === tenantId,
      ))
  ) {
    throw new Error('cloud_session_projection_scope_invalid');
  }
  return Object.freeze({
    config: Object.freeze({
      ...currentConfig,
      apiBaseUrl: projection.apiBaseUrl,
      apiKey: '',
      localApiToken: '',
      tenantId,
      projectId: projectId ?? '',
      workspaceId: '',
      mode: 'cloud',
    }),
    auth: Object.freeze({
      status: 'signed_in',
      credentialKind: 'cloud_session',
      session: null,
      context: projectedWorkspaceContext(tenantId, projectId, revision, updatedAt),
      user: Object.freeze({
        user_id: projection.user.userId,
        email: projection.user.email,
        name: projection.user.name,
        roles: [...projection.user.roles],
        global_roles: [...projection.user.globalRoles],
        is_active: projection.user.active,
        is_superuser: projection.user.superuser,
        created_at: projection.user.createdAt,
        profile: Object.freeze({}),
        preferred_language: projection.user.preferredLanguage,
      }),
      tenants: projection.tenants.map((tenant) => ({ ...tenant })),
      projects: projection.projects.map((project) => ({ ...project })),
      mustChangePassword: false,
      error: null,
    }),
  });
}

export function resolveNativeOAuthResumePath<TModule>(
  registry: DesktopRouteRegistry<TModule>,
  resumeRoute: string,
  projection: NativeOAuthSessionProjection,
): string | null {
  const restored = restoreDesktopRoute(registry, resumeRoute);
  if (restored.status === 'matched' && routeMatchesProjectedScope(restored.match, projection)) {
    return restored.match.canonicalPath;
  }
  const projectId = projection.workspaceContext.projectId;
  const fallback = registry.byId.get(
    projectId === null ? TENANT_OVERVIEW_ROUTE_ID : PROJECT_OVERVIEW_ROUTE_ID,
  );
  if (!fallback) return null;
  try {
    return buildDesktopRoutePath(fallback, {
      tenantId: projection.workspaceContext.tenantId,
      ...(projectId === null ? {} : { projectId }),
    });
  } catch {
    return null;
  }
}

function routeMatchesProjectedScope<TModule>(
  match: DesktopRouteMatch<TModule>,
  projection: NativeOAuthSessionProjection,
): boolean {
  if (match.definition.scope.includes('workspace') || match.definition.scope.includes('instance')) {
    return false;
  }
  const { tenantId, projectId } = projection.workspaceContext;
  if (
    projectId === null &&
    (match.definition.scope.includes('project') || match.context.projectId !== undefined)
  ) {
    return false;
  }
  return (
    (match.context.tenantId === undefined || match.context.tenantId === tenantId) &&
    (match.context.projectId === undefined || match.context.projectId === projectId)
  );
}

function projectedWorkspaceContext(
  tenantId: string,
  projectId: string | null,
  revision: number,
  updatedAt: string,
): NonNullable<AuthState['context']> {
  const context = Object.freeze({
    tenant_id: tenantId,
    project_id: projectId,
    revision,
    updated_at: updatedAt,
  });
  // The shared snapshot still models project-selected sessions only. Keep the tenant-only
  // runtime null at this single compatibility bridge until that wider contract can be changed.
  return context as unknown as NonNullable<AuthState['context']>;
}
