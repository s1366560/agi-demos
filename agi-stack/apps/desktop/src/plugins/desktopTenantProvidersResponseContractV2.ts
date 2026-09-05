import { DesktopApiError } from '../api/client';
import type {
  LlmProviderAuthMethod,
  LlmProviderModelCatalog,
  LlmProviderRoutingPolicy,
  LlmProviderTypeDescriptor,
  LlmProviderUsage,
  LlmProviderUsageStatistic,
  LlmProviderValidationOutcome,
  ManagedLlmProvider,
} from '../types';
export function normalizeManagedLlmProviderV2(payload: unknown): ManagedLlmProvider {
  if (!isRecord(payload)) {
    throw new DesktopApiError('Invalid provider response', 502, null);
  }
  const id = readCompatString(payload, 'id');
  const name = readCompatString(payload, 'name');
  const providerType = readCompatString(payload, 'provider_type', 'providerType');
  if (!id || !name || !providerType) {
    throw new DesktopApiError('Invalid provider response', 502, null);
  }

  const authMethod = readProviderAuthMethod(
    readCompatString(payload, 'auth_method', 'authMethod').toLowerCase(),
  );
  const maskedCredential = readCompatString(payload, 'api_key_masked', 'apiKeyMasked');
  const credentialConfigured = readCompatBoolean(
    payload,
    'credential_configured',
    'credentialConfigured',
  );
  const revision = readCompatInteger(payload, 'revision', 'version') ?? 0;

  return {
    id,
    tenant_id: readCompatString(payload, 'tenant_id', 'tenantId') || undefined,
    name,
    provider_type: providerType,
    operation_type: readCompatString(payload, 'operation_type', 'operationType') || undefined,
    auth_method: authMethod,
    is_active: readCompatBoolean(payload, 'is_active', 'isActive'),
    is_enabled: readCompatBoolean(payload, 'is_enabled', 'isEnabled'),
    base_url: readCompatNullableString(payload, 'base_url', 'baseUrl'),
    llm_model: readCompatNullableString(payload, 'llm_model', 'llmModel'),
    llm_small_model: readCompatNullableString(payload, 'llm_small_model', 'llmSmallModel'),
    embedding_model: readCompatNullableString(payload, 'embedding_model', 'embeddingModel'),
    reranker_model: readCompatNullableString(payload, 'reranker_model', 'rerankerModel'),
    allowed_models: readCompatStringArray(payload, 'allowed_models', 'allowedModels'),
    secondary_models: readCompatStringArray(payload, 'secondary_models', 'secondaryModels'),
    health_status: readCompatNullableString(payload, 'health_status', 'healthStatus'),
    credential_source:
      readCompatString(payload, 'credential_source', 'credentialSource') || undefined,
    credential_configured: credentialConfigured,
    environment_variable:
      authMethod === 'environment'
        ? readCompatString(payload, 'environment_variable', 'environmentVariable') || null
        : null,
    api_key_masked: credentialConfigured && maskedCredential ? '••••••••••••' : null,
    health_last_check: readCompatNullableString(payload, 'health_last_check', 'healthLastCheck'),
    response_time_ms: readCompatNullableNumber(payload, 'response_time_ms', 'responseTimeMs'),
    error_message: readCompatNullableString(payload, 'error_message', 'errorMessage'),
    revision,
    updated_at: readCompatNullableString(payload, 'updated_at', 'updatedAt'),
  };
}

