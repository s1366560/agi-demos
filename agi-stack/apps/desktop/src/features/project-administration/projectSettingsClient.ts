import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';
import {
  isRecord,
  observeProjectAdministrationScope,
  optionalText,
  projectAdministrationError,
  requestProjectAdministrationJson,
  requestProjectAdministrationNoContent,
  requireBoolean,
  requireFiniteNumber,
  requireIdentifier,
  requireNonnegativeInteger,
  requireProjectAdministrationScope,
  type ProjectAdministrationOptions,
  type ProjectAdministrationScope,
  type ProjectAdministrationSnapshotBase,
  type ProjectMembershipRole,
} from './projectAdministrationClient';

export const PROJECT_SETTINGS_ROUTE_ID = 'project-project-settings' as const;
export const PROJECT_SETTINGS_LOCAL_REASON = 'local_project_settings_authority_unavailable' as const;

export type ProjectSettingsProject = Readonly<{
  id: string;
  tenantId: string;
  name: string;
  description: string | null;
  ownerId: string;
  isPublic: boolean;
  memoryRules: Readonly<{
    maxEpisodes: number;
    retentionDays: number;
    autoRefresh: boolean;
    refreshInterval: number;
  }>;
  graphConfig: Readonly<{
    maxNodes: number;
    maxEdges: number;
    similarityThreshold: number;
    communityDetection: boolean;
  }>;
  sandboxType: string;
  conversationMode: string;
  createdAt: string;
  updatedAt: string | null;
}>;
export type ProjectSettingsSandbox = Readonly<{
  id: string;
  status: string;
  healthy: boolean;
  createdAt: string;
}>;
export type ProjectSettingsSandboxStats = Readonly<{
  sandboxId: string;
  status: string;
  cpuPercent: number;
  memoryUsage: number;
  memoryLimit: number;
  memoryPercent: number;
  pids: number;
  collectedAt: string;
}>;
export type ProjectSettingsSnapshot = ProjectAdministrationSnapshotBase &
  Readonly<{
    project: ProjectSettingsProject;
    sandbox: ProjectSettingsSandbox | null;
    sandboxStats: ProjectSettingsSandboxStats | null;
  }>;
export type ProjectSettingsMutation = Readonly<Record<string, unknown>>;
export type ProjectSettingsClient = Readonly<{
  load(
    scope: ProjectAdministrationScope,
    options?: ProjectAdministrationOptions,
  ): Promise<ProjectSettingsSnapshot>;
  update(scope: ProjectAdministrationScope, input: ProjectSettingsMutation): Promise<void>;
  deleteProject(scope: ProjectAdministrationScope): Promise<void>;
  restartSandbox(scope: ProjectAdministrationScope): Promise<void>;
  terminateSandbox(scope: ProjectAdministrationScope): Promise<void>;
}>;

const READ_ACTIONS = ['view', 'inspect-sandbox'] as const;
const WRITE_ACTIONS = ['update', 'delete', 'restart-sandbox', 'terminate-sandbox'] as const;

export function createProjectSettingsClient(config: DesktopRuntimeConfig): ProjectSettingsClient {
  const runtimeConfig = Object.freeze({ ...config });
  const projectPath = (scope: ProjectAdministrationScope) =>
    `/api/v1/projects/${encodeURIComponent(scope.projectId)}`;
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireProjectAdministrationScope(
        runtimeConfig,
        scope,
        PROJECT_SETTINGS_LOCAL_REASON,
      );
      const authority = await observeProjectAdministrationScope(runtimeConfig, currentScope, options);
      const basePath = projectPath(currentScope);
      const [projectPayload, sandboxPayload, statsPayload] = await Promise.all([
        requestProjectAdministrationJson(runtimeConfig, basePath, options),
        optionalAuthority(() =>
          requestProjectAdministrationJson(runtimeConfig, `${basePath}/sandbox`, options),
        ),
        optionalAuthority(() =>
          requestProjectAdministrationJson(runtimeConfig, `${basePath}/sandbox/stats`, options),
        ),
      ]);
      const sandbox = sandboxPayload === null ? null : parseSandbox(sandboxPayload, currentScope);
      const sandboxStats =
        statsPayload === null ? null : parseSandboxStats(statsPayload, currentScope, sandbox);
      return Object.freeze({
        scope: currentScope,
        scopeRevision: authority.revision,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        contractVersion: '4.0.0',
        allowedActions: allowedActions(authority.membershipRole),
        membershipRole: authority.membershipRole,
        project: parseProject(projectPayload, currentScope),
        sandbox,
        sandboxStats,
      });
    },
    async update(scope, input) {
      const currentScope = requireProjectAdministrationScope(
        runtimeConfig,
        scope,
        PROJECT_SETTINGS_LOCAL_REASON,
      );
      await requestProjectAdministrationNoContent(runtimeConfig, projectPath(currentScope), {
        method: 'PATCH',
        body: input,
      });
    },
    async deleteProject(scope) {
      const currentScope = requireProjectAdministrationScope(
        runtimeConfig,
        scope,
        PROJECT_SETTINGS_LOCAL_REASON,
      );
      await requestProjectAdministrationNoContent(runtimeConfig, projectPath(currentScope), {
        method: 'DELETE',
      });
    },
    async restartSandbox(scope) {
      const currentScope = requireProjectAdministrationScope(
        runtimeConfig,
        scope,
        PROJECT_SETTINGS_LOCAL_REASON,
      );
      await requestProjectAdministrationNoContent(
        runtimeConfig,
        `${projectPath(currentScope)}/sandbox/restart`,
        { method: 'POST' },
      );
    },
    async terminateSandbox(scope) {
      const currentScope = requireProjectAdministrationScope(
        runtimeConfig,
        scope,
        PROJECT_SETTINGS_LOCAL_REASON,
      );
      await requestProjectAdministrationNoContent(
        runtimeConfig,
        `${projectPath(currentScope)}/sandbox`,
        { method: 'DELETE' },
      );
    },
  });
}

