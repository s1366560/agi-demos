import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../../api/client';
import {
  desktopApiAuthenticationAvailable,
  desktopApiFetch,
} from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import type {
  ProjectWorkspaceAgentBinding,
  ProjectWorkspaceMember,
  ProjectWorkspaceRecord,
  ProjectWorkspacesClient,
  ProjectWorkspacesRequestOptions,
  ProjectWorkspacesScope,
  ProjectWorkspacesSnapshot,
} from './projectWorkspacesClient';

const CONTRACT_VERSION = '1.0.0' as const;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'create',
  'update',
  'add-member',
  'update-member-role',
  'remove-member',
  'bind-agent',
  'unbind-agent',
  'open-blackboard',
]);
const LOCAL_ACTIONS = Object.freeze(['view', 'list', 'create', 'open-blackboard']);

type RequestOptions = ProjectWorkspacesRequestOptions &
  Readonly<{
    method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
    body?: Record<string, unknown>;
  }>;

export function createProjectWorkspacesHttpClient(
  config: DesktopRuntimeConfig,
): ProjectWorkspacesClient {
  const runtimeConfig = Object.freeze({ ...config });
  requireRuntimeCredentials(runtimeConfig);
  const client: ProjectWorkspacesClient = {
    async list(scope, options) {
      const currentScope = requireScope(runtimeConfig, scope);
      const payload = await requestJson(
        runtimeConfig,
        `${workspaceBase(currentScope)}?limit=500&offset=0`,
        options,
      );
      const workspaces = requireCollection(payload, ['items', 'workspaces']).map((item) =>
        requireWorkspace(item, currentScope),
      );
      return Object.freeze({
        scope: currentScope,
        authority: currentScope.authority,
        availability: currentScope.authority === 'cloud' ? 'available' : 'degraded',
        reasonCode:
          currentScope.authority === 'cloud' ? null : 'local_workspace_lifecycle_partial',
        serviceVersion: currentScope.authority === 'cloud' ? 'cloud' : 'sidecar',
        contractVersion: CONTRACT_VERSION,
        authorityRevision: null,
        allowedActions: currentScope.authority === 'cloud' ? CLOUD_ACTIONS : LOCAL_ACTIONS,
        workspaces: Object.freeze(workspaces),
      }) satisfies ProjectWorkspacesSnapshot;
    },
    async create(scope, input, options) {
      const currentScope = requireScope(runtimeConfig, scope);
      const payload = await requestJson(runtimeConfig, workspaceBase(currentScope), {
        ...options,
        method: 'POST',
        body: {
          name: requireInputText(input.name, 'project_workspace_name_required'),
          description: input.description.trim(),
          use_case: 'conversation',
          collaboration_mode: 'multi_agent_shared',
          metadata: {
            source: 'desktop',
            workspace_use_case: 'conversation',
            workspace_type: 'general',
            collaboration_mode: 'multi_agent_shared',
            agent_conversation_mode: 'multi_agent_shared',
            autonomy_profile: { workspace_type: 'general' },
          },
        },
      });
      return requireWorkspace(payload, currentScope);
    },
    async update(scope, workspaceId, input, options) {
      const currentScope = requireCloudAction(runtimeConfig, scope, 'update');
      const payload = await requestJson(
        runtimeConfig,
        workspacePath(currentScope, workspaceId),
        {
          ...options,
          method: 'PATCH',
          body: {
            name: requireInputText(input.name, 'project_workspace_name_required'),
            description: input.description.trim(),
            is_archived: input.archived,
          },
        },
      );
      return requireWorkspace(payload, currentScope);
    },
    async listMembers(scope, workspaceId, options) {
      const currentScope = requireCloudAction(runtimeConfig, scope, 'list_members');
      const payload = await requestJson(
        runtimeConfig,
        `${workspacePath(currentScope, workspaceId)}/members?limit=500&offset=0`,
        options,
      );
      return Object.freeze(
        requireCollection(payload, ['items', 'members']).map((item) =>
          requireMember(item, requireId(workspaceId, 'project_workspace_id_required')),
        ),
      );
    },
    async addMember(scope, workspaceId, input, options) {
      const currentScope = requireCloudAction(runtimeConfig, scope, 'add_member');
      const expectedWorkspaceId = requireId(workspaceId, 'project_workspace_id_required');
      const payload = await requestJson(
        runtimeConfig,
        `${workspacePath(currentScope, expectedWorkspaceId)}/members`,
        {
          ...options,
          method: 'POST',
          body: {
            user_id: requireId(input.userId, 'project_workspace_user_id_required'),
            role: requireRole(input.role),
          },
        },
      );
      return requireMember(payload, expectedWorkspaceId);
    },
    async updateMemberRole(scope, workspaceId, userId, role, options) {
      const currentScope = requireCloudAction(runtimeConfig, scope, 'update_member_role');
      const expectedWorkspaceId = requireId(workspaceId, 'project_workspace_id_required');
      const payload = await requestJson(
        runtimeConfig,
        `${workspacePath(currentScope, expectedWorkspaceId)}/members/${encodeURIComponent(
          requireId(userId, 'project_workspace_user_id_required'),
        )}`,
        { ...options, method: 'PATCH', body: { role: requireRole(role) } },
      );
      return requireMember(payload, expectedWorkspaceId);
    },
    async removeMember(scope, workspaceId, userId, options) {
      const currentScope = requireCloudAction(runtimeConfig, scope, 'remove_member');
      await requestJson(
        runtimeConfig,
        `${workspacePath(currentScope, workspaceId)}/members/${encodeURIComponent(
          requireId(userId, 'project_workspace_user_id_required'),
        )}`,
        { ...options, method: 'DELETE' },
      );
    },
    async listAgents(scope, workspaceId, options) {
      const currentScope = requireCloudAction(runtimeConfig, scope, 'list_agents');
      const expectedWorkspaceId = requireId(workspaceId, 'project_workspace_id_required');
      const payload = await requestJson(
        runtimeConfig,
        `${workspacePath(currentScope, expectedWorkspaceId)}/agents?active_only=false&limit=500&offset=0`,
        options,
      );
      return Object.freeze(
        requireCollection(payload, ['items', 'agents']).map((item) =>
          requireAgentBinding(item, expectedWorkspaceId),
        ),
      );
    },
    async bindAgent(scope, workspaceId, input, options) {
      const currentScope = requireCloudAction(runtimeConfig, scope, 'bind_agent');
      const expectedWorkspaceId = requireId(workspaceId, 'project_workspace_id_required');
      const payload = await requestJson(
        runtimeConfig,
        `${workspacePath(currentScope, expectedWorkspaceId)}/agents`,
        {
          ...options,
          method: 'POST',
          body: {
            agent_id: requireId(input.agentId, 'project_workspace_agent_id_required'),
            ...(input.displayName === undefined
              ? {}
              : { display_name: input.displayName.trim() || null }),
            ...(input.description === undefined
              ? {}
              : { description: input.description.trim() || null }),
          },
        },
      );
      return requireAgentBinding(payload, expectedWorkspaceId);
    },
    async unbindAgent(scope, workspaceId, bindingId, options) {
      const currentScope = requireCloudAction(runtimeConfig, scope, 'unbind_agent');
      await requestJson(
        runtimeConfig,
        `${workspacePath(currentScope, workspaceId)}/agents/${encodeURIComponent(
          requireId(bindingId, 'project_workspace_binding_id_required'),
        )}`,
        { ...options, method: 'DELETE' },
      );
    },
  };
  return Object.freeze(client);
}

