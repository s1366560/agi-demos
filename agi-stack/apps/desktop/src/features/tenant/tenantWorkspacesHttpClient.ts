import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig, WorkspaceSummary } from '../../types';
import type {
  TenantWorkspaceRecord,
  TenantWorkspacesClient,
  TenantWorkspacesScope,
} from './tenantWorkspacesClient';

const ALLOWED_ACTIONS = Object.freeze(['view', 'list', 'create']);

export function createTenantWorkspacesHttpClient(
  config: DesktopRuntimeConfig,
): TenantWorkspacesClient {
  const runtimeConfig = Object.freeze({ ...config });
  const api = new DesktopApiClient(runtimeConfig);
  return Object.freeze({
    async list(scope, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const workspaces = await api.listWorkspacesForProject(
        scope.projectId,
        scope.tenantId,
        options?.signal,
      );
      return Object.freeze({
        scope,
        authority: scope.authority,
        availability: 'degraded' as const,
        reasonCode: partialReason(scope.authority),
        serviceVersion: scope.authority === 'cloud' ? 'cloud' : '0.1.0',
        contractVersion: '3.0.0',
        allowedActions: ALLOWED_ACTIONS,
        authorityRevision: null,
        workspaces: Object.freeze(
          workspaces.map((workspace) => projectWorkspace(workspace, scope)),
        ),
      });
    },
    async create(scope, input, options) {
      requireRuntimeScope(runtimeConfig, scope);
      const workspace = await api.createWorkspaceForProject(
        scope.projectId,
        {
          name: input.name.trim(),
          description: input.description.trim(),
          useCase: 'conversation',
          collaborationMode: 'multi_agent_shared',
          metadata: {
            source: 'desktop',
            workspace_use_case: 'conversation',
            workspace_type: 'general',
            collaboration_mode: 'multi_agent_shared',
            agent_conversation_mode: 'multi_agent_shared',
            autonomy_profile: { workspace_type: 'general' },
          },
        },
        scope.tenantId,
        options?.signal,
      );
      return projectWorkspace(workspace, scope);
    },
  });
}

function requireRuntimeScope(config: DesktopRuntimeConfig, scope: TenantWorkspacesScope): void {
  if (
    config.mode !== scope.authority ||
    config.tenantId !== scope.tenantId ||
    config.projectId !== scope.projectId
  ) {
    throw new Error('tenant_workspaces_runtime_scope_mismatch');
  }
}

function projectWorkspace(
  workspace: WorkspaceSummary,
  scope: TenantWorkspacesScope,
): TenantWorkspaceRecord {
  if (workspace.tenant_id !== scope.tenantId || workspace.project_id !== scope.projectId) {
    throw new Error(`${scope.authority}_tenant_workspaces_contract_invalid`);
  }
  return Object.freeze({
    id: workspace.id,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
    name: workspace.name ?? workspace.title ?? workspace.id,
    description: workspace.description ?? '',
    status: workspace.status ?? (workspace.is_archived ? 'archived' : 'active'),
    archived: workspace.is_archived ?? false,
    createdAt: workspace.created_at ?? null,
    updatedAt: workspace.updated_at ?? null,
  });
}

function partialReason(authority: TenantWorkspacesScope['authority']): string {
  return authority === 'cloud'
    ? 'desktop_tenant_workspaces_advanced_management_partial'
    : 'local_workspace_lifecycle_partial';
}
