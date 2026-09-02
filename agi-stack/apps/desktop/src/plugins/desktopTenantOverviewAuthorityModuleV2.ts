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
  TenantOverviewScope,
  TenantOverviewSnapshot,
} from '../features/tenant/tenantOverviewClient';
import type { DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import {
  projectDesktopTenantOverviewResponseV2,
  requireDesktopTenantOverviewSnapshotV2,
  tenantOverviewContractErrorV2,
} from './desktopTenantOverviewContractV2';

export const DESKTOP_TENANT_OVERVIEW_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-overview-authority';
export const DESKTOP_TENANT_OVERVIEW_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-overview-authority';
export const DESKTOP_TENANT_OVERVIEW_AUTHORITY_VERSION_V2 = '1.0.0';

export type DesktopTenantOverviewOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantOverviewScope;
  signal?: AbortSignal;
}>;

export interface DesktopTenantOverviewAuthorityV2 {
  readonly load: (signal?: AbortSignal) => Promise<TenantOverviewSnapshot>;
}

export interface DesktopTenantOverviewAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: TenantOverviewScope,
  ) => DesktopTenantOverviewAuthorityV2;
}

export interface DesktopTenantOverviewOperationsV2 {
  readonly loadTenantOverview: (
    input: DesktopTenantOverviewOperationInputV2,
  ) => Promise<TenantOverviewSnapshot>;
}

type PreparedTenantOverviewOperationV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: TenantOverviewScope;
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
const AUTHORITY_KEYS_V2 = new Set(['load']);

export class DesktopTenantOverviewAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantOverviewAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantOverviewAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_overview_authority_config_invalid',
      'desktop tenant overview authority requires desktop-api-fetch strategy',
    );
  }
  const service: DesktopTenantOverviewAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopTenantOverviewAuthorityV2,
  });
  context.provide(DESKTOP_TENANT_OVERVIEW_AUTHORITY_SERVICE_V2, service);
}

export const desktopTenantOverviewAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_OVERVIEW_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopTenantOverviewAuthorityV2,
});

export function createDesktopTenantOverviewOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantOverviewOperationsV2 {
  return Object.freeze({
    loadTenantOverview(input: DesktopTenantOverviewOperationInputV2) {
      const prepared = prepareTenantOverviewOperationV2(input);
      return runDesktopTenantOverviewAuthorityOperationV2(
        requireGenerationActionsV2(resolveActions()),
        prepared,
        (authority) => authority.load(prepared.signal),
      );
    },
  });
}

export function withDesktopTenantOverviewAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  input: DesktopTenantOverviewOperationInputV2,
  operation: (
    authority: DesktopTenantOverviewAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  return runDesktopTenantOverviewAuthorityOperationV2(
    actions,
    prepareTenantOverviewOperationV2(input),
    operation,
  );
}

async function runDesktopTenantOverviewAuthorityOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedTenantOverviewOperationV2,
  operation: (
    authority: DesktopTenantOverviewAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantOverviewAuthorityServiceV2>({
      service: DESKTOP_TENANT_OVERVIEW_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_OVERVIEW_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'tenant',
        tenant_id: prepared.scope.tenantId,
      }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantOverviewAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((candidate) => {
      const service = requireTenantOverviewServiceV2(candidate);
      const authority = requireTenantOverviewAuthorityV2(
        service.bindOperation(prepared.config, prepared.scope),
      );
      return operation(
        createRevocableTenantOverviewAuthorityV2(
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

function createDesktopTenantOverviewAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: TenantOverviewScope,
): DesktopTenantOverviewAuthorityV2 {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const operationScope = cloneTenantOverviewScopeV2(scope, operationConfig);
  return Object.freeze({
    async load(signal?: AbortSignal) {
      const payload = await requestTenantOverviewJsonV2(
        operationConfig,
        operationScope,
        signal,
      );
      return projectDesktopTenantOverviewResponseV2(payload, operationScope);
    },
  });
}

function createRevocableTenantOverviewAuthorityV2(
  authority: DesktopTenantOverviewAuthorityV2,
  scope: TenantOverviewScope,
  isOperationActive: () => boolean,
): DesktopTenantOverviewAuthorityV2 {
  return Object.freeze({
    async load(signal?: AbortSignal) {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          'desktop_tenant_overview_operation_released',
          'desktop tenant overview operation has been released',
        );
      }
      const result = await authority.load(signal);
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          'desktop_tenant_overview_operation_released',
          'desktop tenant overview operation has been released',
        );
      }
      return requireDesktopTenantOverviewSnapshotV2(result, scope);
    },
  });
}

async function requestTenantOverviewJsonV2(
  config: DesktopRuntimeConfig,
  scope: TenantOverviewScope,
  signal?: AbortSignal,
): Promise<unknown> {
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launchCapability = desktopLaunchCapability(config);
  if (launchCapability) headers.set('X-Agistack-Launch', launchCapability);
  const response = await desktopApiFetch(
    config,
    `/api/v1/tenants/${encodeURIComponent(scope.tenantId)}/stats`,
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
    throw tenantOverviewContractErrorV2(`${config.mode}_tenant_overview_contract_invalid`);
  }
  return payload;
}

function prepareTenantOverviewOperationV2(
  input: DesktopTenantOverviewOperationInputV2,
): PreparedTenantOverviewOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    !hasExactOptionalKeysV2(input, OPERATION_INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidTenantOverviewInputV2();
  }
  const config = cloneDesktopRuntimeConfigV2(input.config);
  const scope = cloneTenantOverviewScopeV2(input.scope, config);
  return Object.freeze({
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

function cloneDesktopRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidTenantOverviewInputV2();
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
    throw invalidTenantOverviewInputV2();
  }
  return Object.freeze(copy);
}

function cloneTenantOverviewScopeV2(
  scope: TenantOverviewScope,
  config: DesktopRuntimeConfig,
): TenantOverviewScope {
  if (
    !isPlainRecordV2(scope) ||
    Object.keys(scope).length !== 2 ||
    scope.authority !== config.mode ||
    !isCanonicalStringV2(scope.tenantId) ||
    scope.tenantId !== config.tenantId
  ) {
    throw invalidTenantOverviewInputV2();
  }
  return Object.freeze({ authority: scope.authority, tenantId: scope.tenantId });
}

function requireTenantOverviewServiceV2(
  value: unknown,
): DesktopTenantOverviewAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidTenantOverviewServiceV2();
  }
  return value as unknown as DesktopTenantOverviewAuthorityServiceV2;
}

function requireTenantOverviewAuthorityV2(
  value: unknown,
): DesktopTenantOverviewAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== AUTHORITY_KEYS_V2.size ||
    !Object.keys(value).every((key) => AUTHORITY_KEYS_V2.has(key)) ||
    typeof value.load !== 'function'
  ) {
    throw invalidTenantOverviewServiceV2();
  }
  return value as unknown as DesktopTenantOverviewAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopTenantOverviewAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidTenantOverviewInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_overview_operation_input_invalid',
    'desktop tenant overview operation input is invalid',
  );
}

function invalidTenantOverviewServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_overview_service_invalid',
    'desktop tenant overview authority service is invalid',
  );
}

function errorMessageV2(status: number, payload: unknown): string {
  if (isPlainRecordV2(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  return `HTTP ${status}`;
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
      candidate.module_ref === DESKTOP_TENANT_OVERVIEW_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_tenant_overview_authority_catalog_missing',
      'desktop tenant overview authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
