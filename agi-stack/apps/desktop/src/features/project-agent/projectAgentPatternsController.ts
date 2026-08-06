import type { ProjectAgentAuthority, ProjectAgentScope } from './projectAgentClient';
import {
  createProjectAgentController,
  type ProjectAgentController,
} from './projectAgentController';
import type { ProjectAgentPatternsClient } from './projectAgentPatternsClient';
import { buildProjectAgentPatternsPresentation } from './projectAgentPatternsPresentationModel';

export type ProjectAgentPatternsController = ProjectAgentController;
export function createProjectAgentPatternsController(
  options: Readonly<{
    authority: ProjectAgentAuthority;
    client: ProjectAgentPatternsClient;
    initialScope: ProjectAgentScope;
  }>,
): ProjectAgentPatternsController {
  return createProjectAgentController({
    ...options,
    failureReasonCodes: Object.freeze({
      forbidden: 'project_agent_patterns_forbidden',
      unavailable: 'project_agent_patterns_authority_unavailable',
      error: 'project_agent_patterns_request_failed',
    }),
    buildPresentation: buildProjectAgentPatternsPresentation,
  });
}
