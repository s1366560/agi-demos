import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createProjectKnowledgeRouteModuleLoader,
  type ProjectKnowledgeRouteBinding,
  type ProjectKnowledgeRouteContext,
} from './projectKnowledgeRouteModule';
import { PROJECT_COMMUNITIES_ROUTE_ID } from './projectCommunitiesClient';

export type ProjectCommunitiesRouteContext = ProjectKnowledgeRouteContext;
export type ProjectCommunitiesRouteBinding = ProjectKnowledgeRouteBinding;
export function createProjectCommunitiesRouteModuleLoader(options: Readonly<{
  createBinding: (context: ProjectCommunitiesRouteContext) => ProjectCommunitiesRouteBinding;
}>): DesktopRouteModuleLoader {
  return createProjectKnowledgeRouteModuleLoader({
    routeId: PROJECT_COMMUNITIES_ROUTE_ID,
    contextUnavailableReason: 'project_communities_route_context_unavailable',
    bindingScopeMismatchReason: 'project_communities_route_binding_scope_mismatch',
    ...options,
  });
}
