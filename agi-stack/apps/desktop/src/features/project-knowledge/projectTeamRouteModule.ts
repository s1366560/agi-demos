import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createProjectKnowledgeRouteModuleLoader,
  type ProjectKnowledgeRouteBinding,
  type ProjectKnowledgeRouteContext,
} from './projectKnowledgeRouteModule';
import { PROJECT_TEAM_ROUTE_ID } from './projectTeamClient';

export type ProjectTeamRouteContext = ProjectKnowledgeRouteContext;
export type ProjectTeamRouteBinding = ProjectKnowledgeRouteBinding;
export function createProjectTeamRouteModuleLoader(options: Readonly<{
  createBinding: (context: ProjectTeamRouteContext) => ProjectTeamRouteBinding;
}>): DesktopRouteModuleLoader {
  return createProjectKnowledgeRouteModuleLoader({
    routeId: PROJECT_TEAM_ROUTE_ID,
    contextUnavailableReason: 'project_team_route_context_unavailable',
    bindingScopeMismatchReason: 'project_team_route_binding_scope_mismatch',
    ...options,
  });
}
