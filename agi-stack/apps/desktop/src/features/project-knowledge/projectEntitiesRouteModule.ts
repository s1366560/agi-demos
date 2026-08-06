import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createProjectKnowledgeRouteModuleLoader,
  type ProjectKnowledgeRouteBinding,
  type ProjectKnowledgeRouteContext,
} from './projectKnowledgeRouteModule';
import { PROJECT_ENTITIES_ROUTE_ID } from './projectEntitiesClient';

export type ProjectEntitiesRouteContext = ProjectKnowledgeRouteContext;
export type ProjectEntitiesRouteBinding = ProjectKnowledgeRouteBinding;
export function createProjectEntitiesRouteModuleLoader(options: Readonly<{
  createBinding: (context: ProjectEntitiesRouteContext) => ProjectEntitiesRouteBinding;
}>): DesktopRouteModuleLoader {
  return createProjectKnowledgeRouteModuleLoader({
    routeId: PROJECT_ENTITIES_ROUTE_ID,
    contextUnavailableReason: 'project_entities_route_context_unavailable',
    bindingScopeMismatchReason: 'project_entities_route_binding_scope_mismatch',
    ...options,
  });
}