export function normalizeLlmProviderRoutingPolicyV2(payload: unknown): LlmProviderRoutingPolicy {
  if (!isRecord(payload) || !isRecord(payload.roles) || !Array.isArray(payload.fallbacks)) {
    throw new DesktopApiError('Invalid provider routing policy response', 502, null);
  }
  const tenantId = readCompatString(payload, 'tenant_id', 'tenantId');
  const projectId = readCompatString(payload, 'project_id', 'projectId');
  const workspaceId = readCompatString(payload, 'workspace_id', 'workspaceId');
  const revision = readCompatInteger(payload, 'revision');
  const updatedAt = readCompatString(payload, 'updated_at', 'updatedAt');
  if (!tenantId || !projectId || !workspaceId || revision == null || revision < 0 || !updatedAt) {
    throw new DesktopApiError('Invalid provider routing policy response', 502, null);
  }
  return {
    tenant_id: tenantId,
    project_id: projectId,
    workspace_id: workspaceId,
    revision,
    roles: {
      default: normalizeLlmRouteTarget(payload.roles.default, payload),
      fast: normalizeLlmRouteTarget(payload.roles.fast, payload),
      coding: normalizeLlmRouteTarget(payload.roles.coding, payload),
      vision: normalizeLlmRouteTarget(payload.roles.vision, payload),
    },
    fallbacks: payload.fallbacks.map((target) => {
      const normalized = normalizeLlmRouteTarget(target, payload);
      if (!normalized) {
        throw new DesktopApiError('Invalid provider routing policy response', 502, null);
      }
      return normalized;
    }),
    updated_at: updatedAt,
  };
}

function normalizeLlmRouteTarget(
  value: unknown,
  payload: unknown,
): LlmProviderRoutingPolicy['roles']['default'] {
  if (value === null) return null;
  if (!isRecord(value)) {
    throw new DesktopApiError('Invalid provider routing policy response', 502, null);
  }
  const providerId = readCompatString(value, 'provider_id', 'providerId');
  const modelId = readCompatString(value, 'model_id', 'modelId');
  if (!providerId || !modelId) {
    throw new DesktopApiError('Invalid provider routing policy response', 502, null);
  }
  return { provider_id: providerId, model_id: modelId };
}

export function normalizeProviderValidationOutcomeV2(
  payload: unknown,
  fallbackProviderType = '',
): LlmProviderValidationOutcome {
  if (!isRecord(payload)) {
    throw new DesktopApiError('Invalid provider validation response', 502, null);
  }
  const status = readCompatString(payload, 'status');
  if (!status || typeof payload.probed !== 'boolean') {
    throw new DesktopApiError('Invalid provider validation response', 502, null);
  }
  const provider =
    payload.provider == null ? null : normalizeManagedLlmProviderV2(payload.provider);
  const providerType = provider?.provider_type || fallbackProviderType;
  return {
    provider,
    status,
    probed: payload.probed,
    detail: readCompatNullableString(payload, 'detail'),
    lastChecked: readCompatNullableString(payload, 'last_check', 'lastChecked'),
    responseTimeMs: readCompatNullableNumber(payload, 'response_time_ms', 'responseTimeMs'),
    errorMessage: readCompatNullableString(payload, 'error_message', 'errorMessage'),
    catalog:
      payload.catalog == null
        ? null
        : normalizeProviderCatalogV2(payload.catalog, providerType, provider?.id ?? ''),
  };
}

function readCompatString(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): string {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  return typeof value === 'string' ? value.trim() : '';
}

function readProviderAuthMethod(value: string): LlmProviderAuthMethod | undefined {
  return value === 'api_key' || value === 'oauth' || value === 'environment' || value === 'none'
    ? value
    : undefined;
}

function readCompatBoolean(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): boolean | undefined {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  return typeof value === 'boolean' ? value : undefined;
}

function readCompatInteger(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): number | undefined {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  return Number.isInteger(value) && typeof value === 'number' ? value : undefined;
}

function readCompatStringArray(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): string[] | null {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  if (!Array.isArray(value)) return null;
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean);
}

function readCompatNullableString(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): string | null {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  return typeof value === 'string' ? value : null;
}

function readCompatNullableNumber(
  record: Record<string, unknown>,
  snakeCaseKey: string,
  camelCaseKey?: string,
): number | null {
  const value = record[snakeCaseKey] ?? (camelCaseKey ? record[camelCaseKey] : undefined);
  return typeof value === 'number' ? value : null;
}

