import type {
  DesktopRuntimeConfig,
  LlmProviderRoutingPolicy,
  LlmProviderRoutingPolicyMutationInput,
  LlmRoutingRole,
  ManagedLlmProvider,
  RuntimeMode,
  WorkspaceRuntimeProvider,
} from '../../types';
import {
  localRuntimeRoutingModelIds,
  providerEnabledModelIds,
} from './providerManagementModel';

export type WorkspaceRuntimeModelOption = {
  value: string;
  providerId: string;
  providerLabel: string;
  modelId: string;
  selected: boolean;
  roles: LlmRoutingRole[];
  description: string;
  contextWindow: string | null;
};

export type ConversationRuntimeModelSelection = {
  overrideModel: string | null;
  selectedValue: string | null;
  displayLabel: string;
  canReset: boolean;
};

/**
 * Overlay a persisted conversation model override on the workspace routing
 * catalog. Duplicate model ids intentionally remain unselected because the
 * conversation contract does not carry a provider id.
 */
export function conversationRuntimeModelSelection(
  agentConfig: Record<string, unknown> | null | undefined,
  options: readonly WorkspaceRuntimeModelOption[],
  workspaceSelectedValue: string | null,
  workspaceDisplayLabel: string,
  eventOverride: string | null | undefined = undefined,
): ConversationRuntimeModelSelection {
  const rawOverride = agentConfig?.llm_model_override;
  const persistedOverride =
    typeof rawOverride === 'string' && rawOverride.trim() ? rawOverride.trim() : null;
  const overrideModel =
    eventOverride === undefined
      ? persistedOverride
      : typeof eventOverride === 'string' && eventOverride.trim()
        ? eventOverride.trim()
        : null;
  if (!overrideModel) {
    return {
      overrideModel: null,
      selectedValue: workspaceSelectedValue,
      displayLabel: workspaceDisplayLabel,
      canReset: false,
    };
  }

  const matches = options.filter((option) => option.modelId === overrideModel);
  return {
    overrideModel,
    selectedValue: matches.length === 1 ? matches[0]?.value ?? null : null,
    displayLabel: overrideModel,
    canReset: true,
  };
}

export function latestConversationRuntimeModelEvent(
  items: readonly unknown[],
): { overrideModel: string | null; revision: string } | null {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = recordValue(items[index]);
    if (!item) continue;
    const payload = recordValue(item.payload) ?? recordValue(item.data) ?? item;
    const type = stringValue(item.type) ?? stringValue(item.event_type);
    const revision = modelEventRevision(item, type);
    if (type === 'model_override_rejected') return { overrideModel: null, revision };
    if (type !== 'model_switch_requested') continue;
    const model = stringValue(payload.model);
    if (model) return { overrideModel: model, revision };
  }
  return null;
}

function modelEventRevision(item: Record<string, unknown>, type: string | null): string {
  return [
    type ?? '',
    stringValue(item.id) ?? '',
    numberValue(item.eventTimeUs ?? item.event_time_us ?? item.time_us),
    numberValue(item.eventCounter ?? item.event_counter ?? item.counter),
  ].join(':');
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function numberValue(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
}

export function workspaceRuntimeModelSelectionValue(providerId: string, modelId: string): string {
  return JSON.stringify([providerId, modelId]);
}

export function workspaceRuntimeModelOptions(
  policy: LlmProviderRoutingPolicy,
  providers: readonly ManagedLlmProvider[],
  role: LlmRoutingRole = 'default',
  mode: RuntimeMode = 'local',
): WorkspaceRuntimeModelOption[] {
  const selected = policy.roles[role] ?? policy.roles.default;
  return providers.flatMap((provider) =>
    workspaceRoutingModelIds(provider, mode).map((modelId) => {
      const roles = (Object.entries(policy.roles) as Array<
        [LlmRoutingRole, typeof selected]
      >)
        .filter(
          ([, target]) =>
            target?.provider_id === provider.id && target.model_id === modelId,
        )
        .map(([routingRole]) => routingRole);
      const providerLabel = provider.name.trim() || provider.provider_type;
      return {
        value: workspaceRuntimeModelSelectionValue(provider.id, modelId),
        providerId: provider.id,
        providerLabel,
        modelId,
        selected:
          selected?.provider_id === provider.id && selected.model_id === modelId,
        roles,
        description: `${providerLabel} · ${provider.provider_type}`,
        contextWindow: null,
      };
    }),
  );
}

function workspaceRoutingModelIds(
  provider: ManagedLlmProvider,
  mode: RuntimeMode,
): string[] {
  if (mode === 'local') return localRuntimeRoutingModelIds(provider);
  const operationType = provider.operation_type?.trim().toLowerCase();
  if (
    (operationType && operationType !== 'llm') ||
    provider.is_active === false ||
    provider.is_enabled === false
  ) {
    return [];
  }
  return providerEnabledModelIds(provider);
}

export function workspaceRuntimeRoutingMutation(
  config: DesktopRuntimeConfig,
  policy: LlmProviderRoutingPolicy,
  option: WorkspaceRuntimeModelOption,
  role: LlmRoutingRole = 'default',
): LlmProviderRoutingPolicyMutationInput | null {
  if (
    policy.tenant_id !== config.tenantId.trim() ||
    policy.project_id !== config.projectId.trim() ||
    policy.workspace_id !== config.workspaceId.trim()
  ) {
    return null;
  }
  const target = { provider_id: option.providerId, model_id: option.modelId };
  return {
    projectId: policy.project_id,
    workspaceId: policy.workspace_id,
    expectedRevision: policy.revision,
    roles: {
      ...policy.roles,
      default: policy.roles.default ?? target,
      [role]: target,
    },
    fallbacks: [...policy.fallbacks],
  };
}

export function workspaceRuntimeProviderFromAuthority(
  config: DesktopRuntimeConfig,
  policy: LlmProviderRoutingPolicy,
  providers: readonly ManagedLlmProvider[],
  role: LlmRoutingRole = 'default',
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

  const target = policy.roles[role] ?? policy.roles.default;
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
