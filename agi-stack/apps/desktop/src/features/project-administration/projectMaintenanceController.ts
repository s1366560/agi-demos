import {
  createProjectAdministrationController,
  type ProjectAdministrationController,
} from './projectAdministrationController';
import type { ProjectAdministrationScope } from './projectAdministrationClient';
import type { ProjectMaintenanceClient } from './projectMaintenanceClient';
import {
  buildProjectMaintenancePresentation,
  type ProjectMaintenanceViewModel,
} from './projectMaintenancePresentationModel';

export type ProjectMaintenanceController =
  ProjectAdministrationController<ProjectMaintenanceViewModel>;
export function createProjectMaintenanceController(options: Readonly<{
  client: ProjectMaintenanceClient;
  initialScope: ProjectAdministrationScope;
}>): ProjectMaintenanceController {
  return createProjectAdministrationController({
    ...options,
    buildPresentation: buildProjectMaintenancePresentation,
  });
}
