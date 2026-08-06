import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import {
  createProjectKnowledgeRouteModuleLoader,
  type ProjectKnowledgeRouteBinding,
  type ProjectKnowledgeRouteContext,
} from './projectKnowledgeRouteModule';
import { PROJECT_MEMORIES_ROUTE_ID } from './projectMemoriesClient';

export type ProjectMemoriesRouteContext = ProjectKnowledgeRouteContext;
export type ProjectMemoriesRouteBinding = ProjectKnowledgeRouteBinding;
export function createProjectMemoriesRouteModuleLoader(options: Readonly<{
  createBinding: (context: ProjectMemoriesRouteContext) => ProjectMemoriesRouteBinding;
}>): DesktopRouteModuleLoader {
  return createProjectKnowledgeRouteModuleLoader({
    routeId: PROJECT_MEMORIES_ROUTE_ID,
    contextUnavailableReason: 'project_memories_route_context_unavailable',
    bindingScopeMismatchReason: 'project_memories_route_binding_scope_mismatch',
    ...options,
  });
}
