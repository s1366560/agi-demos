import type { DesktopRouteModuleLoader } from '../navigation/desktopRouteModule';
import { PROJECT_AGENT_DASHBOARD_ROUTE_ID } from './projectAgentDashboardClient';
import {
  createProjectAgentRouteModuleLoader,
  type ProjectAgentRouteBinding,
  type ProjectAgentRouteContext,
} from './projectAgentRouteModule';

export type ProjectAgentDashboardRouteContext = ProjectAgentRouteContext;
export type ProjectAgentDashboardRouteBinding = ProjectAgentRouteBinding;
export function createProjectAgentDashboardRouteModuleLoader(
  options: Readonly<{
    createBinding: (
      context: ProjectAgentDashboardRouteContext,
    ) => ProjectAgentDashboardRouteBinding;
  }>,
): DesktopRouteModuleLoader {
  return createProjectAgentRouteModuleLoader({
    routeId: PROJECT_AGENT_DASHBOARD_ROUTE_ID,
    contextUnavailableReason: 'project_agent_dashboard_route_context_unavailable',
    bindingScopeMismatchReason: 'project_agent_dashboard_route_binding_scope_mismatch',
    ...options,
  });
}
