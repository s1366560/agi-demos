import {
  createProjectKnowledgeController,
  type ProjectKnowledgeController,
} from './projectKnowledgeController';
import type { ProjectKnowledgeAuthority, ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectCommunitiesClient } from './projectCommunitiesClient';
import { buildProjectCommunitiesPresentation } from './projectCommunitiesPresentationModel';

export type ProjectCommunitiesController = ProjectKnowledgeController;
export function createProjectCommunitiesController(options: Readonly<{
  authority: ProjectKnowledgeAuthority;
  client: ProjectCommunitiesClient;
  initialScope: ProjectKnowledgeScope;
}>): ProjectCommunitiesController {
  return createProjectKnowledgeController({
    ...options,
    buildPresentation: buildProjectCommunitiesPresentation,
  });
}
