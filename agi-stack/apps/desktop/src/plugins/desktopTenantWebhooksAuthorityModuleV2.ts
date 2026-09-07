import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  TenantWebhook,
  TenantWebhooksClient,
  TenantWebhooksSnapshot,
} from '../features/tenant-admin/tenantWebhooksClient';
import type {
  TenantManagementRequestOptions,
  TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantWebhooksHttpProjectionV2 } from './desktopTenantWebhooksHttpProjectionV2';
import {
  freezeTenantWebhooksConfigV2,
  prepareTenantWebhookCreateV2,
  prepareTenantWebhookDeleteV2,
  prepareTenantWebhookUpdateV2,
  prepareTenantWebhooksLoadV2,
  requireTenantWebhookV2,
  requireTenantWebhooksSnapshotV2,
  type DesktopTenantWebhookCreateInputV2,
  type DesktopTenantWebhookDeleteInputV2,
  type DesktopTenantWebhookUpdateInputV2,
  type DesktopTenantWebhooksLoadInputV2,
} from './desktopTenantWebhooksOperationContractV2';

export const DESKTOP_TENANT_WEBHOOKS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-webhooks-authority';
export const DESKTOP_TENANT_WEBHOOKS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-webhooks-authority';
export const DESKTOP_TENANT_WEBHOOKS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantWebhooksAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig, scope: TenantManagementScope): TenantWebhooksClient;
}
export interface DesktopTenantWebhooksOperationsV2 {
  loadTenantWebhooks(input: DesktopTenantWebhooksLoadInputV2): Promise<TenantWebhooksSnapshot>;
  createTenantWebhook(input: DesktopTenantWebhookCreateInputV2): Promise<TenantWebhook>;
  updateTenantWebhook(input: DesktopTenantWebhookUpdateInputV2): Promise<TenantWebhook>;
  deleteTenantWebhook(input: DesktopTenantWebhookDeleteInputV2): Promise<void>;
}
type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantWebhooksAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;
  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantWebhooksAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantWebhooksAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_webhooks_authority_config_invalid',
      'desktop tenant webhooks authority requires desktop-api-fetch strategy'
    );
  }
  context.provide(
    DESKTOP_TENANT_WEBHOOKS_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopTenantWebhooksHttpProjectionV2(configValue);
      },
    })
  );
}

export const desktopTenantWebhooksAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_WEBHOOKS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantWebhooksAuthorityV2,
});

export function createDesktopTenantWebhooksOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null
): DesktopTenantWebhooksOperationsV2 {
  return Object.freeze({
    loadTenantWebhooks(input: DesktopTenantWebhooksLoadInputV2) {
      const prepared = prepareTenantWebhooksLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantWebhooksSnapshotV2(
          await authority.load(prepared.scope, requestOptions(prepared.signal)),
          prepared.scope
        )
      );
    },
    createTenantWebhook(input: DesktopTenantWebhookCreateInputV2) {
      const prepared = prepareTenantWebhookCreateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantWebhookV2(
          await authority.createWebhook(
            prepared.scope,
            prepared.webhook,
            requestOptions(prepared.signal)
          ),
          prepared.scope
        )
      );
    },
    updateTenantWebhook(input: DesktopTenantWebhookUpdateInputV2) {
      const prepared = prepareTenantWebhookUpdateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantWebhookV2(
          await authority.updateWebhook(
            prepared.scope,
            prepared.webhookId,
            prepared.webhook,
            requestOptions(prepared.signal)
          ),
          prepared.scope
        )
      );
    },
    deleteTenantWebhook(input: DesktopTenantWebhookDeleteInputV2) {
      const prepared = prepareTenantWebhookDeleteV2(input);
      return run(resolve, prepared, async (authority) => {
        const result = await authority.deleteWebhook(
          prepared.scope,
          prepared.webhookId,
          requestOptions(prepared.signal)
        );
        if (result !== undefined) throw invalidService();
      });
    },
  });
}

export function createDesktopTenantWebhooksClientV2(
  operations: DesktopTenantWebhooksOperationsV2,
  config: DesktopRuntimeConfig
): TenantWebhooksClient {
  const frozen = freezeTenantWebhooksConfigV2(config);
  const base = (scope: TenantManagementScope, signal?: AbortSignal) => ({
    config: frozen,
    scope,
    ...(signal === undefined ? {} : { signal }),
  });
  return Object.freeze({
    load: (scope, options) => operations.loadTenantWebhooks(base(scope, options?.signal)),
    createWebhook: (scope, webhook, options) =>
      operations.createTenantWebhook({ ...base(scope, options?.signal), webhook }),
    updateWebhook: (scope, webhookId, webhook, options) =>
      operations.updateTenantWebhook({ ...base(scope, options?.signal), webhookId, webhook }),
    deleteWebhook: (scope, webhookId, options) =>
      operations.deleteTenantWebhook({ ...base(scope, options?.signal), webhookId }),
  });
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantWebhooksLoadInputV2,
  operation: (authority: TenantWebhooksClient) => Promise<T>
): Promise<T> {
  const actions = resolve();
  if (!actions)
    throw new DesktopTenantWebhooksAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantWebhooksAuthorityServiceV2>({
      service: DESKTOP_TENANT_WEBHOOKS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_WEBHOOKS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected')
    throw new DesktopTenantWebhooksAuthorityUnavailableErrorV2(admission);
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
        Object.keys(raw).length !== 4 ||
        typeof raw.load !== 'function' ||
        typeof raw.createWebhook !== 'function' ||
        typeof raw.updateWebhook !== 'function' ||
        typeof raw.deleteWebhook !== 'function'
      )
        throw invalidService();
      const authority = Object.freeze({
        load: (...args: Parameters<TenantWebhooksClient['load']>) => invoke(active, raw.load, args),
        createWebhook: (...args: Parameters<TenantWebhooksClient['createWebhook']>) =>
          invoke(active, raw.createWebhook, args),
        updateWebhook: (...args: Parameters<TenantWebhooksClient['updateWebhook']>) =>
          invoke(active, raw.updateWebhook, args),
        deleteWebhook: (...args: Parameters<TenantWebhooksClient['deleteWebhook']>) =>
          invoke(active, raw.deleteWebhook, args),
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
function invoke<F extends (...args: never[]) => unknown>(
  active: boolean,
  fn: F,
  args: Parameters<F>
): ReturnType<F> {
  assertActive(active);
  return fn(...args) as ReturnType<F>;
}
function requestOptions(signal?: AbortSignal): TenantManagementRequestOptions | undefined {
  return signal === undefined ? undefined : Object.freeze({ signal });
}
function assertActive(active: boolean): void {
  if (!active)
    throw new RuntimeV2Error(
      'desktop_tenant_webhooks_operation_released',
      'desktop tenant webhooks operation released'
    );
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_webhooks_service_invalid',
    'desktop tenant webhooks authority service invalid'
  );
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_WEBHOOKS_AUTHORITY_MODULE_REF_V2
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_tenant_webhooks_authority_catalog_missing',
      'desktop tenant webhooks authority absent from catalog'
    );
  return entry.contract_digest;
}
