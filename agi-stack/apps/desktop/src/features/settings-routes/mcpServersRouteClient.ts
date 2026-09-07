import type { DesktopProjectMcpServersOperationsV2 } from '../../plugins/desktopProjectMcpServersAuthorityModuleV2';
import type { DesktopRuntimeConfig } from '../../types';
import {
  ManagementRouteClientError,
  managementRouteObservation,
  requireManagementRouteRuntimeScope,
  type ManagementRouteClient,
} from './managementRouteTypes';

export type McpServersRouteAuthority = Pick<
  DesktopProjectMcpServersOperationsV2,
  'listMCPServers'
>;

export function createMcpServersRouteClient(
  config: DesktopRuntimeConfig,
  authority: McpServersRouteAuthority,
): ManagementRouteClient {
  const runtimeConfig = Object.freeze({ ...config });
  const client: ManagementRouteClient = {
    async observe(scope, options) {
      const currentScope = requireManagementRouteRuntimeScope(
        runtimeConfig,
        scope,
      );
      if (currentScope.projectId === null) {
        throw new ManagementRouteClientError(
          'mcp_servers_project_scope_required',
        );
      }
      const servers = await authority.listMCPServers({
        config: runtimeConfig,
        scope: {
          authority: currentScope.authority,
          tenantId: currentScope.tenantId,
          projectId: currentScope.projectId,
        },
        args: [currentScope.projectId],
        signal: options?.signal,
      });
      return managementRouteObservation(currentScope, servers.length);
    },
  };
  return Object.freeze(client);
}
