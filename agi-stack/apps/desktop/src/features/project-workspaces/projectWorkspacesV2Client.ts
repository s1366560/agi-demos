import type {
  DesktopWorkspaceCatalogOperationsV2,
} from '../../plugins/desktopWorkspaceCatalogAuthorityModuleV2';
import type {
  DesktopWorkspaceLifecycleOperationsV2,
} from '../../plugins/desktopWorkspaceLifecycleAuthorityModuleV2';
import type { DesktopRuntimeConfig, WorkspaceSummary } from '../../types';
import type {
  ProjectWorkspaceRecord,
  ProjectWorkspacesClient,
  ProjectWorkspacesScope,
} from './projectWorkspacesClient';

const ALLOWED_ACTIONS = Object.freeze(['view', 'list', 'create', 'open-blackboard']);

export type ProjectWorkspacesV2ClientDependencies = Readonly<{
  catalogOperations: Pick<
    DesktopWorkspaceCatalogOperationsV2,
    'listWorkspacesForProject'
  >;
  lifecycleOperations: Pick<
    DesktopWorkspaceLifecycleOperationsV2,
    'createWorkspace'
  >;
}>;

export function createProjectWorkspacesV2Client(
  config: DesktopRuntimeConfig,
  dependencies: ProjectWorkspacesV2ClientDependencies,
): Pick<ProjectWorkspacesClient, 'list' | 'create'> {
  const catalogOperations = dependencies?.catalogOperations;
  if (typeof catalogOperations?.listWorkspacesForProject !== 'function') {
    throw new Error('desktop_workspace_catalog_authority_required');
  }
  const lifecycleOperations = dependencies?.lifecycleOperations;
  if (typeof lifecycleOperations?.createWorkspace !== 'function') {
    throw new Error('desktop_workspace_lifecycle_authority_required');
  }
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async list(scope, options) {
      const operationConfig = operationConfigForScope(runtimeConfig, scope);
      const workspaces = await catalogOperations.listWorkspacesForProject({
        config: operationConfig,
        signal: options?.signal,
      });
      const snapshotScope = freezeScope(scope);
      if (!Array.isArray(workspaces)) {
        throw new Error(`${snapshotScope.authority}_project_workspaces_contract_invalid`);
      }
      // Availability mirrors the authority's actual lifecycle coverage: the
      // cloud backend serves the full workspace lifecycle (list/create/
      // update/delete), while the local runtime serves list/create only, so
      // local stays honestly degraded.
      const lifecycleComplete = snapshotScope.authority === 'cloud';
      return Object.freeze({
        scope: snapshotScope,
        authority: snapshotScope.authority,
        availability: lifecycleComplete ? ('available' as const) : ('degraded' as const),
        reasonCode: lifecycleComplete ? null : 'local_workspace_lifecycle_partial',
        serviceVersion: '1.0.0',
        contractVersion: '1.0.0' as const,
        authorityRevision: null,
        allowedActions: ALLOWED_ACTIONS,
        workspaces: Object.freeze(
          workspaces.map((workspace) => projectWorkspace(workspace, snapshotScope)),
        ),
      });
    },
    async create(scope, input, options) {
      const operationConfig = operationConfigForScope(runtimeConfig, scope);
      const workspace = await lifecycleOperations.createWorkspace({
        config: operationConfig,
        input: Object.freeze({
          name: requireInputText(input.name, 'project_workspace_name_required'),
          description: requireDescription(input.description),
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
  scope: ProjectWorkspacesScope,
): DesktopRuntimeConfig {
  requireRuntimeScope(config, scope);
  return Object.freeze({
    ...config,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
    workspaceId: '',
  });
}

function requireRuntimeScope(
  config: DesktopRuntimeConfig,
  scope: ProjectWorkspacesScope,
): void {
  if (
    config.mode !== scope.authority ||
    config.tenantId !== scope.tenantId ||
    config.projectId !== scope.projectId ||
    !isCanonicalIdentifier(scope.tenantId) ||
    !isCanonicalIdentifier(scope.projectId)
  ) {
    throw new Error('project_workspaces_runtime_scope_mismatch');
  }
}

function freezeScope(scope: ProjectWorkspacesScope): ProjectWorkspacesScope {
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

function projectWorkspace(
  workspace: WorkspaceSummary | unknown,
  scope: ProjectWorkspacesScope,
): ProjectWorkspaceRecord {
  if (
    !isRecord(workspace) ||
    workspace.tenant_id !== scope.tenantId ||
    workspace.project_id !== scope.projectId ||
    !isCanonicalIdentifier(workspace.id) ||
    !isCanonicalIdentifier(workspace.name) ||
    !isNullableString(workspace.description) ||
    !isNullableString(workspace.created_at) ||
    !isNullableString(workspace.updated_at) ||
    (workspace.is_archived !== undefined &&
      typeof workspace.is_archived !== 'boolean')
  ) {
    throw new Error(`${scope.authority}_project_workspaces_contract_invalid`);
  }
  return Object.freeze({
    id: workspace.id,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
    name: workspace.name,
    description: workspace.description ?? '',
    archived: workspace.is_archived === true || workspace.status === 'archived',
    createdAt: workspace.created_at ?? null,
    updatedAt: workspace.updated_at ?? null,
  });
}

function requireInputText(value: string, reasonCode: string): string {
  const normalized = typeof value === 'string' ? value.trim() : '';
  if (!normalized || normalized.length > 255) throw new Error(reasonCode);
  return normalized;
}

function requireDescription(value: string): string {
  if (typeof value !== 'string') throw new Error('project_workspace_description_invalid');
  return value.trim();
}

function isCanonicalIdentifier(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isNullableString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === 'string';
}

function isRecord(
  value: unknown,
): value is WorkspaceSummary & Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