function requireCloudAction(
  config: DesktopRuntimeConfig,
  scope: ProjectWorkspacesScope,
  action: string,
): ProjectWorkspacesScope {
  const currentScope = requireScope(config, scope);
  if (currentScope.authority === 'local') {
    throw new DesktopApiError(`local_workspace_${action}_unavailable`, 501, {
      reason_code: `local_workspace_${action}_unavailable`,
      availability: 'unavailable',
      authority: 'sidecar',
    });
  }
  return currentScope;
}

function requireRuntimeCredentials(config: DesktopRuntimeConfig): void {
  if (!desktopApiAuthenticationAvailable(config)) {
    throw contractError('project_workspaces_trusted_session_required');
  }
  if (config.mode === 'local' && !desktopLaunchCapability(config)) {
    throw contractError('project_workspaces_launch_capability_required');
  }
}

function requireScope(
  config: DesktopRuntimeConfig,
  scope: ProjectWorkspacesScope,
): ProjectWorkspacesScope {
  if (
    scope.authority !== config.mode ||
    !validId(scope.tenantId) ||
    !validId(scope.projectId) ||
    scope.tenantId !== config.tenantId ||
    scope.projectId !== config.projectId
  ) {
    throw contractError('project_workspaces_runtime_scope_mismatch');
  }
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

function workspaceBase(scope: ProjectWorkspacesScope): string {
  return (
    `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/projects/` +
    `${encodeURIComponent(scope.projectId)}/workspaces`
  );
}

function workspacePath(scope: ProjectWorkspacesScope, workspaceId: string): string {
  return `${workspaceBase(scope)}/${encodeURIComponent(
    requireId(workspaceId, 'project_workspace_id_required'),
  )}`;
}

async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  options: RequestOptions = {},
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  headers.set('Authorization', `Bearer ${desktopApiCredential(config)}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  const response = await desktopApiFetch(config, path, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    credentials: 'omit',
    signal: options.signal,
  });
  const declaredLength = Number(response.headers.get('content-length') ?? '0');
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw contractError('project_workspaces_response_too_large');
  }
  if (response.status === 204) return null;
  const text = await response.text().catch(() => '');
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw contractError('project_workspaces_response_too_large');
  }
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  const payload = contentType.includes('application/json') ? parseJson(text) : text;
  if (!response.ok) {
    throw new DesktopApiError(errorMessage(response.status, payload), response.status, payload);
  }
  if (!contentType.includes('application/json')) {
    throw contractError('project_workspaces_response_not_json');
  }
  return payload;
}

function requireWorkspace(
  input: unknown,
  scope: ProjectWorkspacesScope,
): ProjectWorkspaceRecord {
  if (
    !isRecord(input) ||
    input.tenant_id !== scope.tenantId ||
    input.project_id !== scope.projectId ||
    !validId(input.id) ||
    !validId(input.name) ||
    !nullableString(input.description) ||
    !nullableString(input.created_at) ||
    !nullableString(input.updated_at) ||
    (input.is_archived !== undefined && typeof input.is_archived !== 'boolean')
  ) {
    throw contractError(`${scope.authority}_project_workspaces_contract_invalid`);
  }
  return Object.freeze({
    id: input.id,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
    name: input.name,
    description: input.description ?? '',
    archived: input.is_archived === true || input.status === 'archived',
    createdAt: input.created_at ?? null,
    updatedAt: input.updated_at ?? null,
  });
}

function requireMember(input: unknown, workspaceId: string): ProjectWorkspaceMember {
  if (
    !isRecord(input) ||
    input.workspace_id !== workspaceId ||
    !validId(input.id) ||
    !validId(input.user_id) ||
    !nullableString(input.user_email) ||
    !isRole(input.role)
  ) {
    throw contractError('cloud_project_workspace_member_contract_invalid');
  }
  return Object.freeze({
    id: input.id,
    workspaceId,
    userId: input.user_id,
    email: input.user_email ?? null,
    role: input.role,
  });
}

function requireAgentBinding(
  input: unknown,
  workspaceId: string,
): ProjectWorkspaceAgentBinding {
  if (
    !isRecord(input) ||
    input.workspace_id !== workspaceId ||
    !validId(input.id) ||
    !validId(input.agent_id) ||
    !nullableString(input.display_name) ||
    typeof input.is_active !== 'boolean' ||
    !nullableString(input.status)
  ) {
    throw contractError('cloud_project_workspace_agent_contract_invalid');
  }
  return Object.freeze({
    id: input.id,
    workspaceId,
    agentId: input.agent_id,
    displayName: input.display_name ?? null,
    active: input.is_active,
    status: input.status ?? null,
  });
}

function requireCollection(input: unknown, keys: readonly string[]): unknown[] {
  if (Array.isArray(input)) return input;
  if (isRecord(input)) {
    for (const key of keys) {
      if (Array.isArray(input[key])) return input[key];
    }
  }
  throw contractError('project_workspaces_collection_contract_invalid');
}

function requireInputText(value: string, reasonCode: string): string {
  const normalized = value.trim();
  if (!normalized || normalized.length > 255) throw contractError(reasonCode);
  return normalized;
}

function requireId(value: string, reasonCode: string): string {
  if (!validId(value)) throw contractError(reasonCode);
  return value;
}

function requireRole(value: string): ProjectWorkspaceMember['role'] {
  if (!isRole(value)) throw contractError('project_workspace_member_role_invalid');
  return value;
}

function isRole(value: unknown): value is ProjectWorkspaceMember['role'] {
  return value === 'owner' || value === 'editor' || value === 'viewer';
}

function validId(value: unknown): value is string {
  return typeof value === 'string' && value.trim() === value && value.length > 0;
}

function nullableString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === 'string';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function parseJson(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    throw contractError('project_workspaces_response_invalid_json');
  }
}

function errorMessage(status: number, payload: unknown): string {
  if (isRecord(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  return `HTTP ${status}`;
}

function contractError(reasonCode: string): DesktopApiError {
  return new DesktopApiError(reasonCode, 0, { reason_code: reasonCode });
}
