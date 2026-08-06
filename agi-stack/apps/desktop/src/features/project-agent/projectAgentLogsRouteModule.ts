import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import { PROJECT_AGENT_LOGS_ROUTE_ID } from './projectAgentLogsClient';
import {
  createProjectAgentRouteModuleLoader,
  type ProjectAgentRouteBinding,
  type ProjectAgentRouteContext,
} from './projectAgentRouteModule';

export type ProjectAgentLogsRouteContext = ProjectAgentRouteContext;
export type ProjectAgentLogsRouteBinding = ProjectAgentRouteBinding;
export function createProjectAgentLogsRouteModuleLoader(
  options: Readonly<{
    createBinding: (context: ProjectAgentLogsRouteContext) => ProjectAgentLogsRouteBinding;
  }>,
): DesktopRouteModuleLoader {
  return createProjectAgentRouteModuleLoader({
    routeId: PROJECT_AGENT_LOGS_ROUTE_ID,
    contextUnavailableReason: 'project_agent_logs_route_context_unavailable',
    bindingScopeMismatchReason: 'project_agent_logs_route_binding_scope_mismatch',
    ...options,
  });
}