export function normalizeProviderTypeDescriptorsV2(
  payload: unknown,
  source: LlmProviderTypeDescriptor['source'],
): LlmProviderTypeDescriptor[] {
  const descriptors: LlmProviderTypeDescriptor[] = [];
  const seen = new Set<string>();
  for (const value of readArray<unknown>(payload, ['types', 'items', 'data'])) {
    const providerType =
      typeof value === 'string'
        ? value.trim()
        : value && typeof value === 'object' && !Array.isArray(value)
          ? readTrimmedString(value as Record<string, unknown>, 'provider_type')
          : '';
    if (!providerType || seen.has(providerType)) continue;
    const authMethods =
      value && typeof value === 'object' && !Array.isArray(value)
        ? readProviderAuthMethods((value as Record<string, unknown>).auth_methods)
        : [];
    const explicitlyUnavailableAuthMethods =
      value && typeof value === 'object' && !Array.isArray(value)
        ? readProviderAuthMethods((value as Record<string, unknown>).unavailable_auth_methods)
        : [];
    const unavailableAuthMethods = Array.from(
      new Set<LlmProviderAuthMethod>([
        ...explicitlyUnavailableAuthMethods,
        ...authMethods.filter((method) => method === 'oauth'),
      ]),
    );
    const explicitOperationType =
      value && typeof value === 'object' && !Array.isArray(value)
        ? readTrimmedString(value as Record<string, unknown>, 'operation_type')
        : '';
    const operationType = providerOperationType(providerType, explicitOperationType);
    const probeSupported =
      !value ||
      typeof value !== 'object' ||
      Array.isArray(value) ||
      (value as Record<string, unknown>).probe_supported !== false;
    seen.add(providerType);
    descriptors.push({
      providerType,
      authMethods,
      unavailableAuthMethods,
      operationType,
      probeSupported,
      source,
    });
  }
  return descriptors;
}

function providerOperationType(
  providerType: string,
  explicitOperationType: string,
): LlmProviderTypeDescriptor['operationType'] {
  if (explicitOperationType === 'embedding' || explicitOperationType === 'rerank') {
    return explicitOperationType;
  }
  if (providerType.endsWith('_embedding')) return 'embedding';
  if (providerType.endsWith('_reranker') || providerType.endsWith('_rerank')) return 'rerank';
  return 'llm';
}

function readProviderAuthMethods(value: unknown): LlmProviderAuthMethod[] {
  if (!Array.isArray(value)) return [];
  const methods: LlmProviderAuthMethod[] = [];
  for (const candidate of value) {
    const method =
      typeof candidate === 'string'
        ? readProviderAuthMethod(candidate.trim().toLowerCase())
        : undefined;
    if (method && !methods.includes(method)) methods.push(method);
  }
  return methods;
}

function readTrimmedString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === 'string' ? value.trim() : '';
}

function unavailableProviderCatalog(
  providerType: string,
  providerId = '',
  detail: string | null = null,
): LlmProviderModelCatalog {
  return {
    providerType,
    providerId: providerId || null,
    availability: 'unavailable',
    source: null,
    discoveredAt: null,
    detail,
    models: [],
  };
}

