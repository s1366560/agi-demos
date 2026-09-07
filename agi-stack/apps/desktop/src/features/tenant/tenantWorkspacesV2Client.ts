import type {
  DesktopWorkspaceCatalogOperationsV2,
} from '../../plugins/desktopWorkspaceCatalogAuthorityModuleV2';
import type {
  DesktopWorkspaceLifecycleOperationsV2,
} from '../../plugins/desktopWorkspaceLifecycleAuthorityModuleV2';
import type { DesktopRuntimeConfig, WorkspaceSummary } from '../../types';
import type {
  TenantWorkspaceRecord,
  TenantWorkspacesClient,
  TenantWorkspacesScope,
} from './tenantWorkspacesClient';

const ALLOWED_ACTIONS = Object.freeze(['view', 'list', 'create']);

export type TenantWorkspacesV2ClientDependencies = Readonly<{
  catalogOperations: Pick<
    DesktopWorkspaceCatalogOperationsV2,
    'listWorkspacesForProject'
  >;
  lifecycleOperations: Pick<
    DesktopWorkspaceLifecycleOperationsV2,
    'createWorkspace'
  >;
}>;

export function createTenantWorkspacesV2Client(
  config: DesktopRuntimeConfig,
  dependencies: TenantWorkspacesV2ClientDependencies,
): TenantWorkspacesClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async list(scope, options) {
      const operationConfig = operationConfigForScope(runtimeConfig, scope);
      const workspaces = await dependencies.catalogOperations.listWorkspacesForProject({
        config: operationConfig,
        signal: options?.signal,
      });
      const snapshotScope = freezeScope(scope);
      return Object.freeze({
        scope: snapshotScope,
        authority: snapshotScope.authority,
        availability: 'degraded' as const,
        reasonCode: partialReason(snapshotScope.authority),
        serviceVersion: snapshotScope.authority === 'cloud' ? 'cloud' : '0.1.0',
        contractVersion: '3.0.0',
        allowedActions: ALLOWED_ACTIONS,
        authorityRevision: null,
        workspaces: Object.freeze(
          workspaces.map((workspace) => projectWorkspace(workspace, snapshotScope)),
        ),
      });
    },
    async create(scope, input, options) {
      const operationConfig = operationConfigForScope(runtimeConfig, scope);
      const workspace = await dependencies.lifecycleOperations.createWorkspace({
        config: operationConfig,
        input: Object.freeze({
          name: input.name.trim(),
          description: input.description.trim(),
          useCase: 'conversation',
          collaborationMode: 'multi_agent_shared',
          metadata: Object.freeze({
            source: 'desktop',
            workspace_use_case: 'conversation',
            workspace_type: 'general',
            collaboration_mode: 'multi_agent_shared',
            agent_conversation_mode: 'multi_agent_shared',
            autonomy_profile: Object.freeze({ workspace_type: 'general' }),
          }),
        }),
        signal: options?.signal,
      });
      return projectWorkspace(workspace, freezeScope(scope));
    },
  });
}

function operationConfigForScope(
  config: DesktopRuntimeConfig,
  scope: TenantWorkspacesScope,
): DesktopRuntimeConfig {
  requireRuntimeScope(config, scope);
  return Object.freeze({
    ...config,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
    workspaceId: '',
  });
}

function freezeScope(scope: TenantWorkspacesScope): TenantWorkspacesScope {
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

function requireRuntimeScope(
  config: DesktopRuntimeConfig,
  scope: TenantWorkspacesScope,
): void {
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
  if (
    workspace.tenant_id !== scope.tenantId ||
    workspace.project_id !== scope.projectId
  ) {
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
