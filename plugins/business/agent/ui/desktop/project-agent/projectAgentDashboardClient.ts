import type {
  ProjectAgentReadOptions,
  ProjectAgentScope,
  ProjectAgentSnapshotBase,
} from './projectAgentClient';
import type { ProjectAgentRun } from './projectAgentRuns';

export const PROJECT_AGENT_DASHBOARD_ROUTE_ID = 'project-agent-dashboard' as const;
export const PROJECT_AGENT_DASHBOARD_LOCAL_REASON =
  'local_project_agent_dashboard_authority_unavailable' as const;

export type ProjectAgentDashboardSnapshot = ProjectAgentSnapshotBase &
  Readonly<{
    runs: readonly ProjectAgentRun[];
    total: number;
    activeCount: number;
  }>;
export type ProjectAgentDashboardClient = Readonly<{
  load(
    scope: ProjectAgentScope,
    options?: ProjectAgentReadOptions,
  ): Promise<ProjectAgentDashboardSnapshot>;
}>;