export function normalizeProviderCatalogV2(
  payload: unknown,
  fallbackProviderType: string,
  fallbackProviderId = '',
): LlmProviderModelCatalog {
  if (!payload || typeof payload !== 'object') {
    return unavailableProviderCatalog(fallbackProviderType, fallbackProviderId);
  }
  const record = payload as Record<string, unknown>;
  const providerType =
    readCompatString(record, 'provider_type', 'providerType') || fallbackProviderType;
  const providerId =
    readCompatString(record, 'provider_id', 'providerId') || fallbackProviderId || null;
  const detail = readCompatNullableString(record, 'detail');
  const availability = readCompatString(record, 'availability');
  if (!record.models || typeof record.models !== 'object' || Array.isArray(record.models)) {
    return unavailableProviderCatalog(providerType, providerId ?? '', detail);
  }
  const categorized = record.models as Record<string, unknown>;
  const models: LlmProviderModelCatalog['models'] = [];
  for (const capability of ['chat', 'embedding', 'rerank'] as const) {
    const candidates = categorized[capability];
    if (!Array.isArray(candidates)) continue;
    const seen = new Set<string>();
    for (const candidate of candidates) {
      if (typeof candidate !== 'string') continue;
      const id = candidate.trim();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      models.push({ id, capability });
    }
  }
  const source = typeof record.source === 'string' ? record.source.trim() || null : null;
  const discoveredAt = readCompatNullableString(record, 'discovered_at', 'discoveredAt');
  if (availability === 'unavailable') {
    return {
      providerType,
      providerId,
      availability: 'unavailable',
      source,
      discoveredAt,
      detail,
      models,
    };
  }
  if (models.length === 0 && source === null && availability !== 'available') {
    return unavailableProviderCatalog(providerType, providerId ?? '', detail);
  }
  return {
    providerType,
    providerId,
    availability: 'available',
    source,
    discoveredAt,
    detail,
    models,
  };
}

function unavailableProviderUsage(providerId: string): LlmProviderUsage {
  return {
    provider_id: providerId,
    tenant_id: null,
    availability: 'unavailable',
    statistics: [],
  };
}

export function normalizeProviderUsageV2(payload: unknown, providerId: string): LlmProviderUsage {
  if (!payload || typeof payload !== 'object') return unavailableProviderUsage(providerId);
  const record = payload as Record<string, unknown>;
  if (
    typeof record.provider_id !== 'string' ||
    !Array.isArray(record.statistics) ||
    (record.tenant_id !== null && typeof record.tenant_id !== 'string')
  ) {
    return unavailableProviderUsage(providerId);
  }
  if (
    record.availability !== undefined &&
    record.availability !== 'available' &&
    record.availability !== 'unavailable'
  ) {
    return unavailableProviderUsage(providerId);
  }
  if (record.availability === 'unavailable') {
    return {
      provider_id: record.provider_id,
      tenant_id: record.tenant_id,
      availability: 'unavailable',
      statistics: [],
    };
  }
  const statistics = record.statistics.filter(isLlmProviderUsageStatistic);
  if (statistics.length !== record.statistics.length) return unavailableProviderUsage(providerId);
  return {
    provider_id: record.provider_id,
    tenant_id: record.tenant_id,
    availability: 'available',
    statistics,
  };
}

function isLlmProviderUsageStatistic(value: unknown): value is LlmProviderUsageStatistic {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.provider_id === 'string' &&
    (record.tenant_id === null || typeof record.tenant_id === 'string') &&
    (record.operation_type === null || typeof record.operation_type === 'string') &&
    typeof record.total_requests === 'number' &&
    typeof record.total_prompt_tokens === 'number' &&
    typeof record.total_completion_tokens === 'number' &&
    typeof record.total_tokens === 'number' &&
    (record.total_cost_usd === null || typeof record.total_cost_usd === 'number') &&
    (record.avg_response_time_ms === null || typeof record.avg_response_time_ms === 'number') &&
    (record.first_request_at === null || typeof record.first_request_at === 'string') &&
    (record.last_request_at === null || typeof record.last_request_at === 'string')
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function readProviderArrayV2(payload: unknown, keys: string[]): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (isRecord(payload))
    for (const key of keys)
      if (key in payload) {
        if (Array.isArray(payload[key])) return payload[key];
        break;
      }
  throw new DesktopApiError('Invalid provider collection response', 502, null);
}
function readArray<T>(payload: unknown, keys: string[]): T[] {
  return readProviderArrayV2(payload, keys) as T[];
}
