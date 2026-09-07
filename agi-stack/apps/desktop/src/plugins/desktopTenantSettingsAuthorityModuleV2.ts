import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  TenantSettingsClient,
  TenantSettingsSnapshot,
  TenantSettingsTenant,
} from '../features/tenant-admin/tenantSettingsClient';
import type {
  TenantManagementRequestOptions,
  TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantSettingsHttpProjectionV2 } from './desktopTenantSettingsHttpProjectionV2';
import {
  freezeTenantSettingsConfigV2,
  prepareTenantSettingsLoadV2,
  prepareTenantSettingsUpdateV2,
  requireTenantSettingsSnapshotV2,
  requireTenantSettingsTenantV2,
  type DesktopTenantSettingsLoadInputV2,
  type DesktopTenantSettingsUpdateInputV2,
} from './desktopTenantSettingsOperationContractV2';

export const DESKTOP_TENANT_SETTINGS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-settings-authority';
export const DESKTOP_TENANT_SETTINGS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-settings-authority';
export const DESKTOP_TENANT_SETTINGS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantSettingsAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig, scope: TenantManagementScope): TenantSettingsClient;
}
export interface DesktopTenantSettingsOperationsV2 {
  loadTenantSettings(input: DesktopTenantSettingsLoadInputV2): Promise<TenantSettingsSnapshot>;
  updateTenantSettings(input: DesktopTenantSettingsUpdateInputV2): Promise<TenantSettingsTenant>;
  deleteTenant(input: DesktopTenantSettingsLoadInputV2): Promise<void>;
}
type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantSettingsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;
  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantSettingsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantSettingsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_settings_authority_config_invalid',
      'desktop tenant settings authority requires desktop-api-fetch strategy'
    );
  }
  context.provide(
    DESKTOP_TENANT_SETTINGS_AUTHORITY_SERVICE_V2,
    Object.freeze({
      bindOperation(configValue: DesktopRuntimeConfig) {
        return createDesktopTenantSettingsHttpProjectionV2(configValue);
      },
    })
  );
}

export const desktopTenantSettingsAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_SETTINGS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantSettingsAuthorityV2,
});

export function createDesktopTenantSettingsOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null
): DesktopTenantSettingsOperationsV2 {
  return Object.freeze({
    loadTenantSettings(input: DesktopTenantSettingsLoadInputV2) {
      const prepared = prepareTenantSettingsLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantSettingsSnapshotV2(
          await authority.load(prepared.scope, requestOptions(prepared.signal)),
          prepared.scope
        )
      );
    },
    updateTenantSettings(input: DesktopTenantSettingsUpdateInputV2) {
      const prepared = prepareTenantSettingsUpdateV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantSettingsTenantV2(
          await authority.updateTenant(
            prepared.scope,
            prepared.update,
            requestOptions(prepared.signal)
          ),
          prepared.scope
        )
      );
    },
    deleteTenant(input: DesktopTenantSettingsLoadInputV2) {
      const prepared = prepareTenantSettingsLoadV2(input);
      return run(resolve, prepared, async (authority) => {
        const result = await authority.deleteTenant(
          prepared.scope,
          requestOptions(prepared.signal)
        );
        if (result !== undefined) throw invalidService();
      });
    },
  });
}

export function createDesktopTenantSettingsClientV2(
  operations: DesktopTenantSettingsOperationsV2,
  config: DesktopRuntimeConfig
): TenantSettingsClient {
  const frozen = freezeTenantSettingsConfigV2(config);
  return Object.freeze({
    load: (scope, options) =>
      operations.loadTenantSettings({
        config: frozen,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
    updateTenant: (scope, update, options) =>
      operations.updateTenantSettings({
        config: frozen,
        scope,
        update,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
    deleteTenant: (scope, options) =>
      operations.deleteTenant({
        config: frozen,
        scope,
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
      }),
  });
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantSettingsLoadInputV2,
  operation: (authority: TenantSettingsClient) => Promise<T>
): Promise<T> {
  const actions = resolve();
  if (!actions)
    throw new DesktopTenantSettingsAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantSettingsAuthorityServiceV2>({
      service: DESKTOP_TENANT_SETTINGS_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_SETTINGS_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
    });
  if (admission.status === 'rejected')
    throw new DesktopTenantSettingsAuthorityUnavailableErrorV2(admission);
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
        Object.keys(raw).length !== 3 ||
        typeof raw.load !== 'function' ||
        typeof raw.updateTenant !== 'function' ||
        typeof raw.deleteTenant !== 'function'
      )
        throw invalidService();
      const authority = Object.freeze({
        load: (...args: Parameters<TenantSettingsClient['load']>) => {
          assertActive(active);
          return raw.load(...args);
        },
        updateTenant: (...args: Parameters<TenantSettingsClient['updateTenant']>) => {
          assertActive(active);
          return raw.updateTenant(...args);
        },
        deleteTenant: (...args: Parameters<TenantSettingsClient['deleteTenant']>) => {
          assertActive(active);
          return raw.deleteTenant(...args);
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
      'desktop_tenant_settings_operation_released',
      'desktop tenant settings operation released'
    );
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_settings_service_invalid',
    'desktop tenant settings authority service invalid'
  );
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_SETTINGS_AUTHORITY_MODULE_REF_V2
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_tenant_settings_authority_catalog_missing',
      'desktop tenant settings authority absent from catalog'
    );
  return entry.contract_digest;
}
