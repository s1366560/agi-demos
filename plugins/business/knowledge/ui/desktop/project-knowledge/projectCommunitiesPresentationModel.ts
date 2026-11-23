import type { ProjectKnowledgePresentationInput } from './projectKnowledgePresentationModel';
import { buildProjectKnowledgePresentation } from './projectKnowledgePresentationModel';
import {
  PROJECT_COMMUNITIES_ROUTE_ID,
  type ProjectCommunitiesSnapshot,
} from './projectCommunitiesClient';

export function buildProjectCommunitiesPresentation(
  input: ProjectKnowledgePresentationInput<ProjectCommunitiesSnapshot>,
) {
  return buildProjectKnowledgePresentation(PROJECT_COMMUNITIES_ROUTE_ID, input, (snapshot) =>
    Object.freeze({
      items: Object.freeze(
        snapshot.communities.map((community) =>
          Object.freeze({
            id: community.id,
            title: community.name,
            detail: community.summary,
            kind: String(community.memberCount),
          }),
        ),
      ),
      total: snapshot.total,
    }),
  );
}
