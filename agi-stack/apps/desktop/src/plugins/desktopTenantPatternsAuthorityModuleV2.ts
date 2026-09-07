import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  TenantPatternsClient,
  TenantPatternsSnapshot,
} from '../features/tenant-admin/tenantPatternsClient';
import type {
  TenantManagementRequestOptions,
  TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantPatternsHttpProjectionV2 } from './desktopTenantPatternsHttpProjectionV2';
import {
  freezeTenantPatternsConfigV2,
  prepareTenantPatternsDeleteV2,
  prepareTenantPatternsLoadV2,
  requireTenantPatternsSnapshotV2,
  type DesktopTenantPatternsDeleteInputV2,
  type DesktopTenantPatternsLoadInputV2,
} from './desktopTenantPatternsOperationContractV2';

export const DESKTOP_TENANT_PATTERNS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-patterns-authority';
export const DESKTOP_TENANT_PATTERNS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-patterns-authority';
export const DESKTOP_TENANT_PATTERNS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantPatternsAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig, scope: TenantManagementScope): TenantPatternsClient;
}
export interface DesktopTenantPatternsOperationsV2 {
  loadTenantPatterns(input: DesktopTenantPatternsLoadInputV2): Promise<TenantPatternsSnapshot>;
  deleteTenantPattern(input: DesktopTenantPatternsDeleteInputV2): Promise<void>;
}
type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantPatternsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;
  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantPatternsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantPatternsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_patterns_authority_config_invalid',
      'desktop tenant patterns authority requires desktop-api-fetch strategy'
    );
  }
  context.provide(
    DESKTOP_TENANT_PATTERNS_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopTenantPatternsHttpProjectionV2(configValue);
      },
    })
  );
}

export const desktopTenantPatternsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_PATTERNS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantPatternsAuthorityV2,
});

export function createDesktopTenantPatternsOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null
): DesktopTenantPatternsOperationsV2 {
  return Object.freeze({
    loadTenantPatterns(input: DesktopTenantPatternsLoadInputV2) {
      const prepared = prepareTenantPatternsLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantPatternsSnapshotV2(
          await authority.load(prepared.scope, requestOptions(prepared.signal)),
          prepared.scope
        )
      );
    },
    deleteTenantPattern(input: DesktopTenantPatternsDeleteInputV2) {
      const prepared = prepareTenantPatternsDeleteV2(input);
      return run(resolve, prepared, async (authority) => {
        const result = await authority.deletePattern(
          prepared.scope,
          prepared.patternId,
          requestOptions(prepared.signal)
        );
        if (result !== undefined) throw invalidService();
      });
    },
  });
}

export function createDesktopTenantPatternsClientV2(
  operations: DesktopTenantPatternsOperationsV2,
  config: DesktopRuntimeConfig
): TenantPatternsClient {
  const frozen = freezeTenantPatternsConfigV2(config);
  return Object.freeze({
    load: (scope, options) =>
      operations.loadTenantPatterns({
        config: frozen,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
    deletePattern: (scope, patternId, options) =>
      operations.deleteTenantPattern({
        config: frozen,
        scope,
        patternId,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
  });
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantPatternsLoadInputV2,
  operation: (authority: TenantPatternsClient) => Promise<T>
): Promise<T> {
  const actions = resolve();
  if (!actions)
    throw new DesktopTenantPatternsAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantPatternsAuthorityServiceV2>({
      service: DESKTOP_TENANT_PATTERNS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_PATTERNS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected')
    throw new DesktopTenantPatternsAuthorityUnavailableErrorV2(admission);
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      if (
        !record(candidate) ||
        Object.keys(candidate).length !== 1 ||
        typeof candidate.bindOperation !== 'function'
      )
        throw invalidService();
      const raw = candidate.bindOperation(prepared.config, prepared.scope);
      if (
        !record(raw) ||
        Object.keys(raw).length !== 2 ||
        typeof raw.load !== 'function' ||
        typeof raw.deletePattern !== 'function'
      )
        throw invalidService();
      const authority = Object.freeze({
        load: (...args: Parameters<TenantPatternsClient['load']>) => {
          assertActive(active);
          return raw.load(...args);
        },
        deletePattern: (...args: Parameters<TenantPatternsClient['deletePattern']>) => {
          assertActive(active);
          return raw.deletePattern(...args);
        },
      });
      const result = await operation(authority);
      assertActive(active);
      return result;
    });
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    active = false;
    try {
      await admission.release();
    } catch (error) {
      if (!failed) throw error;
    }
  }
}
function requestOptions(signal?: AbortSignal): TenantManagementRequestOptions | undefined {
  return signal === undefined ? undefined : Object.freeze({ signal });
}
function assertActive(active: boolean): void {
  if (!active)
    throw new RuntimeV2Error(
      'desktop_tenant_patterns_operation_released',
      'desktop tenant patterns operation released'
    );
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_patterns_service_invalid',
    'desktop tenant patterns authority service invalid'
  );
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_PATTERNS_AUTHORITY_MODULE_REF_V2
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_tenant_patterns_authority_catalog_missing',
      'desktop tenant patterns authority absent from catalog'
    );
  return entry.contract_digest;
}
