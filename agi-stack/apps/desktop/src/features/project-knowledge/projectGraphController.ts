import {
  createProjectKnowledgeController,
  type ProjectKnowledgeController,
} from './projectKnowledgeController';
import type { ProjectKnowledgeAuthority, ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectGraphClient } from './projectGraphClient';
import { buildProjectGraphPresentation } from './projectGraphPresentationModel';

export type ProjectGraphController = ProjectKnowledgeController;
export function createProjectGraphController(options: Readonly<{
  authority: ProjectKnowledgeAuthority;
  client: ProjectGraphClient;
  initialScope: ProjectKnowledgeScope;
}>): ProjectGraphController {
  return createProjectKnowledgeController({
    ...options,
    buildPresentation: buildProjectGraphPresentation,
  });
}
