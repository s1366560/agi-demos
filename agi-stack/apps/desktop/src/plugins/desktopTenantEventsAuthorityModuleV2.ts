import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import {
  type TenantEventFilters,
  type TenantEventsClient,
  type TenantEventsSnapshot,
} from '../features/tenant-admin/tenantEventsClient';
import type {
  TenantManagementRequestOptions,
  TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantEventsHttpProjectionV2 } from './desktopTenantEventsHttpProjectionV2';
import {
  freezeDesktopRuntimeConfigV2,
  prepareDesktopTenantEventsOperationV2,
  requireDesktopTenantEventsSnapshotV2,
  type DesktopTenantEventsOperationInputV2,
} from './desktopTenantEventsOperationContractV2';

export const DESKTOP_TENANT_EVENTS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-events-authority';
export const DESKTOP_TENANT_EVENTS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-events-authority';
export const DESKTOP_TENANT_EVENTS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantEventsAuthorityServiceV2 {
  bindOperation(
    config: DesktopRuntimeConfig,
    scope: TenantManagementScope
  ): Pick<TenantEventsClient, 'load'>;
}
export interface DesktopTenantEventsOperationsV2 {
  loadTenantEvents(input: DesktopTenantEventsOperationInputV2): Promise<TenantEventsSnapshot>;
}
type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantEventsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;
  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantEventsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantEventsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_tenant_events_authority_config_invalid',
      'desktop tenant events authority requires desktop-api-fetch strategy'
    );
  context.provide(
    DESKTOP_TENANT_EVENTS_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig, scope: TenantManagementScope) {
        const client = createDesktopTenantEventsHttpProjectionV2(configValue);
        return Object.freeze({
          load: (
            _scope: TenantManagementScope,
            options?: TenantManagementRequestOptions & Readonly<{ filters?: TenantEventFilters }>
          ) => client.load(scope, options),
        });
      },
    })
  );
}

export const desktopTenantEventsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_EVENTS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantEventsAuthorityV2,
});

export function createDesktopTenantEventsOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null
): DesktopTenantEventsOperationsV2 {
  return Object.freeze({
    loadTenantEvents(input: DesktopTenantEventsOperationInputV2) {
      const prepared = prepareDesktopTenantEventsOperationV2(input);
      return run(requireActions(resolve()), prepared);
    },
  });
}

export function createDesktopTenantEventsClientV2(
  operations: DesktopTenantEventsOperationsV2,
  config: DesktopRuntimeConfig
): TenantEventsClient {
  const frozen = freezeDesktopRuntimeConfigV2(config);
  return Object.freeze({
    load: (scope, options) =>
      operations.loadTenantEvents({
        config: frozen,
        scope,
        ...(options?.filters === undefined ? {} : { filters: options.filters }),
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
  });
}

async function run(
  actions: DesktopRendererGenerationActionsV2,
  prepared: DesktopTenantEventsOperationInputV2
): Promise<TenantEventsSnapshot> {
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantEventsAuthorityServiceV2>({
      service: DESKTOP_TENANT_EVENTS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_EVENTS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({
        kind: 'tenant',
        tenant_id: prepared.scope.tenantId,
      }),
    });
  if (admission.status === 'rejected')
    throw new DesktopTenantEventsAuthorityUnavailableErrorV2(admission);
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      const service = requireService(candidate);
      assertActive(active);
      const authority = service.bindOperation(prepared.config, prepared.scope);
      if (!authority || typeof authority.load !== 'function') throw invalidService();
      const result = await authority.load(prepared.scope, {
        ...(prepared.filters === undefined ? {} : { filters: prepared.filters }),
        ...(prepared.signal === undefined ? {} : { signal: prepared.signal }),
      });
      assertActive(active);
      return requireDesktopTenantEventsSnapshotV2(result, prepared.scope);
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

function requireService(value: unknown): DesktopTenantEventsAuthorityServiceV2 {
  if (!record(value) || typeof value.bindOperation !== 'function') throw invalidService();
  return value as unknown as DesktopTenantEventsAuthorityServiceV2;
}
function requireActions(
  value: DesktopRendererGenerationActionsV2 | null
): DesktopRendererGenerationActionsV2 {
  if (value) return value;
  throw new DesktopTenantEventsAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}
function assertActive(active: boolean): void {
  if (!active)
    throw new RuntimeV2Error(
      'desktop_tenant_events_operation_released',
      'desktop tenant events operation released'
    );
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_events_service_invalid',
    'desktop tenant events authority service invalid'
  );
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_TENANT_EVENTS_AUTHORITY_MODULE_REF_V2
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_tenant_events_authority_catalog_missing',
      'desktop tenant events authority absent from catalog'
    );
  return entry.contract_digest;
}
