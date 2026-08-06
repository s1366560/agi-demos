import {
  createProjectAdministrationController,
  type ProjectAdministrationController,
} from './projectAdministrationController';
import type { ProjectAdministrationScope } from './projectAdministrationClient';
import type { ProjectSettingsClient } from './projectSettingsClient';
import {
  buildProjectSettingsPresentation,
  type ProjectSettingsViewModel,
} from './projectSettingsPresentationModel';

export type ProjectSettingsController = ProjectAdministrationController<ProjectSettingsViewModel>;
export function createProjectSettingsController(options: Readonly<{
  client: ProjectSettingsClient;
  initialScope: ProjectAdministrationScope;
}>): ProjectSettingsController {
  return createProjectAdministrationController({
    ...options,
    buildPresentation: buildProjectSettingsPresentation,
  });
}
