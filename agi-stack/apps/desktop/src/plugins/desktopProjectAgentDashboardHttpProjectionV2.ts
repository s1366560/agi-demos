import {
  isRecord,
  observeProjectAgentScope,
  projectAgentError,
  requestProjectAgentJson,
  requireNonnegativeInteger,
  requireProjectAgentScope,
  type ProjectAgentScope,
} from '../features/project-agent/projectAgentClient';
import {
  PROJECT_AGENT_DASHBOARD_LOCAL_REASON,
  type ProjectAgentDashboardSnapshot,
} from '../features/project-agent/projectAgentDashboardClient';
import { parseProjectAgentRuns } from '../features/project-agent/projectAgentRuns';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectAgentDashboardRuntimeConfigV2,
  cloneDesktopProjectAgentDashboardScopeV2,
} from './desktopProjectAgentDashboardOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view', 'list-runs', 'inspect-active-count']);

export type DesktopProjectAgentDashboardHttpAuthorityV2 = Readonly<{
  load: (signal?: AbortSignal) => Promise<ProjectAgentDashboardSnapshot>;
}>;

export function createDesktopProjectAgentDashboardHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectAgentScope
): DesktopProjectAgentDashboardHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectAgentDashboardRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectAgentDashboardScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(signal) {
      const currentScope = requireProjectAgentScope(
        runtimeConfig,
        operationScope,
        PROJECT_AGENT_DASHBOARD_LOCAL_REASON
      );
      const scopeRevision = await observeProjectAgentScope(runtimeConfig, currentScope, {
        signal,
      });
      const projectPath = encodeURIComponent(currentScope.projectId);
      const [runsPayload, countPayload] = await Promise.all([
        requestProjectAgentJson(runtimeConfig, {
          path: `/api/v1/agent/trace/runs/project/${projectPath}`,
          query: { limit: 8 },
          signal,
        }),
        requestProjectAgentJson(runtimeConfig, {
          path: `/api/v1/agent/trace/runs/project/${projectPath}/active/count`,
          signal,
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
        'project_agent_dashboard_contract_invalid'
      );
      const total = requireNonnegativeInteger(
        runsPayload.total,
        'project_agent_dashboard_contract_invalid'
      );
      const activeCount = requireNonnegativeInteger(
        countPayload.active_count,
        'project_agent_dashboard_contract_invalid'
      );
      if (total < runs.length) {
        throw projectAgentError('project_agent_dashboard_contract_invalid');
      }
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        allowedActions: ACTIONS_V2,
        runs,
        total,
        activeCount,
      });
    },
  });
}
