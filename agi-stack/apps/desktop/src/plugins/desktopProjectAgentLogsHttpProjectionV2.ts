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
  PROJECT_AGENT_LOGS_LOCAL_REASON,
  type ProjectAgentLogsSnapshot,
} from '../features/project-agent/projectAgentLogsClient';
import { parseProjectAgentRuns } from '../features/project-agent/projectAgentRuns';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectAgentLogsRuntimeConfigV2,
  cloneDesktopProjectAgentLogsScopeV2,
} from './desktopProjectAgentLogsOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view', 'list-runs', 'filter-status']);

export type DesktopProjectAgentLogsHttpAuthorityV2 = Readonly<{
  load: (
    status?: string,
    limit?: number,
    signal?: AbortSignal
  ) => Promise<ProjectAgentLogsSnapshot>;
}>;

export function createDesktopProjectAgentLogsHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectAgentScope
): DesktopProjectAgentLogsHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectAgentLogsRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectAgentLogsScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(status, limit = 100, signal) {
      const currentScope = requireProjectAgentScope(
        runtimeConfig,
        operationScope,
        PROJECT_AGENT_LOGS_LOCAL_REASON
      );
      const scopeRevision = await observeProjectAgentScope(runtimeConfig, currentScope, { signal });
      const payload = await requestProjectAgentJson(runtimeConfig, {
        path: `/api/v1/agent/trace/runs/project/${encodeURIComponent(currentScope.projectId)}`,
        query: { status, limit },
        signal,
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
        allowedActions: ACTIONS_V2,
        runs,
        total,
      });
    },
  });
}
