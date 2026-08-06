import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createManagementRouteModuleLoader,
  type ManagementRouteBinding,
  type ManagementRouteContext,
} from './managementRouteModule';

export const MCP_SERVERS_ROUTE_ID = 'tenant-tenant-mcp-servers' as const;

export function createMcpServersRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: ManagementRouteContext) => ManagementRouteBinding;
}>): DesktopRouteModuleLoader {
  return createManagementRouteModuleLoader({
    capability: MCP_SERVERS_ROUTE_ID,
    createBinding,
  });
}
