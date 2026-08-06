import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createProjectAdministrationRouteModuleLoader,
  type ProjectAdministrationRouteBinding,
  type ProjectAdministrationRouteContext,
} from './projectAdministrationRouteModule';
import { PROJECT_SETTINGS_ROUTE_ID } from './projectSettingsClient';

export type ProjectSettingsRouteContext = ProjectAdministrationRouteContext;
export type ProjectSettingsRouteBinding = ProjectAdministrationRouteBinding;
export function createProjectSettingsRouteModuleLoader(options: Readonly<{
  createBinding: (context: ProjectSettingsRouteContext) => ProjectSettingsRouteBinding;
}>): DesktopRouteModuleLoader {
  return createProjectAdministrationRouteModuleLoader({
    routeId: PROJECT_SETTINGS_ROUTE_ID,
    contextUnavailableReason: 'project_settings_route_context_unavailable',
    bindingScopeMismatchReason: 'project_settings_route_binding_scope_mismatch',
    ...options,
  });
}
