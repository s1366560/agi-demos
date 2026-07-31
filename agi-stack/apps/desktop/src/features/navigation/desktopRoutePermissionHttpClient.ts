import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import type { DesktopRouteContext } from './desktopRouteRegistry';
import type { DesktopRoutePermissionAuthorityClient } from './desktopRoutePermissionAuthority';

export function createCloudDesktopRoutePermissionClient(
  config: DesktopRuntimeConfig,
): DesktopRoutePermissionAuthorityClient {
  if (config.mode !== 'cloud') throw new Error('desktop_route_permission_mode_mismatch');
  return createDesktopRoutePermissionClient(config);
}

export function createLocalDesktopRoutePermissionClient(
  config: DesktopRuntimeConfig,
): DesktopRoutePermissionAuthorityClient {
  if (config.mode !== 'local') throw new Error('desktop_route_permission_mode_mismatch');
  return createDesktopRoutePermissionClient(config);
}

function createDesktopRoutePermissionClient(
  config: DesktopRuntimeConfig,
): DesktopRoutePermissionAuthorityClient {
  const baseConfig = Object.freeze({ ...config });
  const identity = new DesktopApiClient(baseConfig);
  return Object.freeze({
    getCurrentUser: (signal) => identity.currentUser(signal),
    getWorkspaceContext: (signal) => identity.getWorkspaceContext(signal),
    listWorkspaceMembers: (context, signal) => {
      const scoped = new DesktopApiClient(scopedConfig(baseConfig, context, true));
      return scoped.listWorkspaceMembers(signal);
    },
  });
}

function scopedConfig(
  config: DesktopRuntimeConfig,
  context: DesktopRouteContext,
  requireWorkspace: boolean,
): DesktopRuntimeConfig {
  const tenantId = context.tenantId ?? config.tenantId;
  const projectId = context.projectId ?? config.projectId;
  const workspaceId = context.workspaceId ?? config.workspaceId;
  if (
    !isExactIdentifier(tenantId) ||
    !isExactIdentifier(projectId) ||
    (requireWorkspace && !isExactIdentifier(workspaceId))
  ) {
    throw new Error('desktop_route_permission_scope_invalid');
  }
  return Object.freeze({
    ...config,
    tenantId,
    projectId,
    workspaceId,
  });
}

function isExactIdentifier(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.trim() === value;
}
