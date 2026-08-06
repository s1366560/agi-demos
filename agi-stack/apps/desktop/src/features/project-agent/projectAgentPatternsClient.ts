import type { DesktopRuntimeConfig } from '../../types';
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
  type ProjectAgentReadOptions,
  type ProjectAgentScope,
  type ProjectAgentSnapshotBase,
} from './projectAgentClient';

export const PROJECT_AGENT_PATTERNS_ROUTE_ID = 'project-agent-patterns' as const;
export const PROJECT_AGENT_PATTERNS_LOCAL_REASON =
  'local_project_agent_patterns_authority_unavailable' as const;

export type ProjectAgentPattern = Readonly<{
  id: string;
  tenantId: string;
  name: string;
  description: string;
  successRate: number;
  usageCount: number;
  createdAt: string;
}>;
export type ProjectAgentPatternsSnapshot = ProjectAgentSnapshotBase &
  Readonly<{
    scopeKind: 'tenant_shared';
    patterns: readonly ProjectAgentPattern[];
    total: number;
  }>;
export type ProjectAgentPatternsClient = Readonly<{
  load(
    scope: ProjectAgentScope,
    options?: ProjectAgentReadOptions,
  ): Promise<ProjectAgentPatternsSnapshot>;
}>;

const ACTIONS = Object.freeze(['view', 'list-patterns', 'inspect-shared-scope']);

export function createProjectAgentPatternsClient(
  config: DesktopRuntimeConfig,
): ProjectAgentPatternsClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireProjectAgentScope(
        runtimeConfig,
        scope,
        PROJECT_AGENT_PATTERNS_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectAgentScope(runtimeConfig, currentScope, options);
      const payload = await requestProjectAgentJson(runtimeConfig, {
        path: `/api/v1/agent/workflows/patterns/project/${encodeURIComponent(currentScope.projectId)}`,
        query: { page: 1, page_size: 100 },
        signal: options?.signal,
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
        payload.patterns.map((value) => parsePattern(value, currentScope)),
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
        allowedActions: ACTIONS,
        scopeKind: 'tenant_shared',
        patterns,
        total,
      });
    },
  });
}

function parsePattern(value: unknown, scope: ProjectAgentScope): ProjectAgentPattern {
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
