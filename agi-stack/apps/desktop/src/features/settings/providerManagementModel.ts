import type {
  LlmProviderAuthMethod,
  LlmProviderCatalogModel,
  LlmProviderCreateInput,
  LlmProviderMutationInput,
  LlmProviderProbeInput,
  LlmProviderRoutingPolicy,
  LlmProviderTypeDescriptor,
  LlmProviderValidationOutcome,
  LlmRouteTarget,
  ManagedLlmProvider,
  RuntimeMode,
} from '../../types';

export type ProviderEditorDraft = {
  id: string;
  name: string;
  providerType: string;
  authMethod: 'api_key' | 'none';
  baseUrl: string;
  primaryModel: string;
  allowedModels: string;
  active: boolean;
  apiKey: string;
  expectedRevision: number;
};

export type ProviderValidationSignal = {
  kind: 'configuration_only' | 'external_probe';
  status: string;
};

export type ProviderListFilter = 'all' | 'connected' | 'attention';

export type ProviderConnectionStatus = Exclude<ProviderListFilter, 'all'>;

export type ProviderRoutingOverview = Pick<LlmProviderRoutingPolicy, 'roles' | 'fallbacks'>;

const LOCAL_RUNTIME_ROUTING_PROVIDER_TYPES = new Set([
  'anthropic',
  'openai',
  'openai_compatible',
]);

const LOCAL_RUNTIME_ROUTABLE_HEALTH_STATUSES = new Set([
  'configuration_valid',
  'healthy',
  'connected',
  'ready',
]);

const providerTypeLabels: Readonly<Record<string, string>> = {
  anthropic: 'Anthropic',
  azure_openai: 'Azure OpenAI',
  bedrock: 'AWS Bedrock',
  gemini: 'Google AI',
  lmstudio: 'LM Studio',
  ollama: 'Ollama',
  openai: 'OpenAI',
  openai_compatible: 'OpenAI-compatible',
  openrouter: 'OpenRouter',
  xai: 'xAI',
};

export function providerTypeDisplayName(providerType: string): string {
  const normalized = providerType.trim().toLowerCase();
  return (
    providerTypeLabels[normalized] ??
    normalized
      .split('_')
      .filter(Boolean)
      .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
      .join(' ')
  );
}

export function providerAuthMethodSupported(
  descriptor: LlmProviderTypeDescriptor,
  method: LlmProviderAuthMethod,
): boolean {
  return descriptor.authMethods.includes(method);
}

export function providerManagementAllowed(mode: RuntimeMode, roles: readonly string[]): boolean {
  const normalized = new Set(roles.map((role) => role.trim().toLowerCase()));
  return mode === 'local' ? normalized.has('owner') || normalized.has('admin') : normalized.has('admin');
}

export function providerDraftFromProvider(provider: ManagedLlmProvider): ProviderEditorDraft {
  return {
    id: provider.id,
    name: provider.name || provider.provider_type,
    providerType: provider.provider_type,
    authMethod: provider.auth_method === 'none' ? 'none' : 'api_key',
    baseUrl: provider.base_url ?? '',
    primaryModel: provider.llm_model ?? '',
    allowedModels: (provider.allowed_models ?? []).join('\n'),
    active: provider.is_active !== false,
    apiKey: '',
    expectedRevision: provider.revision ?? 0,
  };
}

export function providerMutationFromDraft(draft: ProviderEditorDraft): LlmProviderMutationInput {
  const apiKey = draft.apiKey.trim();
  return {
    name: draft.name.trim(),
    providerType: draft.providerType.trim(),
    authMethod: draft.authMethod,
    baseUrl: draft.baseUrl.trim().replace(/\/$/, ''),
    primaryModel: draft.primaryModel.trim(),
    allowedModels: normalizedModelIds(draft.allowedModels),
    active: draft.active,
    expectedRevision: draft.expectedRevision,
    ...(apiKey ? { apiKey } : {}),
  };
}

export function providerCreateInputFromDraft(draft: ProviderEditorDraft): LlmProviderCreateInput {
  const { expectedRevision: _expectedRevision, ...input } = providerMutationFromDraft(draft);
  return input;
}

export function providerProbeInputFromDraft(draft: ProviderEditorDraft): LlmProviderProbeInput {
  const apiKey = draft.apiKey.trim();
  return {
    name: draft.name.trim(),
    providerType: draft.providerType.trim(),
    authMethod: draft.authMethod,
    baseUrl: draft.baseUrl.trim().replace(/\/$/, ''),
    active: draft.active,
    ...(apiKey ? { apiKey } : {}),
  };
}

export function providerProbeInputIsValid(
  input: LlmProviderProbeInput,
  credentialConfigured = false,
): boolean {
  return Boolean(
    input.name &&
      input.providerType &&
      input.baseUrl &&
      (input.authMethod === 'none' || input.apiKey || credentialConfigured),
  );
}

export function providerConnectionStatus(
  provider: ManagedLlmProvider,
): ProviderConnectionStatus {
  if (
    provider.is_active === false ||
    provider.is_enabled === false ||
    (provider.credential_configured === false && provider.auth_method !== 'none')
  ) {
    return 'attention';
  }
  const healthStatus = provider.health_status?.trim().toLowerCase();
  if (!healthStatus) return 'attention';
  if (
    healthStatus !== 'healthy' &&
    healthStatus !== 'connected' &&
    healthStatus !== 'ready'
  ) {
    return 'attention';
  }
  if (providerEnabledModelIds(provider).length === 0) return 'attention';
  return 'connected';
}

