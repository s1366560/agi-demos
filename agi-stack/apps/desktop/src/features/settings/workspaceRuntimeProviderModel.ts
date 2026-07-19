import type {
  DesktopRuntimeConfig,
  LlmProviderRoutingPolicy,
  ManagedLlmProvider,
  WorkspaceRuntimeProvider,
} from '../../types';

export function workspaceRuntimeProviderFromAuthority(
  config: DesktopRuntimeConfig,
  policy: LlmProviderRoutingPolicy,
  providers: readonly ManagedLlmProvider[],
): WorkspaceRuntimeProvider | null {
  const tenantId = config.tenantId.trim();
  const projectId = config.projectId.trim();
  const workspaceId = config.workspaceId.trim();
  if (
    !tenantId ||
    !projectId ||
    !workspaceId ||
    policy.tenant_id !== tenantId ||
    policy.project_id !== projectId ||
    policy.workspace_id !== workspaceId
  ) {
    return null;
  }

  const target = policy.roles.default;
  if (!target) return null;
  const provider = providers.find(
    (item) =>
      item.id === target.provider_id &&
      (!item.operation_type || item.operation_type.trim().toLowerCase() === 'llm'),
  );
  if (!provider) return null;

  return {
    tenant_id: tenantId,
    project_id: projectId,
    workspace_id: workspaceId,
    provider_id: provider.id,
    provider_type: provider.provider_type,
    model: target.model_id,
    credential_configured:
      provider.auth_method === 'none' || provider.credential_configured === true,
  };
}
