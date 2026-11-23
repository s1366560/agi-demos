import { PROJECT_AGENT_DASHBOARD_ROUTE_ID } from './projectAgentDashboardClient';
import type { ProjectAgentDashboardSnapshot } from './projectAgentDashboardClient';
import type { ProjectAgentPresentationInput } from './projectAgentPresentationModel';
import { buildProjectAgentPresentation } from './projectAgentPresentationModel';

export function buildProjectAgentDashboardPresentation(
  input: ProjectAgentPresentationInput<ProjectAgentDashboardSnapshot>,
) {
  return buildProjectAgentPresentation(PROJECT_AGENT_DASHBOARD_ROUTE_ID, input, (snapshot) =>
    Object.freeze({
      items: Object.freeze(snapshot.runs.map(runItem)),
      total: snapshot.total,
      metrics: Object.freeze({
        activeCount: snapshot.activeCount,
        recentRuns: snapshot.runs.length,
      }),
    }),
  );
}

function runItem(run: ProjectAgentDashboardSnapshot['runs'][number]) {
  return Object.freeze({
    id: run.id,
    title: run.title,
    detail: run.detail,
    status: run.status,
    createdAt: run.createdAt,
  });
}
