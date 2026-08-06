import {
  buildProjectAdministrationBase,
  type ProjectAdministrationPresentationState,
} from './projectAdministrationPresentationModel';
import {
  PROJECT_MAINTENANCE_ROUTE_ID,
  type ProjectMaintenanceSnapshot,
} from './projectMaintenanceClient';

export type ProjectMaintenanceViewModel = ReturnType<typeof buildProjectMaintenancePresentation>;

export function buildProjectMaintenancePresentation(
  input: ProjectAdministrationPresentationState<ProjectMaintenanceSnapshot>,
) {
  return Object.freeze({
    ...buildProjectAdministrationBase(PROJECT_MAINTENANCE_ROUTE_ID, input, Object.freeze([])),
    membershipRole: input.snapshot?.membershipRole ?? null,
    stats: input.snapshot?.stats ?? null,
    maintenanceStatus: input.snapshot?.maintenanceStatus ?? null,
    embeddingStatus: input.snapshot?.embeddingStatus ?? null,
  });
}
