import { DesktopApiError } from '../api/client';

import {
  isRecord,
  observeProjectAdministrationScope,
  optionalText,
  projectAdministrationError,
  requestProjectAdministrationJson,
  requireBoolean,
  requireFiniteNumber,
  requireIdentifier,
  requireNonnegativeInteger,
  requireProjectAdministrationScope,
  type ProjectAdministrationScope,
} from '../features/project-administration/projectAdministrationClient';
import {
  PROJECT_SETTINGS_DEGRADED_REASON,
  PROJECT_SETTINGS_LOCAL_REASON,
  type ProjectSettingsProject,
  type ProjectSettingsSandbox,
  type ProjectSettingsSandboxStats,
  type ProjectSettingsSnapshot,
} from '../features/project-administration/projectSettingsClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectSettingsRuntimeConfigV2,
  cloneDesktopProjectSettingsScopeV2,
} from './desktopProjectSettingsOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view']);

export type DesktopProjectSettingsHttpAuthorityV2 = Readonly<{
  load: (signal?: AbortSignal) => Promise<ProjectSettingsSnapshot>;
}>;

export function createDesktopProjectSettingsHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectAdministrationScope,
): DesktopProjectSettingsHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectSettingsRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectSettingsScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(signal) {
      const currentScope = requireProjectAdministrationScope(
        runtimeConfig,
        operationScope,
        PROJECT_SETTINGS_LOCAL_REASON,
      );
      const authority = await observeProjectAdministrationScope(runtimeConfig, currentScope, {
        signal,
      });
      const basePath = `/api/v1/projects/${encodeURIComponent(currentScope.projectId)}`;
      const [projectPayload, sandboxPayload, statsPayload] = await Promise.all([
        requestProjectAdministrationJson(runtimeConfig, basePath, {
          signal, query: { tenant_id: currentScope.tenantId },
        }),
        optionalAuthorityV2(() =>
          requestProjectAdministrationJson(runtimeConfig, `${basePath}/sandbox`, { signal }),
        ),
        optionalAuthorityV2(() =>
          requestProjectAdministrationJson(runtimeConfig, `${basePath}/sandbox/stats`, { signal }),
        ),
      ]);
      const sandbox =
        sandboxPayload === null ? null : parseProjectSettingsSandboxV2(sandboxPayload, currentScope);
      const sandboxStats =
        statsPayload === null
          ? null
          : parseProjectSettingsSandboxStatsV2(statsPayload, currentScope, sandbox);
      return Object.freeze({
        scope: currentScope,
        scopeRevision: authority.revision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_SETTINGS_DEGRADED_REASON,
        contractVersion: '4.0.0',
        allowedActions: ACTIONS_V2,
        membershipRole: authority.membershipRole,
        project: parseProjectSettingsProjectV2(projectPayload, currentScope),
        sandbox,
        sandboxStats,
      });
    },
  });
}

async function optionalAuthorityV2(operation: () => Promise<unknown>): Promise<unknown | null> {
  try {
    return await operation();
  } catch (error) {
    if (error instanceof DesktopApiError && error.status === 404) return null;
    throw error;
  }
}

