import type { ProjectAgentAuthority, ProjectAgentScope } from './projectAgentClient';
import {
  createProjectAgentController,
  type ProjectAgentController,
} from './projectAgentController';
import type { ProjectAgentLogsClient } from './projectAgentLogsClient';
import { buildProjectAgentLogsPresentation } from './projectAgentLogsPresentationModel';

export type ProjectAgentLogsController = ProjectAgentController;
export function createProjectAgentLogsController(
  options: Readonly<{
    authority: ProjectAgentAuthority;
    client: ProjectAgentLogsClient;
    initialScope: ProjectAgentScope;
  }>,
): ProjectAgentLogsController {
  return createProjectAgentController({
    ...options,
    failureReasonCodes: Object.freeze({
      forbidden: 'project_agent_logs_forbidden',
      unavailable: 'project_agent_logs_authority_unavailable',
      error: 'project_agent_logs_request_failed',
    }),
    buildPresentation: buildProjectAgentLogsPresentation,
  });
}
