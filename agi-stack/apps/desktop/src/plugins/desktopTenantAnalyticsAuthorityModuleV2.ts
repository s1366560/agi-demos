import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import {
  DesktopApiError,
  desktopApiCredential,
  desktopLaunchCapability,
} from '../api/client';
import { desktopApiFetch } from '../api/cloudRequestBroker';
import type {
  TenantAnalyticsPeriod,
  TenantAnalyticsScope,
  TenantAnalyticsSnapshot,
} from '../features/tenant/tenantAnalyticsClient';
import type { DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  projectDesktopTenantAnalyticsResponseV2,
  requireDesktopTenantAnalyticsSnapshotV2,
  tenantAnalyticsContractErrorV2,
} from './desktopTenantAnalyticsContractV2';

export const DESKTOP_TENANT_ANALYTICS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-analytics-authority';
export const DESKTOP_TENANT_ANALYTICS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-analytics-authority';
export const DESKTOP_TENANT_ANALYTICS_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopTenantAnalyticsOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantAnalyticsScope;
  signal?: AbortSignal;
}>;

export interface DesktopTenantAnalyticsAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<TenantAnalyticsSnapshot>;
}

export interface DesktopTenantAnalyticsAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: TenantAnalyticsScope,
  ) => DesktopTenantAnalyticsAuthorityV2;
}

export interface DesktopTenantAnalyticsOperationsV2 {
  readonly loadTenantAnalytics: (
    input: DesktopTenantAnalyticsOperationInputV2,
  ) => Promise<TenantAnalyticsSnapshot>;
}

type PreparedTenantAnalyticsOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantAnalyticsScope;
  signal?: AbortSignal;
}>;

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;

type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;

type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2;

const OPERATION_INPUT_KEYS_V2 = new Set(['config', 'scope', 'signal']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'period']);
const AUTHORITY_KEYS_V2 = new Set(['load']);
const PERIODS_V2 = new Set<TenantAnalyticsPeriod>(['7d', '30d', '90d']);

export class DesktopTenantAnalyticsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantAnalyticsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantAnalyticsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_analytics_authority_config_invalid',
      'desktop tenant analytics authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopTenantAnalyticsAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopTenantAnalyticsAuthorityV2,
  });
  context.provide(DESKTOP_TENANT_ANALYTICS_AUTHORITY_SERVICE_V2, service);
}

export const desktopTenantAnalyticsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_ANALYTICS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopTenantAnalyticsAuthorityV2,
});

export function createDesktopTenantAnalyticsOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantAnalyticsOperationsV2 {
  return Object.freeze({
    loadTenantAnalytics(input: DesktopTenantAnalyticsOperationInputV2) {
      const prepared = prepareTenantAnalyticsOperationV2(input);
      return runDesktopTenantAnalyticsAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal),
      );
    },
  });
}

export function withDesktopTenantAnalyticsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopTenantAnalyticsOperationInputV2,
  operation: (
    authority: DesktopTenantAnalyticsAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopTenantAnalyticsAuthorityOperationV2(
    actions,
    prepareTenantAnalyticsOperationV2(input),
    operation,
  );
}

async function runDesktopTenantAnalyticsAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedTenantAnalyticsOperationV2,
  operation: (
    authority: DesktopTenantAnalyticsAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantAnalyticsAuthorityServiceV2>({
      service: DESKTOP_TENANT_ANALYTICS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_ANALYTICS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'tenant',
        tenant_id: prepared.scope.tenantId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantAnalyticsAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireTenantAnalyticsServiceV2(candidate);
      const authority = requireTenantAnalyticsAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableTenantAnalyticsAuthorityV2(
          authority,
          prepared.scope,
          () => operationActive,
        ),
      );
    });
  } catch (error) {
    operationFailed = true;
    throw error;
  } finally {
    operationActive = false;
    try {
      await admission.release();
    } catch (releaseError) {
      if (!operationFailed) throw releaseError;
    }
  }
}

function createDesktopTenantAnalyticsAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: TenantAnalyticsScope,
): DesktopTenantAnalyticsAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const operationScope = cloneTenantAnalyticsScopeV2(scope, operationConfig);
  return Object.freeze({
    async load(signal?: AbortSignal) {
      const payload = await requestTenantAnalyticsJsonV2(
        operationConfig,
        operationScope,
        signal,
      );
      return projectDesktopTenantAnalyticsResponseV2(payload, operationScope);
    },
  });
}

