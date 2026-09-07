import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  TenantBillingClient,
  TenantBillingSnapshot,
  TenantBillingTenant,
} from '../features/tenant-admin/tenantBillingClient';
import type {
  TenantAdminRequestOptions,
  TenantAdminScope,
} from '../features/tenant-admin/tenantAdminHttp';
import type { DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantBillingHttpProjectionV2 } from './desktopTenantBillingHttpProjectionV2';
import {
  freezeTenantBillingConfigV2,
  prepareTenantBillingLoadV2,
  prepareTenantBillingUpgradeV2,
  requireTenantBillingSnapshotV2,
  requireTenantBillingTenantV2,
  type DesktopTenantBillingLoadInputV2,
  type DesktopTenantBillingUpgradeInputV2,
} from './desktopTenantBillingOperationContractV2';

export const DESKTOP_TENANT_BILLING_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-billing-authority';
export const DESKTOP_TENANT_BILLING_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-billing-authority';
export const DESKTOP_TENANT_BILLING_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantBillingAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig, scope: TenantAdminScope): TenantBillingClient;
}
export interface DesktopTenantBillingOperationsV2 {
  loadTenantBilling(input: DesktopTenantBillingLoadInputV2): Promise<TenantBillingSnapshot>;
  upgradeTenantBillingPlan(input: DesktopTenantBillingUpgradeInputV2): Promise<TenantBillingTenant>;
}
type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;
export class DesktopTenantBillingAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;
  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantBillingAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}
export function applyDesktopTenantBillingAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_tenant_billing_authority_config_invalid',
      'desktop tenant billing authority requires desktop-api-fetch strategy'
    );
  context.provide(
    DESKTOP_TENANT_BILLING_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopTenantBillingHttpProjectionV2(configValue);
      },
    })
  );
}
export const desktopTenantBillingAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_BILLING_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantBillingAuthorityV2,
});
export function createDesktopTenantBillingOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null
): DesktopTenantBillingOperationsV2 {
  return Object.freeze({
    loadTenantBilling(input: DesktopTenantBillingLoadInputV2) {
      const prepared = prepareTenantBillingLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantBillingSnapshotV2(
          await authority.load(prepared.scope, options(prepared.signal)),
          prepared.scope
        )
      );
    },
    upgradeTenantBillingPlan(input: DesktopTenantBillingUpgradeInputV2) {
      const prepared = prepareTenantBillingUpgradeV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantBillingTenantV2(
          await authority.upgradePlan(prepared.scope, prepared.plan, options(prepared.signal)),
          prepared.scope
        )
      );
    },
  });
}
export function createDesktopTenantBillingClientV2(
  operations: DesktopTenantBillingOperationsV2,
  config: DesktopRuntimeConfig
): TenantBillingClient {
  const frozen = freezeTenantBillingConfigV2(config);
  return Object.freeze({
    load: (scope, request) =>
      operations.loadTenantBilling({
        config: frozen,
        scope,
        ...(request?.signal === undefined ? {} : { signal: request.signal }),
      }),
    upgradePlan: (scope, plan, request) =>
      operations.upgradeTenantBillingPlan({
        config: frozen,
        scope,
        plan,
        ...(request?.signal === undefined ? {} : { signal: request.signal }),
      }),
  });
}
async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantBillingLoadInputV2,
  operation: (authority: TenantBillingClient) => Promise<T>
): Promise<T> {
  const actions = resolve();
  if (!actions)
    throw new DesktopTenantBillingAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantBillingAuthorityServiceV2>({
      service: DESKTOP_TENANT_BILLING_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_BILLING_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected')
    throw new DesktopTenantBillingAuthorityUnavailableErrorV2(admission);
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
        typeof raw.upgradePlan !== 'function'
      )
        throw invalidService();
      const authority = Object.freeze({
        load: (...args: Parameters<TenantBillingClient['load']>) => {
          assertActive(active);
          return raw.load(...args);
        },
        upgradePlan: (...args: Parameters<TenantBillingClient['upgradePlan']>) => {
          assertActive(active);
          return raw.upgradePlan(...args);
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
function options(signal?: AbortSignal): TenantAdminRequestOptions | undefined {
  return signal === undefined ? undefined : Object.freeze({ signal });
}
function assertActive(active: boolean): void {
  if (!active)
    throw new RuntimeV2Error(
      'desktop_tenant_billing_operation_released',
      'desktop tenant billing operation released'
    );
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_billing_service_invalid',
    'desktop tenant billing authority service invalid'
  );
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_BILLING_AUTHORITY_MODULE_REF_V2
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_tenant_billing_authority_catalog_missing',
      'desktop tenant billing authority absent from catalog'
    );
  return entry.contract_digest;
}
