import type { ProjectKnowledgePresentationInput } from './projectKnowledgePresentationModel';
import { buildProjectKnowledgePresentation } from './projectKnowledgePresentationModel';
import { PROJECT_GRAPH_ROUTE_ID, type ProjectGraphSnapshot } from './projectGraphClient';

export function buildProjectGraphPresentation(
  input: ProjectKnowledgePresentationInput<ProjectGraphSnapshot>,
) {
  return buildProjectKnowledgePresentation(PROJECT_GRAPH_ROUTE_ID, input, (snapshot) =>
    Object.freeze({
      items: Object.freeze(
        snapshot.nodes.map((node) =>
          Object.freeze({
            id: node.id,
            title: node.name,
            detail: node.summary,
            kind: node.type,
          }),
        ),
      ),
      total: snapshot.nodes.length,
    }),
  );
}
