import {
  createProjectAdministrationController,
  type ProjectAdministrationController,
} from './projectAdministrationController';
import type { ProjectAdministrationScope } from './projectAdministrationClient';
import type { ProjectSchemaClient } from './projectSchemaClient';
import {
  buildProjectSchemaPresentation,
  type ProjectSchemaViewModel,
} from './projectSchemaPresentationModel';

export type ProjectSchemaController = ProjectAdministrationController<ProjectSchemaViewModel>;
export function createProjectSchemaController(options: Readonly<{
  client: ProjectSchemaClient;
  initialScope: ProjectAdministrationScope;
}>): ProjectSchemaController {
  return createProjectAdministrationController({
    ...options,
    buildPresentation: buildProjectSchemaPresentation,
  });
}
