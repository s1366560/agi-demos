import type {
  LlmProviderMutationInput,
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
