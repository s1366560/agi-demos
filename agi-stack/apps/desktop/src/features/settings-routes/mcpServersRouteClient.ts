import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import {
  ManagementRouteClientError,
  managementRouteObservation,
  requireManagementRouteRuntimeScope,
  type ManagementRouteClient,
} from './managementRouteTypes';

export type McpServersRouteAuthority = Pick<
  DesktopApiClient,
  'listMCPServers'
>;

export function createMcpServersRouteClient(
  config: DesktopRuntimeConfig,
  authority: McpServersRouteAuthority = new DesktopApiClient(config),
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
      const servers = await authority.listMCPServers(
        currentScope.projectId,
        options?.signal,
      );
      return managementRouteObservation(currentScope, servers.length);
    },
  };
  return Object.freeze(client);
}
