import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createManagementRouteModuleLoader,
  type ManagementRouteBinding,
  type ManagementRouteContext,
} from './managementRouteModule';

export const SKILLS_ROUTE_ID = 'tenant-tenant-skills' as const;

export function createSkillsRouteModuleLoader({
  createBinding,
}: Readonly<{
  createBinding: (context: ManagementRouteContext) => ManagementRouteBinding;
}>): DesktopRouteModuleLoader {
  return createManagementRouteModuleLoader({
    capability: SKILLS_ROUTE_ID,
    createBinding,
  });
}
