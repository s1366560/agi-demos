import {
  createProjectKnowledgeController,
  type ProjectKnowledgeController,
} from './projectKnowledgeController';
import type { ProjectKnowledgeAuthority, ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectTeamClient } from './projectTeamClient';
import { buildProjectTeamPresentation } from './projectTeamPresentationModel';

export type ProjectTeamController = ProjectKnowledgeController;
export function createProjectTeamController(options: Readonly<{
  authority: ProjectKnowledgeAuthority;
  client: ProjectTeamClient;
  initialScope: ProjectKnowledgeScope;
}>): ProjectTeamController {
  return createProjectKnowledgeController({
    ...options,
    buildPresentation: buildProjectTeamPresentation,
  });
}
