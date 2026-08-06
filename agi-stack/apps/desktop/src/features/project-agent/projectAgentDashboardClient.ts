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

const ACTIONS = Object.freeze(['view', 'list-runs', 'inspect-active-count']);

export function createProjectAgentDashboardClient(
  config: DesktopRuntimeConfig,
): ProjectAgentDashboardClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireProjectAgentScope(
        runtimeConfig,
        scope,
        PROJECT_AGENT_DASHBOARD_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectAgentScope(runtimeConfig, currentScope, options);
      const projectPath = encodeURIComponent(currentScope.projectId);
      const [runsPayload, countPayload] = await Promise.all([
        requestProjectAgentJson(runtimeConfig, {
          path: `/api/v1/agent/trace/runs/project/${projectPath}`,
          query: { limit: 8 },
          signal: options?.signal,
        }),
        requestProjectAgentJson(runtimeConfig, {
          path: `/api/v1/agent/trace/runs/project/${projectPath}/active/count`,
          signal: options?.signal,
        }),
      ]);
      if (
        !isRecord(runsPayload) ||
        !isRecord(countPayload) ||
        runsPayload.project_id !== currentScope.projectId ||
        countPayload.project_id !== currentScope.projectId
      ) {
        throw projectAgentError('project_agent_dashboard_scope_conflict', 409);
      }
      const runs = parseProjectAgentRuns(
        runsPayload.runs,
        'project_agent_dashboard_contract_invalid',
      );
      const total = requireNonnegativeInteger(
        runsPayload.total,
        'project_agent_dashboard_contract_invalid',
      );
      const activeCount = requireNonnegativeInteger(
        countPayload.active_count,
        'project_agent_dashboard_contract_invalid',
      );
      if (total < runs.length) throw projectAgentError('project_agent_dashboard_contract_invalid');
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        allowedActions: ACTIONS,
        runs,
        total,
        activeCount,
      });
    },
  });
}
