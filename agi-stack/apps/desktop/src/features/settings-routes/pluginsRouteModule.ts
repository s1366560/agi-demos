import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createManagementRouteModuleLoader,
  type ManagementRouteBinding,
  type ManagementRouteContext,
} from './managementRouteModule';

export const PLUGINS_ROUTE_ID = 'tenant-tenant-plugins' as const;

export function createPluginsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: ManagementRouteContext) => ManagementRouteBinding;
}>): DesktopRouteModuleLoader {
  return createManagementRouteModuleLoader({
    capability: PLUGINS_ROUTE_ID,
    createBinding,
  });
}
