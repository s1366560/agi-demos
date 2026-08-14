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
  authMethod: LlmProviderAuthMethod;
  baseUrl: string;
  primaryModel: string;
  allowedModels: string;
  active: boolean;
  apiKey: string;
  environmentVariable: string;
  expectedRevision: number;
};

export type ProviderValidationSignal = {
  kind: 'configuration_only' | 'external_probe';
  status: string;
};

export type ProviderListFilter = 'all' | 'connected' | 'attention';

export type ProviderConnectionStatus = Exclude<ProviderListFilter, 'all'>;

export type ProviderRoutingOverview = Pick<LlmProviderRoutingPolicy, 'roles' | 'fallbacks'>;

export type ProviderSetupOption = Readonly<{
  id: string;
  descriptor: LlmProviderTypeDescriptor;
  name: string;
  authMethod: LlmProviderAuthMethod;
  environmentVariable: string;
  baseUrl: string;
}>;

export type ProviderToggleRequest = Readonly<{
  scopeKey: string;
  providerId: string;
  requestToken: number;
}>;

const LOCAL_RUNTIME_ROUTING_PROVIDER_TYPES = new Set(['anthropic', 'openai', 'openai_compatible']);

const LOCAL_RUNTIME_ROUTABLE_HEALTH_STATUSES = new Set([
  'configuration_valid',
  'healthy',
  'connected',
  'ready',
  'not_checked',
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

const providerDefaultBaseUrls: Readonly<Record<string, string>> = {
  anthropic: 'https://api.anthropic.com',
  azure_openai: '',
  lmstudio: 'http://127.0.0.1:1234/v1',
  ollama: 'http://127.0.0.1:11434',
  openai: 'https://api.openai.com/v1',
  openai_compatible: 'http://127.0.0.1:11434/v1',
};

const KIMI_PROVIDER_PRESET = Object.freeze({
  id: 'preset:kimi',
  name: 'Kimi',
  providerType: 'openai_compatible',
  authMethod: 'environment' as const,
  environmentVariable: 'KIMI_API_KEY',
  baseUrl: 'https://api.kimi.com/coding/v1',
});

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

export function providerSetupOptions(
  descriptors: readonly LlmProviderTypeDescriptor[],
): readonly ProviderSetupOption[] {
  return Object.freeze(
    descriptors.flatMap((descriptor) => {
      const genericOption = providerSetupOption({
        id: `type:${descriptor.providerType}`,
        descriptor,
        name: providerTypeDisplayName(descriptor.providerType),
        authMethod:
          descriptor.authMethods[0] ?? descriptor.unavailableAuthMethods[0] ?? 'api_key',
        environmentVariable: '',
        baseUrl: providerDefaultBaseUrls[descriptor.providerType] ?? '',
      });
      if (!supportsKimiProviderPreset(descriptor)) return [genericOption];
      return [
        providerSetupOption({
          ...KIMI_PROVIDER_PRESET,
          descriptor,
        }),
        genericOption,
      ];
    }),
  );
}

export function providerAuthMethodSupported(
  descriptor: LlmProviderTypeDescriptor,
  method: LlmProviderAuthMethod,
): boolean {
  return (
    descriptor.authMethods.includes(method) && !descriptor.unavailableAuthMethods.includes(method)
  );
}

function supportsKimiProviderPreset(descriptor: LlmProviderTypeDescriptor): boolean {
  return (
    descriptor.source === 'local_runtime' &&
    descriptor.operationType === 'llm' &&
    descriptor.providerType === KIMI_PROVIDER_PRESET.providerType &&
    providerAuthMethodSupported(descriptor, KIMI_PROVIDER_PRESET.authMethod)
  );
}

function providerSetupOption(option: ProviderSetupOption): ProviderSetupOption {
  return Object.freeze(option);
}

export function providerTogglePendingIdForScope(
  pending: ProviderToggleRequest | null,
  scopeKey: string,
): string | null {
  return pending?.scopeKey === scopeKey ? pending.providerId : null;
}

export function providerToggleRequestMatches(
  pending: ProviderToggleRequest | null,
  request: ProviderToggleRequest,
): boolean {
  return (
    pending?.scopeKey === request.scopeKey &&
    pending.providerId === request.providerId &&
    pending.requestToken === request.requestToken
  );
}

export function settleProviderToggleRequest(
  pending: ProviderToggleRequest | null,
  completed: ProviderToggleRequest,
): ProviderToggleRequest | null {
  return providerToggleRequestMatches(pending, completed) ? null : pending;
}

export function providerManagementAllowed(mode: RuntimeMode, roles: readonly string[]): boolean {
  const normalized = new Set(roles.map((role) => role.trim().toLowerCase()));
  return mode === 'local'
    ? normalized.has('owner') || normalized.has('admin')
    : normalized.has('admin');
}

export function providerDraftFromProvider(provider: ManagedLlmProvider): ProviderEditorDraft {
  const authMethod = provider.auth_method ?? 'api_key';
  return {
    id: provider.id,
    name: provider.name || provider.provider_type,
    providerType: provider.provider_type,
    authMethod,
    baseUrl: provider.base_url ?? '',
    primaryModel: provider.llm_model ?? '',
    allowedModels: (provider.allowed_models ?? []).join('\n'),
    active: provider.is_active !== false,
    apiKey: '',
    environmentVariable:
      authMethod === 'environment' ? (provider.environment_variable ?? '').trim() : '',
    expectedRevision: provider.revision ?? 0,
  };
}

export function providerMutationFromDraft(draft: ProviderEditorDraft): LlmProviderMutationInput {
  const apiKey = draft.authMethod === 'api_key' ? draft.apiKey.trim() : '';
  const environmentVariable =
    draft.authMethod === 'environment' ? draft.environmentVariable.trim() : '';
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
    ...(environmentVariable ? { environmentVariable } : {}),
  };
}

export function providerCreateInputFromDraft(draft: ProviderEditorDraft): LlmProviderCreateInput {
  const { expectedRevision: _expectedRevision, ...input } = providerMutationFromDraft(draft);
  return input;
}

export function providerProbeInputFromDraft(draft: ProviderEditorDraft): LlmProviderProbeInput {
  const apiKey = draft.authMethod === 'api_key' ? draft.apiKey.trim() : '';
  const environmentVariable =
    draft.authMethod === 'environment' ? draft.environmentVariable.trim() : '';
  return {
    name: draft.name.trim(),
    providerType: draft.providerType.trim(),
    authMethod: draft.authMethod,
    baseUrl: draft.baseUrl.trim().replace(/\/$/, ''),
    active: draft.active,
    ...(apiKey ? { apiKey } : {}),
    ...(environmentVariable ? { environmentVariable } : {}),
  };
}

export function providerProbeInputIsValid(
  input: LlmProviderProbeInput,
  credentialConfigured = false,
): boolean {
  if (!input.name || !input.providerType || !input.baseUrl) return false;
  if (input.authMethod === 'oauth') return false;
  if (input.authMethod === 'none') return true;
  if (input.authMethod === 'environment') return Boolean(input.environmentVariable?.trim());
  return Boolean(input.apiKey?.trim() || credentialConfigured);
}

export function providerConnectionStatus(
  provider: ManagedLlmProvider,
  probeSupported = true,
): ProviderConnectionStatus {
  if (
    provider.is_active === false ||
    provider.is_enabled === false ||
    (provider.credential_configured === false && provider.auth_method !== 'none')
  ) {
    return 'attention';
  }
  if (providerEnabledModelIds(provider).length === 0) return 'attention';
  const healthStatus = provider.health_status?.trim().toLowerCase();
  if (!healthStatus) return probeSupported ? 'attention' : 'connected';
  if (
    healthStatus !== 'healthy' &&
    healthStatus !== 'connected' &&
    healthStatus !== 'ready' &&
    healthStatus !== 'configuration_valid'
  ) {
    return 'attention';
  }
  return 'connected';
}

export function filterProviders(
  providers: readonly ManagedLlmProvider[],
  query: string,
  filter: ProviderListFilter,
  providerTypes: readonly LlmProviderTypeDescriptor[] = [],
): ManagedLlmProvider[] {
  const needle = query.trim().toLowerCase();
  return providers.filter((provider) => {
    const matchesQuery =
      !needle ||
      provider.name.toLowerCase().includes(needle) ||
      provider.provider_type.toLowerCase().includes(needle);
    const descriptor = providerTypes.find((item) => item.providerType === provider.provider_type);
    const matchesFilter =
      filter === 'all' ||
      providerConnectionStatus(provider, descriptor?.probeSupported !== false) === filter;
    return matchesQuery && matchesFilter;
  });
}

export function providerModelsFromProvider(
  provider: ManagedLlmProvider,
): LlmProviderCatalogModel[] {
  const operationType = provider.operation_type?.trim().toLowerCase();
  const capability =
    operationType === 'embedding' ? 'embedding' : operationType === 'rerank' ? 'rerank' : 'chat';
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

export function routingPolicyReferencesProvider(
  policy: LlmProviderRoutingPolicy,
  providerId: string,
): boolean {
  return (
    Object.values(policy.roles).some((target) => target?.provider_id === providerId) ||
    policy.fallbacks.some((target) => target.provider_id === providerId)
  );
}

export function routingPolicyWithoutProvider(
  policy: LlmProviderRoutingPolicy,
  providerId: string,
): ProviderRoutingOverview {
  return {
    roles: Object.fromEntries(
      Object.entries(policy.roles).map(([role, target]) => [
        role,
        target?.provider_id === providerId ? null : target,
      ]),
    ) as LlmProviderRoutingPolicy['roles'],
    fallbacks: policy.fallbacks.filter((target) => target.provider_id !== providerId),
  };
}

export function providerModelCanBeDisabled(provider: ManagedLlmProvider, modelId: string): boolean {
  const primaryModel = provider.llm_model?.trim();
  return !primaryModel || modelId.trim() !== primaryModel;
}

export function providerMutationForActiveState(
  provider: ManagedLlmProvider,
  active: boolean,
): LlmProviderMutationInput {
  const draft = providerDraftFromProvider(provider);
  draft.active = active;
  return providerMutationFromDraft(draft);
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

export function providerValidationSucceeded(outcome: LlmProviderValidationOutcome | null): boolean {
  return outcome?.probed === true && outcome.status === 'healthy';
}

export function providerValidationAccepted(
  outcome: LlmProviderValidationOutcome | null,
  probeSupported: boolean,
): boolean {
  if (probeSupported) return providerValidationSucceeded(outcome);
  return outcome?.probed === false && outcome.status === 'configuration_valid';
}

export function providerConfigurationValidationOutcome(
  _provider: ManagedLlmProvider,
): LlmProviderValidationOutcome {
  return {
    provider: null,
    status: 'configuration_valid',
    probed: false,
    detail: null,
    catalog: null,
  };
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
