import {
  createProjectKnowledgeController,
  type ProjectKnowledgeController,
} from './projectKnowledgeController';
import type { ProjectKnowledgeAuthority, ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectEntitiesClient } from './projectEntitiesClient';
import { buildProjectEntitiesPresentation } from './projectEntitiesPresentationModel';

export type ProjectEntitiesController = ProjectKnowledgeController;
export function createProjectEntitiesController(options: Readonly<{
  authority: ProjectKnowledgeAuthority;
  client: ProjectEntitiesClient;
  initialScope: ProjectKnowledgeScope;
}>): ProjectEntitiesController {
  return createProjectKnowledgeController({
    ...options,
    buildPresentation: buildProjectEntitiesPresentation,
  });
}
