import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createProjectKnowledgeRouteModuleLoader,
  type ProjectKnowledgeRouteBinding,
  type ProjectKnowledgeRouteContext,
} from './projectKnowledgeRouteModule';
import { PROJECT_GRAPH_ROUTE_ID } from './projectGraphClient';

export type ProjectGraphRouteContext = ProjectKnowledgeRouteContext;
export type ProjectGraphRouteBinding = ProjectKnowledgeRouteBinding;
export function createProjectGraphRouteModuleLoader(options: Readonly<{
  createBinding: (context: ProjectGraphRouteContext) => ProjectGraphRouteBinding;
}>): DesktopRouteModuleLoader {
  return createProjectKnowledgeRouteModuleLoader({
    routeId: PROJECT_GRAPH_ROUTE_ID,
    contextUnavailableReason: 'project_graph_route_context_unavailable',
    bindingScopeMismatchReason: 'project_graph_route_binding_scope_mismatch',
    ...options,
  });
}
