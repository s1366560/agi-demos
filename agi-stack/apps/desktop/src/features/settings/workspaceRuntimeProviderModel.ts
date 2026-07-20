import type {
  DesktopRuntimeConfig,
  LlmProviderRoutingPolicy,
  LlmProviderRoutingPolicyMutationInput,
  ManagedLlmProvider,
  WorkspaceRuntimeProvider,
} from '../../types';
import { localRuntimeRoutingModelIds } from './providerManagementModel';

export type WorkspaceRuntimeModelOption = {
  value: string;
  providerId: string;
  providerLabel: string;
  modelId: string;
  selected: boolean;
};

export function workspaceRuntimeModelSelectionValue(providerId: string, modelId: string): string {
  return JSON.stringify([providerId, modelId]);
}

export function workspaceRuntimeModelOptions(
  policy: LlmProviderRoutingPolicy,
  providers: readonly ManagedLlmProvider[],
): WorkspaceRuntimeModelOption[] {
  const selected = policy.roles.default;
  return providers.flatMap((provider) =>
    localRuntimeRoutingModelIds(provider).map((modelId) => ({
      value: workspaceRuntimeModelSelectionValue(provider.id, modelId),
      providerId: provider.id,
      providerLabel: provider.name.trim() || provider.provider_type,
      modelId,
      selected:
        selected?.provider_id === provider.id && selected.model_id === modelId,
    })),
  );
}

export function workspaceRuntimeRoutingMutation(
  config: DesktopRuntimeConfig,
  policy: LlmProviderRoutingPolicy,
  option: WorkspaceRuntimeModelOption,
): LlmProviderRoutingPolicyMutationInput | null {
  if (
    policy.tenant_id !== config.tenantId.trim() ||
    policy.project_id !== config.projectId.trim() ||
    policy.workspace_id !== config.workspaceId.trim()
  ) {
    return null;
  }
  return {
    projectId: policy.project_id,
    workspaceId: policy.workspace_id,
    expectedRevision: policy.revision,
    roles: {
      ...policy.roles,
      default: { provider_id: option.providerId, model_id: option.modelId },
    },
    fallbacks: [...policy.fallbacks],
  };
}

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
