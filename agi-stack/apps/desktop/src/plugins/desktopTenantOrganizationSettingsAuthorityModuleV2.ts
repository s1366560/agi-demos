import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type {
  TenantOrganizationSettingsClient,
  TenantOrganizationSettingsSnapshot,
  TenantRegistry,
  TenantSmtpConfig,
  TenantGenePolicy,
} from '../features/tenant-admin/tenantOrganizationSettingsClient';
import type {
  TenantManagementRequestOptions,
  TenantManagementScope,
} from '../features/tenant-admin/tenantManagementHttp';
import type { DesktopRuntimeConfig } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';
import { createDesktopTenantOrganizationSettingsHttpProjectionV2 } from './desktopTenantOrganizationSettingsHttpProjectionV2';
import {
  freezeTenantOrganizationSettingsConfigV2,
  prepareTenantOrganizationSettingsGenePolicyV2,
  prepareTenantOrganizationSettingsLoadV2,
  prepareTenantOrganizationSettingsPolicyKeyV2,
  prepareTenantOrganizationSettingsRegistryIdV2,
  prepareTenantOrganizationSettingsRegistryV2,
  prepareTenantOrganizationSettingsSmtpTestV2,
  prepareTenantOrganizationSettingsSmtpV2,
  requireTenantOrganizationSettingsGenePolicyV2,
  requireTenantOrganizationSettingsRegistryV2,
  requireTenantOrganizationSettingsSmtpConfigV2,
  requireTenantOrganizationSettingsSnapshotV2,
  requireTenantOrganizationSettingsTestResultV2,
  type DesktopTenantOrganizationSettingsGenePolicyInputV2,
  type DesktopTenantOrganizationSettingsLoadInputV2,
  type DesktopTenantOrganizationSettingsPolicyKeyInputV2,
  type DesktopTenantOrganizationSettingsRegistryIdInputV2,
  type DesktopTenantOrganizationSettingsRegistryInputV2,
  type DesktopTenantOrganizationSettingsSmtpInputV2,
  type DesktopTenantOrganizationSettingsSmtpTestInputV2,
} from './desktopTenantOrganizationSettingsOperationContractV2';

export const DESKTOP_TENANT_ORGANIZATION_SETTINGS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-organization-settings-authority';
export const DESKTOP_TENANT_ORGANIZATION_SETTINGS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-organization-settings-authority';
export const DESKTOP_TENANT_ORGANIZATION_SETTINGS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantOrganizationSettingsAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): TenantOrganizationSettingsClient;
}

export interface DesktopTenantOrganizationSettingsOperationsV2 {
  loadTenantOrganizationSettings(
    input: DesktopTenantOrganizationSettingsLoadInputV2,
  ): Promise<TenantOrganizationSettingsSnapshot>;
  saveTenantOrganizationRegistry(
    input: DesktopTenantOrganizationSettingsRegistryInputV2,
  ): Promise<TenantRegistry>;
  deleteTenantOrganizationRegistry(
    input: DesktopTenantOrganizationSettingsRegistryIdInputV2,
  ): Promise<void>;
  testTenantOrganizationRegistry(
    input: DesktopTenantOrganizationSettingsRegistryIdInputV2,
  ): Promise<Readonly<Record<string, unknown>>>;
  saveTenantOrganizationSmtp(
    input: DesktopTenantOrganizationSettingsSmtpInputV2,
  ): Promise<TenantSmtpConfig>;
  deleteTenantOrganizationSmtp(
    input: DesktopTenantOrganizationSettingsLoadInputV2,
  ): Promise<void>;
  testTenantOrganizationSmtp(
    input: DesktopTenantOrganizationSettingsSmtpTestInputV2,
  ): Promise<Readonly<Record<string, unknown>>>;
  saveTenantOrganizationGenePolicy(
    input: DesktopTenantOrganizationSettingsGenePolicyInputV2,
  ): Promise<TenantGenePolicy>;
  deleteTenantOrganizationGenePolicy(
    input: DesktopTenantOrganizationSettingsPolicyKeyInputV2,
  ): Promise<void>;
}

type Rejection =
  | Extract<DesktopRendererServiceOperationLeaseAdmissionV2<never>, { status: 'rejected' }>
  | Readonly<{
      reasonCode: 'desktop_renderer_generation_actions_unavailable';
      runtimeCode?: undefined;
    }>;

export class DesktopTenantOrganizationSettingsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: Rejection['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: Rejection) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantOrganizationSettingsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantOrganizationSettingsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch') {
    throw new RuntimeV2Error(
      'desktop_tenant_organization_settings_authority_config_invalid',
      'desktop tenant organization settings authority requires desktop-api-fetch strategy',
    );
  }
  context.provide(
    DESKTOP_TENANT_ORGANIZATION_SETTINGS_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopTenantOrganizationSettingsHttpProjectionV2 }),
  );
}

export const desktopTenantOrganizationSettingsAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_TENANT_ORGANIZATION_SETTINGS_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedDigest(),
    apply: applyDesktopTenantOrganizationSettingsAuthorityV2,
  });

export function createDesktopTenantOrganizationSettingsOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantOrganizationSettingsOperationsV2 {
  return Object.freeze({
    loadTenantOrganizationSettings(input: DesktopTenantOrganizationSettingsLoadInputV2) {
      const prepared = prepareTenantOrganizationSettingsLoadV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantOrganizationSettingsSnapshotV2(
          await authority.load(prepared.scope, requestOptions(prepared.signal)),
          prepared.scope,
        ),
      );
    },
    saveTenantOrganizationRegistry(input: DesktopTenantOrganizationSettingsRegistryInputV2) {
      const prepared = prepareTenantOrganizationSettingsRegistryV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantOrganizationSettingsRegistryV2(
          await authority.saveRegistry(
            prepared.scope,
            prepared.input,
            requestOptions(prepared.signal),
          ),
          prepared.scope,
        ),
      );
    },
    deleteTenantOrganizationRegistry(
      input: DesktopTenantOrganizationSettingsRegistryIdInputV2,
    ) {
      const prepared = prepareTenantOrganizationSettingsRegistryIdV2(input);
      return run(resolve, prepared, async (authority) => {
        const result = await authority.deleteRegistry(
          prepared.scope,
          prepared.registryId,
          requestOptions(prepared.signal),
        );
        if (result !== undefined) throw invalidService();
      });
    },
    testTenantOrganizationRegistry(input: DesktopTenantOrganizationSettingsRegistryIdInputV2) {
      const prepared = prepareTenantOrganizationSettingsRegistryIdV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantOrganizationSettingsTestResultV2(
          await authority.testRegistry(
            prepared.scope,
            prepared.registryId,
            requestOptions(prepared.signal),
          ),
        ),
      );
    },
    saveTenantOrganizationSmtp(input: DesktopTenantOrganizationSettingsSmtpInputV2) {
      const prepared = prepareTenantOrganizationSettingsSmtpV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantOrganizationSettingsSmtpConfigV2(
          await authority.saveSmtp(
            prepared.scope,
            prepared.input,
            requestOptions(prepared.signal),
          ),
          prepared.scope,
        ),
      );
    },
    deleteTenantOrganizationSmtp(input: DesktopTenantOrganizationSettingsLoadInputV2) {
      const prepared = prepareTenantOrganizationSettingsLoadV2(input);
      return run(resolve, prepared, async (authority) => {
        const result = await authority.deleteSmtp(
          prepared.scope,
          requestOptions(prepared.signal),
        );
        if (result !== undefined) throw invalidService();
      });
    },
    testTenantOrganizationSmtp(input: DesktopTenantOrganizationSettingsSmtpTestInputV2) {
      const prepared = prepareTenantOrganizationSettingsSmtpTestV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantOrganizationSettingsTestResultV2(
          await authority.testSmtp(
            prepared.scope,
            prepared.recipientEmail,
            requestOptions(prepared.signal),
          ),
        ),
      );
    },
    saveTenantOrganizationGenePolicy(
      input: DesktopTenantOrganizationSettingsGenePolicyInputV2,
    ) {
      const prepared = prepareTenantOrganizationSettingsGenePolicyV2(input);
      return run(resolve, prepared, async (authority) =>
        requireTenantOrganizationSettingsGenePolicyV2(
          await authority.saveGenePolicy(
            prepared.scope,
            prepared.input,
            requestOptions(prepared.signal),
          ),
          prepared.scope,
        ),
      );
    },
    deleteTenantOrganizationGenePolicy(
      input: DesktopTenantOrganizationSettingsPolicyKeyInputV2,
    ) {
      const prepared = prepareTenantOrganizationSettingsPolicyKeyV2(input);
      return run(resolve, prepared, async (authority) => {
        const result = await authority.deleteGenePolicy(
          prepared.scope,
          prepared.policyKey,
          requestOptions(prepared.signal),
        );
        if (result !== undefined) throw invalidService();
      });
    },
  });
}

export function createDesktopTenantOrganizationSettingsClientV2(
  operations: DesktopTenantOrganizationSettingsOperationsV2,
  config: DesktopRuntimeConfig,
): TenantOrganizationSettingsClient {
  const frozen = freezeTenantOrganizationSettingsConfigV2(config);
  return Object.freeze({
    load: (scope, options) =>
      operations.loadTenantOrganizationSettings(operationInput(frozen, scope, options)),
    saveRegistry: (scope, input, options) =>
      operations.saveTenantOrganizationRegistry({
        ...operationInput(frozen, scope, options),
        input,
      }),
    deleteRegistry: (scope, registryId, options) =>
      operations.deleteTenantOrganizationRegistry({
        ...operationInput(frozen, scope, options),
        registryId,
      }),
    testRegistry: (scope, registryId, options) =>
      operations.testTenantOrganizationRegistry({
        ...operationInput(frozen, scope, options),
        registryId,
      }),
    saveSmtp: (scope, input, options) =>
      operations.saveTenantOrganizationSmtp({
        ...operationInput(frozen, scope, options),
        input,
      }),
    deleteSmtp: (scope, options) =>
      operations.deleteTenantOrganizationSmtp(operationInput(frozen, scope, options)),
    testSmtp: (scope, recipientEmail, options) =>
      operations.testTenantOrganizationSmtp({
        ...operationInput(frozen, scope, options),
        recipientEmail,
      }),
    saveGenePolicy: (scope, input, options) =>
      operations.saveTenantOrganizationGenePolicy({
        ...operationInput(frozen, scope, options),
        input,
      }),
    deleteGenePolicy: (scope, policyKey, options) =>
      operations.deleteTenantOrganizationGenePolicy({
        ...operationInput(frozen, scope, options),
        policyKey,
      }),
  });
}

