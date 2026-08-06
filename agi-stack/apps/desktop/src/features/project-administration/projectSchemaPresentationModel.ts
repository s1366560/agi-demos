import {
  buildProjectAdministrationBase,
  type ProjectAdministrationPresentationState,
} from './projectAdministrationPresentationModel';
import { PROJECT_SCHEMA_ROUTE_ID, type ProjectSchemaSnapshot } from './projectSchemaClient';

export type ProjectSchemaViewModel = ReturnType<typeof buildProjectSchemaPresentation>;

export function buildProjectSchemaPresentation(
  input: ProjectAdministrationPresentationState<ProjectSchemaSnapshot>,
) {
  const entityTypes = input.snapshot?.entityTypes ?? Object.freeze([]);
  const edgeTypes = input.snapshot?.edgeTypes ?? Object.freeze([]);
  const mappings = input.snapshot?.mappings ?? Object.freeze([]);
  return Object.freeze({
    ...buildProjectAdministrationBase(
      PROJECT_SCHEMA_ROUTE_ID,
      input,
      entityTypes.map((item) =>
        Object.freeze({ id: item.id, title: item.name, detail: item.description ?? item.status }),
      ),
    ),
    membershipRole: input.snapshot?.membershipRole ?? null,
    entityTypes,
    edgeTypes,
    mappings,
  });
}
