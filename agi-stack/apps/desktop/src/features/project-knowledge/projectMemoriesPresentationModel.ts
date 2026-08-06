import type { ProjectKnowledgePresentationInput } from './projectKnowledgePresentationModel';
import { buildProjectKnowledgePresentation } from './projectKnowledgePresentationModel';
import { PROJECT_MEMORIES_ROUTE_ID, type ProjectMemoriesSnapshot } from './projectMemoriesClient';

export function buildProjectMemoriesPresentation(
  input: ProjectKnowledgePresentationInput<ProjectMemoriesSnapshot>,
) {
  return buildProjectKnowledgePresentation(PROJECT_MEMORIES_ROUTE_ID, input, (snapshot) =>
    Object.freeze({
      items: Object.freeze(
        snapshot.memories.map((memory) =>
          Object.freeze({
            id: memory.id,
            title: memory.title,
            detail: memory.content,
            kind: memory.processingStatus,
          }),
        ),
      ),
      total: snapshot.total,
    }),
  );
}
