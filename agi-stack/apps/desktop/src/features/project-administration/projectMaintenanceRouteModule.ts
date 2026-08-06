import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createProjectAdministrationRouteModuleLoader,
  type ProjectAdministrationRouteBinding,
  type ProjectAdministrationRouteContext,
} from './projectAdministrationRouteModule';
import { PROJECT_MAINTENANCE_ROUTE_ID } from './projectMaintenanceClient';

export type ProjectMaintenanceRouteContext = ProjectAdministrationRouteContext;
export type ProjectMaintenanceRouteBinding = ProjectAdministrationRouteBinding;
export function createProjectMaintenanceRouteModuleLoader(options: Readonly<{
  createBinding: (context: ProjectMaintenanceRouteContext) => ProjectMaintenanceRouteBinding;
}>): DesktopRouteModuleLoader {
  return createProjectAdministrationRouteModuleLoader({
    routeId: PROJECT_MAINTENANCE_ROUTE_ID,
    contextUnavailableReason: 'project_maintenance_route_context_unavailable',
    bindingScopeMismatchReason: 'project_maintenance_route_binding_scope_mismatch',
    ...options,
  });
}
