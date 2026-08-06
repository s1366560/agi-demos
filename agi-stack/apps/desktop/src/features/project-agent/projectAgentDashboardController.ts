import type { ProjectAgentAuthority, ProjectAgentScope } from './projectAgentClient';
import {
  createProjectAgentController,
  type ProjectAgentController,
} from './projectAgentController';
import type { ProjectAgentDashboardClient } from './projectAgentDashboardClient';
import { buildProjectAgentDashboardPresentation } from './projectAgentDashboardPresentationModel';

export type ProjectAgentDashboardController = ProjectAgentController;
export function createProjectAgentDashboardController(
  options: Readonly<{
    authority: ProjectAgentAuthority;
    client: ProjectAgentDashboardClient;
    initialScope: ProjectAgentScope;
  }>,
): ProjectAgentDashboardController {
  return createProjectAgentController({
    ...options,
    failureReasonCodes: Object.freeze({
      forbidden: 'project_agent_dashboard_forbidden',
      unavailable: 'project_agent_dashboard_authority_unavailable',
      error: 'project_agent_dashboard_request_failed',
    }),
    buildPresentation: buildProjectAgentDashboardPresentation,
  });
}
