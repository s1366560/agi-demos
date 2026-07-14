import type {
  LlmProviderAuthMethod,
  LlmProviderCatalogModel,
  LlmProviderCreateInput,
  LlmProviderMutationInput,
  LlmProviderTypeDescriptor,
  LlmProviderValidationOutcome,
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

function normalizedModelIds(value: string): string[] {
  const seen = new Set<string>();
  return value
    .split(/[\n,]/)
    .map((model) => model.trim())
    .filter((model) => Boolean(model) && !seen.has(model) && Boolean(seen.add(model)));
}