function createRevocableTenantAnalyticsAuthorityV2(
  authority: DesktopTenantAnalyticsAuthorityV2,
  scope: TenantAnalyticsScope,
  isOperationActive: () => boolean,
): DesktopTenantAnalyticsAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      if (!isOperationActive()) throw releasedTenantAnalyticsOperationV2();
      const result = await authority.load(signal);
      if (!isOperationActive()) throw releasedTenantAnalyticsOperationV2();
      return requireDesktopTenantAnalyticsSnapshotV2(result, scope);
    },
  });
}

async function requestTenantAnalyticsJsonV2(
  config: DesktopRuntimeConfig,
  scope: TenantAnalyticsScope,
  signal?: AbortSignal,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  const query = new URLSearchParams({ period: scope.period });
  const response = await desktopApiFetch(
    config,
    `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/analytics?${query}`,
    {
      method: 'GET',
      headers,
      signal,
    },
  );
  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.toLowerCase().includes('application/json');
  const payload = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    throw new DesktopApiError(errorMessageV2(response.status, payload), response.status, payload);
  }
  if (!isJson || payload === null) {
    throw tenantAnalyticsContractErrorV2(`${config.mode}_tenant_analytics_contract_invalid`);
  }
  return payload;
}

function prepareTenantAnalyticsOperationV2(
  input: DesktopTenantAnalyticsOperationInputV2,
): PreparedTenantAnalyticsOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasExactOptionalKeysV2(input, OPERATION_INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidTenantAnalyticsInputV2();
  }
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const scope = cloneTenantAnalyticsScopeV2(input.scope, config);
  return Object.freeze({
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidTenantAnalyticsInputV2();
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !isCanonicalStringV2(copy.tenantId)
  ) {
    throw invalidTenantAnalyticsInputV2();
  }
  return Object.freeze(copy);
}

function cloneTenantAnalyticsScopeV2(
  scope: TenantAnalyticsScope,
  config: DesktopRuntimeConfig,
): TenantAnalyticsScope {
  if (
    !isPlainRecordV2(scope) ||
    !hasExactOptionalKeysV2(scope, SCOPE_KEYS_V2) ||
    Object.keys(scope).length !== SCOPE_KEYS_V2.size ||
    scope.authority !== config.mode ||
    !isCanonicalStringV2(scope.tenantId) ||
    scope.tenantId !== config.tenantId ||
    !PERIODS_V2.has(scope.period)
  ) {
    throw invalidTenantAnalyticsInputV2();
  }
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    period: scope.period,
  });
}

function requireTenantAnalyticsServiceV2(
  value: unknown,
): DesktopTenantAnalyticsAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidTenantAnalyticsServiceV2();
  }
  return value as unknown as DesktopTenantAnalyticsAuthorityServiceV2;
}

function requireTenantAnalyticsAuthorityV2(
  value: unknown,
): DesktopTenantAnalyticsAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== AUTHORITY_KEYS_V2.size ||
    !Object.keys(value).every((key) => AUTHORITY_KEYS_V2.has(key)) ||
    typeof value.load !== 'function'
  ) {
    throw invalidTenantAnalyticsServiceV2();
  }
  return value as unknown as DesktopTenantAnalyticsAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopTenantAnalyticsAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidTenantAnalyticsInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_analytics_operation_input_invalid',
    'desktop tenant analytics operation input is invalid',
  );
}

function invalidTenantAnalyticsServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_analytics_service_invalid',
    'desktop tenant analytics authority service is invalid',
  );
}

function releasedTenantAnalyticsOperationV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_analytics_operation_released',
    'desktop tenant analytics operation has been released',
  );
}

function errorMessageV2(status: number, payload: unknown): string {
  if (isPlainRecordV2(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  return `Tenant analytics request failed (${status})`;
}

function hasExactOptionalKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_TENANT_ANALYTICS_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_tenant_analytics_authority_catalog_missing',
      'desktop tenant analytics authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
