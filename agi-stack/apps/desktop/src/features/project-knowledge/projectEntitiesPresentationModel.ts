import type { ProjectKnowledgePresentationInput } from './projectKnowledgePresentationModel';
import { buildProjectKnowledgePresentation } from './projectKnowledgePresentationModel';
import { PROJECT_ENTITIES_ROUTE_ID, type ProjectEntitiesSnapshot } from './projectEntitiesClient';

export function buildProjectEntitiesPresentation(
  input: ProjectKnowledgePresentationInput<ProjectEntitiesSnapshot>,
) {
  return buildProjectKnowledgePresentation(PROJECT_ENTITIES_ROUTE_ID, input, (snapshot) =>
    Object.freeze({
      items: Object.freeze(
        snapshot.entities.map((entity) =>
          Object.freeze({
            id: entity.id,
            title: entity.name,
            detail: entity.summary,
            kind: entity.entityType,
          }),
        ),
      ),
      total: snapshot.total,
    }),
  );
}
