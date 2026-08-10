import { DesktopApiClient } from '../../api/client';
import type { VaultBoundCloudRequestBroker } from '../../api/cloudRequestBroker';
import type { CurrentUser, DesktopRuntimeConfig, WorkspaceContextResponse } from '../../types';
import type { DesktopRouteContext } from './desktopRouteRegistry';
import type { DesktopRoutePermissionAuthorityClient } from './desktopRoutePermissionAuthority';

export function createCloudDesktopRoutePermissionClient(
  config: DesktopRuntimeConfig,
  broker: VaultBoundCloudRequestBroker | null = null,
): DesktopRoutePermissionAuthorityClient {
  if (config.mode !== 'cloud') throw new Error('desktop_route_permission_mode_mismatch');
  if (!config.apiKey.trim() && broker) {
    return Object.freeze({
      async getCurrentUser(signal) {
        return (await broker.requestJson({
          path: '/api/v1/auth/me',
          signal,
        })) as CurrentUser;
      },
      async getWorkspaceContext(signal) {
        return (await broker.requestJson({
          path: '/api/v1/workspace-context',
          signal,
        })) as WorkspaceContextResponse;
      },
      async listWorkspaceMembers() {
        throw new Error('desktop_route_permission_workspace_authority_unavailable');
      },
    });
  }
  return createDesktopRoutePermissionClient(config);
}

export function createLocalDesktopRoutePermissionClient(
  config: DesktopRuntimeConfig,
): DesktopRoutePermissionAuthorityClient {
  if (config.mode !== 'local') throw new Error('desktop_route_permission_mode_mismatch');
  return createDesktopRoutePermissionClient(config);
}

export function createVaultBoundCloudDesktopRoutePermissionClient(
  config: DesktopRuntimeConfig,
  broker: VaultBoundCloudRequestBroker | null,
): DesktopRoutePermissionAuthorityClient {
  if (config.mode !== 'local') throw new Error('desktop_route_permission_mode_mismatch');
  if (!broker) throw new Error('cloud_request_broker_missing');
  return Object.freeze({
    async getCurrentUser(signal) {
      return (await broker.requestJson({
        path: '/api/v1/auth/me',
        signal,
      })) as CurrentUser;
    },
    async getWorkspaceContext(signal) {
      return (await broker.requestJson({
        path: '/api/v1/workspace-context',
        signal,
      })) as WorkspaceContextResponse;
    },
    async listWorkspaceMembers() {
      throw new Error('desktop_route_permission_workspace_authority_unavailable');
    },
  });
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