export function filterProviders(
  providers: readonly ManagedLlmProvider[],
  query: string,
  filter: ProviderListFilter,
): ManagedLlmProvider[] {
  const needle = query.trim().toLowerCase();
  return providers.filter((provider) => {
    const matchesQuery =
      !needle ||
      provider.name.toLowerCase().includes(needle) ||
      provider.provider_type.toLowerCase().includes(needle);
    const matchesFilter = filter === 'all' || providerConnectionStatus(provider) === filter;
    return matchesQuery && matchesFilter;
  });
}

export function providerModelsFromProvider(
  provider: ManagedLlmProvider,
): LlmProviderCatalogModel[] {
  const operationType = provider.operation_type?.trim().toLowerCase();
  const capability =
    operationType === 'embedding'
      ? 'embedding'
      : operationType === 'rerank'
        ? 'rerank'
        : 'chat';
  const seen = new Set<string>();
  return (provider.allowed_models ?? [])
    .map((model) => model.trim())
    .filter((model) => Boolean(model) && !seen.has(model) && Boolean(seen.add(model)))
    .map((id) => ({ id, capability }));
}

export function providerEnabledModelIds(provider: ManagedLlmProvider): string[] {
  return normalizedModelSequence([...(provider.allowed_models ?? []), provider.llm_model ?? '']);
}

export function localRuntimeRoutingModelIds(provider: ManagedLlmProvider): string[] {
  const providerType = provider.provider_type.trim().toLowerCase();
  const operationType = provider.operation_type?.trim().toLowerCase();
  const endpointConfigured = Boolean(provider.base_url?.trim());
  const primaryModelConfigured = Boolean(provider.llm_model?.trim());
  const credentialConfigured =
    provider.auth_method === 'none' || provider.credential_configured === true;
  const healthStatus = provider.health_status?.trim().toLowerCase() ?? '';
  if (
    !LOCAL_RUNTIME_ROUTING_PROVIDER_TYPES.has(providerType) ||
    (operationType && operationType !== 'llm') ||
    !LOCAL_RUNTIME_ROUTABLE_HEALTH_STATUSES.has(healthStatus) ||
    provider.is_active !== true ||
    provider.is_enabled === false ||
    !endpointConfigured ||
    !primaryModelConfigured ||
    !credentialConfigured
  ) {
    return [];
  }
  return providerEnabledModelIds(provider);
}

function routingTargetKey(target: LlmRouteTarget): string {
  return JSON.stringify([target.provider_id, target.model_id]);
}

export function routingFallbackCanAdd(
  fallbacks: readonly LlmRouteTarget[],
  availableTargets: readonly LlmRouteTarget[],
  maxFallbacks: number,
): boolean {
  if (fallbacks.length >= maxFallbacks) return false;
  const used = new Set(fallbacks.map(routingTargetKey));
  return availableTargets.some((target) => !used.has(routingTargetKey(target)));
}

export function providerRoutingOverview(
  provider: ManagedLlmProvider,
  policy: LlmProviderRoutingPolicy | null,
): ProviderRoutingOverview {
  if (policy) {
    return {
      roles: { ...policy.roles },
      fallbacks: [...policy.fallbacks],
    };
  }
  const route = (modelId: string | null | undefined) =>
    modelId ? { provider_id: provider.id, model_id: modelId } : null;
  return {
    roles: {
      default: route(provider.llm_model),
      fast: route(provider.llm_small_model),
      coding: null,
      vision: null,
    },
    fallbacks: (provider.secondary_models ?? []).flatMap((modelId) => {
      const target = route(modelId);
      return target ? [target] : [];
    }),
  };
}

export function providerModelCanBeDisabled(
  provider: ManagedLlmProvider,
  modelId: string,
): boolean {
  const primaryModel = provider.llm_model?.trim();
  return !primaryModel || modelId.trim() !== primaryModel;
}

export function providerMutationForEnabledModels(
  provider: ManagedLlmProvider,
  enabledModelIds: Iterable<string>,
): LlmProviderMutationInput {
  const draft = providerDraftFromProvider(provider);
  const enabled = normalizedModelSequence(enabledModelIds);
  const primaryModel = draft.primaryModel.trim();
  if (primaryModel && !enabled.includes(primaryModel)) enabled.push(primaryModel);
  if (!primaryModel && enabled[0]) draft.primaryModel = enabled[0];
  draft.allowedModels = enabled.join('\n');
  return providerMutationFromDraft(draft);
}

export function providerDraftIsValid(draft: ProviderEditorDraft): boolean {
  return Boolean(
    draft.name.trim() &&
      draft.providerType.trim() &&
      draft.baseUrl.trim() &&
      draft.primaryModel.trim(),
  );
}

export function providerValidationSignal(
  outcome: LlmProviderValidationOutcome,
): ProviderValidationSignal {
  return {
    kind: outcome.probed ? 'external_probe' : 'configuration_only',
    status: outcome.status,
  };
}

export function providerValidationSucceeded(
  outcome: LlmProviderValidationOutcome | null,
): boolean {
  return outcome?.probed === true && outcome.status === 'healthy';
}

export function providerValidationAccepted(
  outcome: LlmProviderValidationOutcome | null,
  probeSupported: boolean,
): boolean {
  if (probeSupported) return providerValidationSucceeded(outcome);
  return outcome?.probed === false && outcome.status === 'configuration_valid';
}

function normalizedModelIds(value: string): string[] {
  return normalizedModelSequence(value.split(/[\n,]/));
}

function normalizedModelSequence(values: Iterable<string>): string[] {
  const seen = new Set<string>();
  return [...values]
    .map((model) => model.trim())
    .filter((model) => Boolean(model) && !seen.has(model) && Boolean(seen.add(model)));
}