async function run<T>(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
  prepared: DesktopTenantOrganizationSettingsLoadInputV2,
  operation: (authority: TenantOrganizationSettingsClient) => Promise<T>,
): Promise<T> {
  const actions = resolve();
  if (!actions) {
    throw new DesktopTenantOrganizationSettingsAuthorityUnavailableErrorV2({
      reasonCode: 'desktop_renderer_generation_actions_unavailable',
    });
  }
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantOrganizationSettingsAuthorityServiceV2>(
      {
        service: DESKTOP_TENANT_ORGANIZATION_SETTINGS_AUTHORITY_SERVICE_V2,
        version: DESKTOP_TENANT_ORGANIZATION_SETTINGS_AUTHORITY_VERSION_V2,
        scope: Object.freeze({ kind: 'tenant', tenant_id: prepared.scope.tenantId }),
      },
    );
  if (admission.status === 'rejected') {
    throw new DesktopTenantOrganizationSettingsAuthorityUnavailableErrorV2(admission);
  }
  let failed = false;
  let active = true;
  try {
    return await admission.useService(async (candidate) => {
      if (
        !record(candidate) ||
        Object.keys(candidate).length !== 1 ||
        typeof candidate.bindOperation !== 'function'
      ) {
        throw invalidService();
      }
      const raw = candidate.bindOperation(prepared.config);
      if (!validAuthority(raw)) throw invalidService();
      const authority = revocableAuthority(raw, () => active);
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

function revocableAuthority(
  raw: TenantOrganizationSettingsClient,
  active: () => boolean,
): TenantOrganizationSettingsClient {
  return Object.freeze({
    load: (...args) => invoke(active, raw.load, args),
    saveRegistry: (...args) => invoke(active, raw.saveRegistry, args),
    deleteRegistry: (...args) => invoke(active, raw.deleteRegistry, args),
    testRegistry: (...args) => invoke(active, raw.testRegistry, args),
    saveSmtp: (...args) => invoke(active, raw.saveSmtp, args),
    deleteSmtp: (...args) => invoke(active, raw.deleteSmtp, args),
    testSmtp: (...args) => invoke(active, raw.testSmtp, args),
    saveGenePolicy: (...args) => invoke(active, raw.saveGenePolicy, args),
    deleteGenePolicy: (...args) => invoke(active, raw.deleteGenePolicy, args),
  });
}

function invoke<TArgs extends readonly unknown[], TResult>(
  active: () => boolean,
  operation: (...args: TArgs) => TResult,
  args: TArgs,
): TResult {
  assertActive(active());
  return operation(...args);
}

function validAuthority(value: unknown): value is TenantOrganizationSettingsClient {
  if (!record(value) || Object.keys(value).length !== 9) return false;
  return [
    'load',
    'saveRegistry',
    'deleteRegistry',
    'testRegistry',
    'saveSmtp',
    'deleteSmtp',
    'testSmtp',
    'saveGenePolicy',
    'deleteGenePolicy',
  ].every((key) => typeof value[key] === 'function');
}

function operationInput(
  config: DesktopRuntimeConfig,
  scope: TenantManagementScope,
  options?: TenantManagementRequestOptions,
): DesktopTenantOrganizationSettingsLoadInputV2 {
  return Object.freeze({
    config,
    scope,
    ...(options?.signal === undefined ? {} : { signal: options.signal }),
  });
}

function requestOptions(signal?: AbortSignal): TenantManagementRequestOptions | undefined {
  return signal === undefined ? undefined : Object.freeze({ signal });
}

function assertActive(active: boolean): void {
  if (!active) {
    throw new RuntimeV2Error(
      'desktop_tenant_organization_settings_operation_released',
      'desktop tenant organization settings operation released',
    );
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidService(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_tenant_organization_settings_service_invalid',
    'desktop tenant organization settings authority service invalid',
  );
}

function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) =>
      item.module_ref === DESKTOP_TENANT_ORGANIZATION_SETTINGS_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) {
    throw new RuntimeV2Error(
      'desktop_tenant_organization_settings_authority_catalog_missing',
      'desktop tenant organization settings authority absent from catalog',
    );
  }
  return entry.contract_digest;
}