async function optionalAuthority(operation: () => Promise<unknown>): Promise<unknown | null> {
  try {
    return await operation();
  } catch (error) {
    if (error instanceof DesktopApiError && error.status === 404) return null;
    throw error;
  }
}

function allowedActions(role: ProjectMembershipRole): readonly string[] {
  return Object.freeze([
    ...READ_ACTIONS,
    ...(role === 'owner' || role === 'admin' ? WRITE_ACTIONS : []),
  ]);
}

function parseProject(
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
    name: requireIdentifier(payload.name, 'project_settings_contract_invalid'),
    description: optionalText(payload.description, 'project_settings_contract_invalid'),
    ownerId: requireIdentifier(payload.owner_id, 'project_settings_contract_invalid'),
    isPublic: requireBoolean(payload.is_public, 'project_settings_contract_invalid'),
    memoryRules: Object.freeze({
      maxEpisodes: requireNonnegativeInteger(
        payload.memory_rules.max_episodes,
        'project_settings_contract_invalid',
      ),
      retentionDays: requireNonnegativeInteger(
        payload.memory_rules.retention_days,
        'project_settings_contract_invalid',
      ),
      autoRefresh: requireBoolean(
        payload.memory_rules.auto_refresh,
        'project_settings_contract_invalid',
      ),
      refreshInterval: requireNonnegativeInteger(
        payload.memory_rules.refresh_interval,
        'project_settings_contract_invalid',
      ),
    }),
    graphConfig: Object.freeze({
      maxNodes: requireNonnegativeInteger(
        payload.graph_config.max_nodes,
        'project_settings_contract_invalid',
      ),
      maxEdges: requireNonnegativeInteger(
        payload.graph_config.max_edges,
        'project_settings_contract_invalid',
      ),
      similarityThreshold: requireFiniteNumber(
        payload.graph_config.similarity_threshold,
        'project_settings_contract_invalid',
      ),
      communityDetection: requireBoolean(
        payload.graph_config.community_detection,
        'project_settings_contract_invalid',
      ),
    }),
    sandboxType: requireIdentifier(
      payload.sandbox_config.sandbox_type,
      'project_settings_contract_invalid',
    ),
    conversationMode: requireIdentifier(
      payload.agent_conversation_mode,
      'project_settings_contract_invalid',
    ),
    createdAt: requireIdentifier(payload.created_at, 'project_settings_contract_invalid'),
    updatedAt: optionalText(payload.updated_at, 'project_settings_contract_invalid'),
  });
}

function parseSandbox(
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
    id: requireIdentifier(payload.sandbox_id, 'project_settings_sandbox_contract_invalid'),
    status: requireIdentifier(payload.status, 'project_settings_sandbox_contract_invalid'),
    healthy: requireBoolean(payload.is_healthy, 'project_settings_sandbox_contract_invalid'),
    createdAt: requireIdentifier(payload.created_at, 'project_settings_sandbox_contract_invalid'),
  });
}

function parseSandboxStats(
  payload: unknown,
  scope: ProjectAdministrationScope,
  sandbox: ProjectSettingsSandbox | null,
): ProjectSettingsSandboxStats {
  if (
    !isRecord(payload) ||
    payload.project_id !== scope.projectId ||
    (sandbox !== null && payload.sandbox_id !== sandbox.id)
  ) {
    throw projectAdministrationError('project_settings_sandbox_scope_conflict', 409);
  }
  return Object.freeze({
    sandboxId: requireIdentifier(
      payload.sandbox_id,
      'project_settings_sandbox_contract_invalid',
    ),
    status: requireIdentifier(payload.status, 'project_settings_sandbox_contract_invalid'),
    cpuPercent: requireFiniteNumber(
      payload.cpu_percent,
      'project_settings_sandbox_contract_invalid',
    ),
    memoryUsage: requireFiniteNumber(
      payload.memory_usage,
      'project_settings_sandbox_contract_invalid',
    ),
    memoryLimit: requireFiniteNumber(
      payload.memory_limit,
      'project_settings_sandbox_contract_invalid',
    ),
    memoryPercent: requireFiniteNumber(
      payload.memory_percent,
      'project_settings_sandbox_contract_invalid',
    ),
    pids: requireNonnegativeInteger(payload.pids, 'project_settings_sandbox_contract_invalid'),
    collectedAt: requireIdentifier(
      payload.collected_at,
      'project_settings_sandbox_contract_invalid',
    ),
  });
}
