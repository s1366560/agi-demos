import { DesktopApiError } from '../api/client';
import type {
  DesktopRuntimeConfig,
  ManagedLlmProvider,
  LlmProviderCreateInput,
  LlmProviderMutationInput,
  LlmProviderProbeInput,
  LlmProviderModelCatalog,
  LlmProviderRoutingPolicy,
  LlmProviderRoutingPolicyMutationInput,
  LlmProviderTypeDescriptor,
  LlmProviderUsage,
  LlmProviderValidationOutcome,
} from '../types';
import {
  normalizeManagedLlmProviderV2,
  normalizeLlmProviderRoutingPolicyV2,
  normalizeProviderValidationOutcomeV2,
  normalizeProviderTypeDescriptorsV2,
  normalizeProviderCatalogV2,
  normalizeProviderUsageV2,
  readProviderArrayV2,
} from './desktopTenantProvidersResponseContractV2';

export interface ProviderArgumentsV2 {
  listLlmProviders: [];
  getLlmProviderRoutingPolicy: [projectId: string, workspaceId: string];
  updateLlmProviderRoutingPolicy: [input: LlmProviderRoutingPolicyMutationInput];
  createLlmProvider: [input: LlmProviderCreateInput, idempotencyKey: string];
  listLlmProviderTypes: [];
  listLlmProviderModels: [providerType: string];
  discoverLlmProviderModels: [providerId: string, expectedRevision: number];
  getLlmProviderUsage: [providerId: string];
  testLlmProviderDraft: [input: LlmProviderProbeInput];
  updateLlmProvider: [providerId: string, input: LlmProviderMutationInput];
  deleteLlmProvider: [providerId: string, expectedRevision: number, idempotencyKey: string];
  checkLlmProvider: [providerId: string, expectedRevision: number];
}
export interface ProviderResultsV2 {
  listLlmProviders: ManagedLlmProvider[];
  getLlmProviderRoutingPolicy: LlmProviderRoutingPolicy;
  updateLlmProviderRoutingPolicy: LlmProviderRoutingPolicy;
  createLlmProvider: ManagedLlmProvider;
  listLlmProviderTypes: LlmProviderTypeDescriptor[];
  listLlmProviderModels: LlmProviderModelCatalog;
  discoverLlmProviderModels: LlmProviderModelCatalog;
  getLlmProviderUsage: LlmProviderUsage;
  testLlmProviderDraft: LlmProviderValidationOutcome;
  updateLlmProvider: ManagedLlmProvider;
  deleteLlmProvider: void;
  checkLlmProvider: LlmProviderValidationOutcome;
}
export type ProviderMethodV2 = keyof ProviderArgumentsV2;
export const PROVIDER_METHODS_V2: readonly ProviderMethodV2[] = Object.freeze([
  'listLlmProviders',
  'getLlmProviderRoutingPolicy',
  'updateLlmProviderRoutingPolicy',
  'createLlmProvider',
  'listLlmProviderTypes',
  'listLlmProviderModels',
  'discoverLlmProviderModels',
  'getLlmProviderUsage',
  'testLlmProviderDraft',
  'updateLlmProvider',
  'deleteLlmProvider',
  'checkLlmProvider',
]);
export type ProviderScopeV2 = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
  tenantId: string;
}>;
export type ProviderInputV2<K extends ProviderMethodV2 = ProviderMethodV2> = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProviderScopeV2;
  args: ProviderArgumentsV2[K];
  signal?: AbortSignal;
}>;
export interface DesktopTenantProvidersAuthorityV2 {
  execute(method: ProviderMethodV2, input: ProviderInputV2): Promise<unknown>;
}
export function providerErrorV2(code: string, status = 422): DesktopApiError {
  return new DesktopApiError(code, status, Object.freeze({ code, reason_code: code }));
}
export function providerRecordV2(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}
export function providerIdentifierV2(v: unknown): string {
  if (typeof v !== 'string' || !v.trim() || v !== v.trim())
    throw providerErrorV2('tenant_provider_identifier_invalid');
  return v;
}
function revision(v: unknown): void {
  if (!Number.isSafeInteger(v) || Number(v) < 0)
    throw providerErrorV2('tenant_provider_revision_required', 428);
}
export function freezeProviderJsonV2<T>(v: T, depth = 0): T {
  if (depth > 32) throw providerErrorV2('tenant_provider_json_invalid');
  if (
    v === null ||
    typeof v === 'string' ||
    typeof v === 'boolean' ||
    (typeof v === 'number' && Number.isFinite(v))
  )
    return v;
  if (Array.isArray(v)) return Object.freeze(v.map((x) => freezeProviderJsonV2(x, depth + 1))) as T;
  if (!providerRecordV2(v) || ![Object.prototype, null].includes(Object.getPrototypeOf(v)))
    throw providerErrorV2('tenant_provider_json_invalid');
  const r: Record<string, unknown> = {};
  for (const [k, x] of Object.entries(v)) {
    if (['__proto__', 'constructor', 'prototype'].includes(k))
      throw providerErrorV2('tenant_provider_json_invalid');
    if (x !== undefined) r[k] = freezeProviderJsonV2(x, depth + 1);
  }
  return Object.freeze(r) as T;
}
export function freezeProviderConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  const keys = [
    'apiBaseUrl',
    'deviceAuthorizationBaseUrl',
    'apiKey',
    'localApiToken',
    'tenantId',
    'projectId',
    'workspaceId',
    'mode',
    'workspaceRoot',
  ];
  if (
    !providerRecordV2(config) ||
    Object.keys(config).length !== keys.length ||
    keys.some((k) => typeof config[k as keyof DesktopRuntimeConfig] !== 'string') ||
    !['cloud', 'local'].includes(config.mode)
  )
    throw providerErrorV2('tenant_provider_config_invalid');
  return Object.freeze({ ...config });
}
export function prepareProviderInputV2<K extends ProviderMethodV2>(
  method: K,
  input: ProviderInputV2<K>,
): ProviderInputV2<K> {
  if (
    !PROVIDER_METHODS_V2.includes(method) ||
    !providerRecordV2(input) ||
    !providerRecordV2(input.scope) ||
    Object.keys(input.scope).length !== 2
  )
    throw providerErrorV2('tenant_provider_operation_invalid');
  const config = freezeProviderConfigV2(input.config);
  const tenantId = providerIdentifierV2(input.scope.tenantId);
  if (config.tenantId !== tenantId || config.mode !== input.scope.authority)
    throw providerErrorV2('tenant_provider_scope_mismatch', 409);
  if (input.signal !== undefined && !(input.signal instanceof AbortSignal))
    throw providerErrorV2('tenant_provider_signal_invalid');
  if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const args = freezeProviderJsonV2(input.args);
  const lengths: Record<ProviderMethodV2, number> = {
    listLlmProviders: 0,
    getLlmProviderRoutingPolicy: 2,
    updateLlmProviderRoutingPolicy: 1,
    createLlmProvider: 2,
    listLlmProviderTypes: 0,
    listLlmProviderModels: 1,
    discoverLlmProviderModels: 2,
    getLlmProviderUsage: 1,
    testLlmProviderDraft: 1,
    updateLlmProvider: 2,
    deleteLlmProvider: 3,
    checkLlmProvider: 2,
  };
  if (!Array.isArray(args) || args.length !== lengths[method])
    throw providerErrorV2('tenant_provider_arguments_invalid');
  if (
    [
      'listLlmProviderModels',
      'discoverLlmProviderModels',
      'getLlmProviderUsage',
      'updateLlmProvider',
      'deleteLlmProvider',
      'checkLlmProvider',
    ].includes(method)
  )
    providerIdentifierV2(args[0]);
  if (method === 'getLlmProviderRoutingPolicy') {
    providerIdentifierV2(args[0]);
    providerIdentifierV2(args[1]);
  }
  if (method === 'createLlmProvider') providerIdentifierV2(args[1]);
  if (method === 'deleteLlmProvider') providerIdentifierV2(args[2]);
  if (['discoverLlmProviderModels', 'deleteLlmProvider', 'checkLlmProvider'].includes(method))
    revision(args[1]);
  if (method === 'updateLlmProviderRoutingPolicy') validateRouting(args[0]);
  if (['createLlmProvider', 'testLlmProviderDraft', 'updateLlmProvider'].includes(method))
    validateMutation(args[method === 'updateLlmProvider' ? 1 : 0], method);
  return Object.freeze({
    config,
    scope: Object.freeze({ authority: config.mode, tenantId }),
    args,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}
function validateMutation(value: unknown, method: ProviderMethodV2): void {
  if (
    !providerRecordV2(value) ||
    typeof value.name !== 'string' ||
    typeof value.providerType !== 'string' ||
    !value.providerType.trim() ||
    typeof value.baseUrl !== 'string' ||
    typeof value.active !== 'boolean'
  )
    throw providerErrorV2('tenant_provider_mutation_invalid');
  if (!['api_key', 'environment', 'none'].includes(String(value.authMethod)))
    throw providerErrorV2('tenant_provider_auth_method_unavailable');
  for (const key of ['apiKey', 'environmentVariable'])
    if (value[key] !== undefined && typeof value[key] !== 'string')
      throw providerErrorV2('tenant_provider_credential_invalid');
  if (
    method !== 'testLlmProviderDraft' &&
    (typeof value.primaryModel !== 'string' ||
      !Array.isArray(value.allowedModels) ||
      value.allowedModels.some((x) => typeof x !== 'string'))
  )
    throw providerErrorV2('tenant_provider_models_invalid');
  if (value.embeddingModel !== undefined) {
    if (
      method === 'testLlmProviderDraft' ||
      typeof value.embeddingModel !== 'string' ||
      value.embeddingModel !== value.embeddingModel.trim() ||
      value.embeddingModel.length > 256 ||
      (value.embeddingModel !== '' &&
        value.embeddingModel !== value.primaryModel &&
        !(value.allowedModels as string[]).includes(value.embeddingModel))
    )
      throw providerErrorV2('tenant_provider_embedding_model_invalid');
  }
  if (method === 'updateLlmProvider') revision(value.expectedRevision);
}
function validateRouting(value: unknown): void {
  if (!providerRecordV2(value) || !providerRecordV2(value.roles) || !Array.isArray(value.fallbacks))
    throw providerErrorV2('tenant_provider_routing_invalid');
  providerIdentifierV2(value.projectId);
  providerIdentifierV2(value.workspaceId);
  revision(value.expectedRevision);
  for (const role of ['default', 'fast', 'coding', 'vision']) routeTarget(value.roles[role], true);
  for (const target of value.fallbacks) routeTarget(target, false);
}
function routeTarget(value: unknown, nullable: boolean): void {
  if (nullable && value === null) return;
  if (!providerRecordV2(value)) throw providerErrorV2('tenant_provider_routing_invalid');
  providerIdentifierV2(value.provider_id);
  providerIdentifierV2(value.model_id);
}
export function requireProviderResultV2<K extends ProviderMethodV2>(
  method: K,
  raw: unknown,
  input: ProviderInputV2<K>,
): ProviderResultsV2[K] {
  const args = input.args;
  let result: unknown;
  const checkProvider = (value: unknown, expected?: string) => {
    const provider = normalizeManagedLlmProviderV2(value);
    if (
      (expected && provider.id !== expected) ||
      (input.config.mode === 'local' &&
        provider.tenant_id !== undefined &&
        provider.tenant_id !== input.scope.tenantId)
    )
      throw providerErrorV2('tenant_provider_response_scope_invalid', 502);
    if (
      provider.revision !== undefined &&
      (!Number.isSafeInteger(provider.revision) || provider.revision < 0)
    )
      throw providerErrorV2('tenant_provider_response_revision_invalid', 502);
    return provider;
  };
  switch (method) {
    case 'listLlmProviders':
      result = readProviderArrayV2(raw, ['providers', 'items', 'data']).map((v) =>
        checkProvider(v),
      );
      break;
    case 'createLlmProvider':
      result = checkProvider(raw);
      break;
    case 'updateLlmProvider':
      result = checkProvider(raw, args[0] as string);
      break;
    case 'listLlmProviderTypes':
      result = normalizeProviderTypeDescriptorsV2(
        raw,
        input.config.mode === 'local' ? 'local_runtime' : 'cloud_api',
      );
      break;
    case 'getLlmProviderRoutingPolicy':
    case 'updateLlmProviderRoutingPolicy': {
      const r = normalizeLlmProviderRoutingPolicyV2(raw);
      const mutation = args[0] as LlmProviderRoutingPolicyMutationInput;
      if (
        r.tenant_id !== input.scope.tenantId ||
        r.project_id !==
          (method === 'getLlmProviderRoutingPolicy' ? args[0] : mutation.projectId) ||
        r.workspace_id !==
          (method === 'getLlmProviderRoutingPolicy' ? args[1] : mutation.workspaceId) ||
        !Number.isSafeInteger(r.revision)
      )
        throw providerErrorV2('tenant_provider_routing_response_scope_invalid', 502);
      result = r;
      break;
    }
    case 'listLlmProviderModels':
    case 'discoverLlmProviderModels': {
      const catalog = normalizeProviderCatalogV2(
        raw,
        method === 'listLlmProviderModels' ? (args[0] as string) : '',
        method === 'discoverLlmProviderModels' ? (args[0] as string) : '',
      );
      if (
        method === 'discoverLlmProviderModels'
          ? catalog.providerId !== args[0]
          : catalog.providerType !== args[0]
      )
        throw providerErrorV2('tenant_provider_catalog_scope_invalid', 502);
      result = catalog;
      break;
    }
    case 'getLlmProviderUsage': {
      const usage = normalizeProviderUsageV2(raw, args[0] as string);
      if (
        usage.provider_id !== args[0] ||
        usage.statistics.some((s) => s.provider_id !== args[0]) ||
        (input.config.mode === 'local' &&
          usage.tenant_id !== null &&
          usage.tenant_id !== input.scope.tenantId)
      )
        throw providerErrorV2('tenant_provider_usage_scope_invalid', 502);
      result = usage;
      break;
    }
    case 'testLlmProviderDraft':
    case 'checkLlmProvider': {
      const outcome = normalizeProviderValidationOutcomeV2(
        raw,
        method === 'testLlmProviderDraft' ? (args[0] as LlmProviderProbeInput).providerType : '',
      );
      if (outcome.provider)
        checkProvider(
          outcome.provider,
          method === 'checkLlmProvider' ? (args[0] as string) : undefined,
        );
      result = outcome;
      break;
    }
    case 'deleteLlmProvider':
      if (
        input.config.mode === 'cloud'
          ? raw !== null
          : !providerRecordV2(raw) || raw.deleted !== true || raw.id !== args[0]
      )
        throw providerErrorV2('tenant_provider_delete_response_invalid', 502);
      result = undefined;
      break;
  }
  return (result === undefined ? undefined : freezeProviderJsonV2(result)) as ProviderResultsV2[K];
}
