import type { DesktopRuntimeConfig } from '../../types';
import {
  isRecord,
  observeProjectAgentScope,
  projectAgentError,
  requestProjectAgentJson,
  requireNonnegativeInteger,
  requireProjectAgentScope,
  type ProjectAgentReadOptions,
  type ProjectAgentScope,
  type ProjectAgentSnapshotBase,
} from './projectAgentClient';
import { parseProjectAgentRuns, type ProjectAgentRun } from './projectAgentRuns';

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

const ACTIONS = Object.freeze(['view', 'list-runs', 'filter-status']);

export function createProjectAgentLogsClient(config: DesktopRuntimeConfig): ProjectAgentLogsClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireProjectAgentScope(
        runtimeConfig,
        scope,
        PROJECT_AGENT_LOGS_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectAgentScope(runtimeConfig, currentScope, options);
      const payload = await requestProjectAgentJson(runtimeConfig, {
        path: `/api/v1/agent/trace/runs/project/${encodeURIComponent(currentScope.projectId)}`,
        query: { status: options?.status, limit: options?.limit ?? 100 },
        signal: options?.signal,
      });
      if (!isRecord(payload) || payload.project_id !== currentScope.projectId) {
        throw projectAgentError('project_agent_logs_scope_conflict', 409);
      }
      const runs = parseProjectAgentRuns(payload.runs, 'project_agent_logs_contract_invalid');
      const total = requireNonnegativeInteger(payload.total, 'project_agent_logs_contract_invalid');
      if (total < runs.length) throw projectAgentError('project_agent_logs_contract_invalid');
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        allowedActions: ACTIONS,
        runs,
        total,
      });
    },
  });
}
