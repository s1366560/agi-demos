import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createProjectAdministrationRouteModuleLoader,
  type ProjectAdministrationRouteBinding,
  type ProjectAdministrationRouteContext,
} from './projectAdministrationRouteModule';
import { PROJECT_SCHEMA_ROUTE_ID } from './projectSchemaClient';

export type ProjectSchemaRouteContext = ProjectAdministrationRouteContext;
export type ProjectSchemaRouteBinding = ProjectAdministrationRouteBinding;
export function createProjectSchemaRouteModuleLoader(options: Readonly<{
  createBinding: (context: ProjectSchemaRouteContext) => ProjectSchemaRouteBinding;
}>): DesktopRouteModuleLoader {
  return createProjectAdministrationRouteModuleLoader({
    routeId: PROJECT_SCHEMA_ROUTE_ID,
    contextUnavailableReason: 'project_schema_route_context_unavailable',
    bindingScopeMismatchReason: 'project_schema_route_binding_scope_mismatch',
    ...options,
  });
}
