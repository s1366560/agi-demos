import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createManagementRouteModuleLoader,
  type ManagementRouteBinding,
  type ManagementRouteContext,
} from './managementRouteModule';

export const PROVIDERS_ROUTE_ID = 'tenant-tenant-providers' as const;

export function createProvidersRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: ManagementRouteContext) => ManagementRouteBinding;
}>): DesktopRouteModuleLoader {
  return createManagementRouteModuleLoader({
    capability: PROVIDERS_ROUTE_ID,
    createBinding,
  });
}
