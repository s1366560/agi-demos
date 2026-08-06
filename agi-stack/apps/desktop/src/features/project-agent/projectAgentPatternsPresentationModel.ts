import {
  PROJECT_AGENT_PATTERNS_ROUTE_ID,
  type ProjectAgentPatternsSnapshot,
} from './projectAgentPatternsClient';
import type { ProjectAgentPresentationInput } from './projectAgentPresentationModel';
import { buildProjectAgentPresentation } from './projectAgentPresentationModel';

export function buildProjectAgentPatternsPresentation(
  input: ProjectAgentPresentationInput<ProjectAgentPatternsSnapshot>,
) {
  return buildProjectAgentPresentation(PROJECT_AGENT_PATTERNS_ROUTE_ID, input, (snapshot) =>
    Object.freeze({
      items: Object.freeze(
        snapshot.patterns.map((pattern) =>
          Object.freeze({
            id: pattern.id,
            title: pattern.name,
            detail: pattern.description,
            status: snapshot.scopeKind,
            createdAt: pattern.createdAt,
          }),
        ),
      ),
      total: snapshot.total,
      metrics: Object.freeze({ scopeKind: snapshot.scopeKind }),
    }),
  );
}
