import type { AuthState, DesktopRuntimeConfig } from '../../types';

// UI invalidation only. The native broker independently verifies the cloud user,
// workspace revision, and installation before selecting a device namespace.
export function mcpManagementOwnerKey(config: DesktopRuntimeConfig, auth: AuthState): string {
  return JSON.stringify([
    config.mode,
    config.apiBaseUrl.replace(/\/+$/u, ''),
    config.tenantId,
    config.projectId,
    config.workspaceId,
    auth.status,
    auth.user?.user_id,
    auth.session?.session_id,
    auth.context?.tenant_id,
    auth.context?.project_id,
    auth.context?.revision,
  ]);
}
