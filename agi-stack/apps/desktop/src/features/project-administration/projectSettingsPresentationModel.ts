import {
  buildProjectAdministrationBase,
  type ProjectAdministrationPresentationState,
} from './projectAdministrationPresentationModel';
import {
  PROJECT_SETTINGS_ROUTE_ID,
  type ProjectSettingsSnapshot,
} from './projectSettingsClient';

export type ProjectSettingsViewModel = ReturnType<typeof buildProjectSettingsPresentation>;

export function buildProjectSettingsPresentation(
  input: ProjectAdministrationPresentationState<ProjectSettingsSnapshot>,
) {
  const project = input.snapshot?.project ?? null;
  return Object.freeze({
    ...buildProjectAdministrationBase(
      PROJECT_SETTINGS_ROUTE_ID,
      input,
      project
        ? Object.freeze([
            Object.freeze({
              id: project.id,
              title: project.name,
              detail: project.description ?? project.sandboxType,
            }),
          ])
        : Object.freeze([]),
    ),
    membershipRole: input.snapshot?.membershipRole ?? null,
    project,
    sandbox: input.snapshot?.sandbox ?? null,
    sandboxStats: input.snapshot?.sandboxStats ?? null,
  });
}
