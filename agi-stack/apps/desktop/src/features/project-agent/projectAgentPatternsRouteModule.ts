import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import { PROJECT_AGENT_PATTERNS_ROUTE_ID } from './projectAgentPatternsClient';
import {
  createProjectAgentRouteModuleLoader,
  type ProjectAgentRouteBinding,
  type ProjectAgentRouteContext,
} from './projectAgentRouteModule';

export type ProjectAgentPatternsRouteContext = ProjectAgentRouteContext;
export type ProjectAgentPatternsRouteBinding = ProjectAgentRouteBinding;
export function createProjectAgentPatternsRouteModuleLoader(
  options: Readonly<{
    createBinding: (context: ProjectAgentPatternsRouteContext) => ProjectAgentPatternsRouteBinding;
  }>,
): DesktopRouteModuleLoader {
  return createProjectAgentRouteModuleLoader({
    routeId: PROJECT_AGENT_PATTERNS_ROUTE_ID,
    contextUnavailableReason: 'project_agent_patterns_route_context_unavailable',
    bindingScopeMismatchReason: 'project_agent_patterns_route_binding_scope_mismatch',
    ...options,
  });
}
