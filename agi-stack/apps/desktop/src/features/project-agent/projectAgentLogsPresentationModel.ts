import {
  PROJECT_AGENT_LOGS_ROUTE_ID,
  type ProjectAgentLogsSnapshot,
} from './projectAgentLogsClient';
import type { ProjectAgentPresentationInput } from './projectAgentPresentationModel';
import { buildProjectAgentPresentation } from './projectAgentPresentationModel';

export function buildProjectAgentLogsPresentation(
  input: ProjectAgentPresentationInput<ProjectAgentLogsSnapshot>,
) {
  return buildProjectAgentPresentation(PROJECT_AGENT_LOGS_ROUTE_ID, input, (snapshot) =>
    Object.freeze({
      items: Object.freeze(
        snapshot.runs.map((run) =>
          Object.freeze({
            id: run.id,
            title: run.title,
            detail: run.detail,
            status: run.status,
            createdAt: run.createdAt,
          }),
        ),
      ),
      total: snapshot.total,
    }),
  );
}
