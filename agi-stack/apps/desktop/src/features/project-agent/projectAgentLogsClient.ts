import type {
  ProjectAgentReadOptions,
  ProjectAgentScope,
  ProjectAgentSnapshotBase,
} from './projectAgentClient';
import type { ProjectAgentRun } from './projectAgentRuns';

export const PROJECT_AGENT_LOGS_ROUTE_ID = 'project-agent-logs' as const;
export const PROJECT_AGENT_LOGS_LOCAL_REASON =
  'local_project_agent_logs_authority_unavailable' as const;

export type ProjectAgentLogsReadOptions = ProjectAgentReadOptions &
  Readonly<{ status?: string; limit?: number }>;
export type ProjectAgentLogsSnapshot = ProjectAgentSnapshotBase &
  Readonly<{ runs: readonly ProjectAgentRun[]; total: number }>;
export type ProjectAgentLogsClient = Readonly<{
  load(
    scope: ProjectAgentScope,
    options?: ProjectAgentLogsReadOptions,
  ): Promise<ProjectAgentLogsSnapshot>;
}>;
