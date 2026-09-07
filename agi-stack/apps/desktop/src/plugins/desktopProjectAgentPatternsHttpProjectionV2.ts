import {
  isRecord,
  observeProjectAgentScope,
  projectAgentError,
  requestProjectAgentJson,
  requireFiniteNumber,
  requireIdentifier,
  requireNonnegativeInteger,
  requireProjectAgentScope,
  requireText,
  type ProjectAgentScope,
} from '../features/project-agent/projectAgentClient';
import {
  PROJECT_AGENT_PATTERNS_LOCAL_REASON,
  type ProjectAgentPattern,
  type ProjectAgentPatternsSnapshot,
} from '../features/project-agent/projectAgentPatternsClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectAgentPatternsRuntimeConfigV2,
  cloneDesktopProjectAgentPatternsScopeV2,
} from './desktopProjectAgentPatternsOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view', 'list-patterns', 'inspect-shared-scope']);

export type DesktopProjectAgentPatternsHttpAuthorityV2 = Readonly<{
  load: (signal?: AbortSignal) => Promise<ProjectAgentPatternsSnapshot>;
}>;

export function createDesktopProjectAgentPatternsHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectAgentScope,
): DesktopProjectAgentPatternsHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectAgentPatternsRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectAgentPatternsScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(signal) {
      const currentScope = requireProjectAgentScope(
        runtimeConfig,
        operationScope,
        PROJECT_AGENT_PATTERNS_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectAgentScope(runtimeConfig, currentScope, { signal });
      const payload = await requestProjectAgentJson(runtimeConfig, {
        path: `/api/v1/agent/workflows/patterns/project/${encodeURIComponent(currentScope.projectId)}`,
        query: { page: 1, page_size: 100 },
        signal,
      });
      if (
        !isRecord(payload) ||
        payload.project_id !== currentScope.projectId ||
        payload.tenant_id !== currentScope.tenantId ||
        payload.scope_kind !== 'tenant_shared'
      ) {
        throw projectAgentError('project_agent_patterns_scope_conflict', 409);
      }
      if (!Array.isArray(payload.patterns)) {
        throw projectAgentError('project_agent_patterns_contract_invalid');
      }
      const patterns = Object.freeze(
        payload.patterns.map((value) => parsePatternV2(value, currentScope)),
      );
      const total = requireNonnegativeInteger(
        payload.total,
        'project_agent_patterns_contract_invalid',
      );
      if (total < patterns.length) {
        throw projectAgentError('project_agent_patterns_contract_invalid');
      }
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        allowedActions: ACTIONS_V2,
        scopeKind: 'tenant_shared',
        patterns,
        total,
      });
    },
  });
}

function parsePatternV2(value: unknown, scope: ProjectAgentScope): ProjectAgentPattern {
  if (!isRecord(value) || value.tenant_id !== scope.tenantId) {
    throw projectAgentError('project_agent_patterns_scope_conflict', 409);
  }
  const successRate = requireFiniteNumber(
    value.success_rate,
    'project_agent_patterns_contract_invalid',
  );
  if (successRate < 0 || successRate > 1) {
    throw projectAgentError('project_agent_patterns_contract_invalid');
  }
  return Object.freeze({
    id: requireIdentifier(value.id, 'project_agent_patterns_contract_invalid'),
    tenantId: scope.tenantId,
    name: requireIdentifier(value.name, 'project_agent_patterns_contract_invalid'),
    description: requireText(value.description, 'project_agent_patterns_contract_invalid'),
    successRate,
    usageCount: requireNonnegativeInteger(
      value.usage_count,
      'project_agent_patterns_contract_invalid',
    ),
    createdAt: requireIdentifier(value.created_at, 'project_agent_patterns_contract_invalid'),
  });
}
