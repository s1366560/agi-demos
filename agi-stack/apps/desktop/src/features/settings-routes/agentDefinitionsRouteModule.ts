import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createManagementRouteModuleLoader,
  type ManagementRouteBinding,
  type ManagementRouteContext,
} from './managementRouteModule';

export const AGENT_DEFINITIONS_ROUTE_ID =
  'tenant-tenant-agent-definitions' as const;

export function createAgentDefinitionsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: ManagementRouteContext) => ManagementRouteBinding;
}>): DesktopRouteModuleLoader {
  return createManagementRouteModuleLoader({
    capability: AGENT_DEFINITIONS_ROUTE_ID,
    createBinding,
  });
}
