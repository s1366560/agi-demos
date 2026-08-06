import {
  createProjectKnowledgeController,
  type ProjectKnowledgeController,
} from './projectKnowledgeController';
import type { ProjectKnowledgeAuthority, ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectMemoriesClient } from './projectMemoriesClient';
import { buildProjectMemoriesPresentation } from './projectMemoriesPresentationModel';

export type ProjectMemoriesController = ProjectKnowledgeController;
export function createProjectMemoriesController(options: Readonly<{
  authority: ProjectKnowledgeAuthority;
  client: ProjectMemoriesClient;
  initialScope: ProjectKnowledgeScope;
}>): ProjectMemoriesController {
  return createProjectKnowledgeController({
    ...options,
    buildPresentation: buildProjectMemoriesPresentation,
  });
}