function parseProjectSettingsProjectV2(
  payload: unknown,
  scope: ProjectAdministrationScope,
): ProjectSettingsProject {
  if (
    !isRecord(payload) ||
    payload.id !== scope.projectId ||
    payload.tenant_id !== scope.tenantId ||
    !isRecord(payload.memory_rules) ||
    !isRecord(payload.graph_config) ||
    !isRecord(payload.sandbox_config)
  ) {
    throw projectAdministrationError('project_settings_scope_conflict', 409);
  }
  return Object.freeze({
    id: scope.projectId,
    tenantId: scope.tenantId,
    name: requireIdentifier(payload.name, invalidContractCodeV2()),
    description: optionalText(payload.description, invalidContractCodeV2()),
    ownerId: requireIdentifier(payload.owner_id, invalidContractCodeV2()),
    isPublic: requireBoolean(payload.is_public, invalidContractCodeV2()),
    memoryRules: Object.freeze({
      maxEpisodes: requireNonnegativeInteger(
        payload.memory_rules.max_episodes,
        invalidContractCodeV2(),
      ),
      retentionDays: requireNonnegativeInteger(
        payload.memory_rules.retention_days,
        invalidContractCodeV2(),
      ),
      autoRefresh: requireBoolean(payload.memory_rules.auto_refresh, invalidContractCodeV2()),
      refreshInterval: requireNonnegativeInteger(
        payload.memory_rules.refresh_interval,
        invalidContractCodeV2(),
      ),
    }),
    graphConfig: Object.freeze({
      maxNodes: requireNonnegativeInteger(payload.graph_config.max_nodes, invalidContractCodeV2()),
      maxEdges: requireNonnegativeInteger(payload.graph_config.max_edges, invalidContractCodeV2()),
      similarityThreshold: requireFiniteNumber(
        payload.graph_config.similarity_threshold,
        invalidContractCodeV2(),
      ),
      communityDetection: requireBoolean(
        payload.graph_config.community_detection,
        invalidContractCodeV2(),
      ),
    }),
    sandboxType: requireIdentifier(payload.sandbox_config.sandbox_type, invalidContractCodeV2()),
    conversationMode: requireIdentifier(payload.agent_conversation_mode, invalidContractCodeV2()),
    createdAt: requireIdentifier(payload.created_at, invalidContractCodeV2()),
    updatedAt: optionalText(payload.updated_at, invalidContractCodeV2()),
  });
}

function parseProjectSettingsSandboxV2(
  payload: unknown,
  scope: ProjectAdministrationScope,
): ProjectSettingsSandbox {
  if (
    !isRecord(payload) ||
    payload.project_id !== scope.projectId ||
    payload.tenant_id !== scope.tenantId
  ) {
    throw projectAdministrationError('project_settings_sandbox_scope_conflict', 409);
  }
  return Object.freeze({
    id: requireIdentifier(payload.sandbox_id, sandboxContractCodeV2()),
    status: requireIdentifier(payload.status, sandboxContractCodeV2()),
    healthy: requireBoolean(payload.is_healthy, sandboxContractCodeV2()),
    createdAt: requireIdentifier(payload.created_at, sandboxContractCodeV2()),
  });
}

function parseProjectSettingsSandboxStatsV2(
  payload: unknown,
  scope: ProjectAdministrationScope,
  sandbox: ProjectSettingsSandbox | null,
): ProjectSettingsSandboxStats {
  if (
    !isRecord(payload) ||
    sandbox === null ||
    payload.project_id !== scope.projectId ||
    payload.sandbox_id !== sandbox.id
  ) {
    throw projectAdministrationError('project_settings_sandbox_scope_conflict', 409);
  }
  return Object.freeze({
    sandboxId: requireIdentifier(payload.sandbox_id, sandboxContractCodeV2()),
    status: requireIdentifier(payload.status, sandboxContractCodeV2()),
    cpuPercent: requireFiniteNumber(payload.cpu_percent, sandboxContractCodeV2()),
    memoryUsage: requireFiniteNumber(payload.memory_usage, sandboxContractCodeV2()),
    memoryLimit: requireFiniteNumber(payload.memory_limit, sandboxContractCodeV2()),
    memoryPercent: requireFiniteNumber(payload.memory_percent, sandboxContractCodeV2()),
    pids: requireNonnegativeInteger(payload.pids, sandboxContractCodeV2()),
    collectedAt: requireIdentifier(payload.collected_at, sandboxContractCodeV2()),
  });
}

function invalidContractCodeV2(): string {
  return 'project_settings_contract_invalid';
}

function sandboxContractCodeV2(): string {
  return 'project_settings_sandbox_contract_invalid';
}
