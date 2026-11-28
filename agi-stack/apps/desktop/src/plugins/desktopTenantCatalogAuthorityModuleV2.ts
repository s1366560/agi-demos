import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type { DesktopRuntimeConfig, TenantSummary } from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_TENANT_CATALOG_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-catalog-authority';
export const DESKTOP_TENANT_CATALOG_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-catalog-authority';
export const DESKTOP_TENANT_CATALOG_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopTenantCatalogAuthorityV2 {
  readonly listTenants: (signal?: AbortSignal) => Promise<TenantSummary[]>;
}

export interface DesktopTenantCatalogAuthorityServiceV2 {
  readonly bindOperation: (config: DesktopRuntimeConfig) => DesktopTenantCatalogAuthorityV2;
}

export interface DesktopTenantCatalogOperationsV2 {
  readonly listTenants: (
    config: DesktopRuntimeConfig,
    signal?: AbortSignal,
  ) => Promise<TenantSummary[]>;
}

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

export class DesktopTenantCatalogAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopTenantCatalogAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopTenantCatalogAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'desktop-api-client') {
    throw new RuntimeV2Error(
      'desktop_tenant_catalog_authority_config_invalid',
      'desktop tenant catalog authority requires desktop-api-client strategy',
    );
  }
  const service: DesktopTenantCatalogAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopTenantCatalogAuthorityV2,
  });
  context.provide(DESKTOP_TENANT_CATALOG_AUTHORITY_SERVICE_V2, service);
}

export const desktopTenantCatalogAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_CATALOG_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(),
  apply: applyDesktopTenantCatalogAuthorityV2,
});

export function createDesktopTenantCatalogOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantCatalogOperationsV2 {
  return Object.freeze({
    listTenants: (config: DesktopRuntimeConfig, signal?: AbortSignal) => {
      const actions = requireGenerationActionsV2(resolveActions());
      return withDesktopTenantCatalogOperationV2(
        actions,
        config,
        (authority) => authority.listTenants(signal),
      );
    },
  });
}

export async function withDesktopTenantCatalogOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  config: DesktopRuntimeConfig,
  operation: (authority: DesktopTenantCatalogAuthorityV2) => TResult | Promise<TResult>,
): Promise<TResult> {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const admission =
    await actions.acquireServiceOperationLease<DesktopTenantCatalogAuthorityServiceV2>({
      service: DESKTOP_TENANT_CATALOG_AUTHORITY_SERVICE_V2,
      version: DESKTOP_TENANT_CATALOG_AUTHORITY_VERSION_V2,
      scope: Object.freeze({ kind: 'root' }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopTenantCatalogAuthorityUnavailableErrorV2(admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((service) =>
      operation(
        createRevocableDesktopTenantCatalogAuthorityV2(
          service.bindOperation(operationConfig),
          () => operationActive,
        ),
      ),
    );
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

function createDesktopTenantCatalogAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopTenantCatalogAuthorityV2 {
  const authority = new DesktopApiClient(cloneDesktopRuntimeConfigV2(config));
  return Object.freeze({
    listTenants: (signal?: AbortSignal) => authority.listTenants(signal),
  });
}

function createRevocableDesktopTenantCatalogAuthorityV2(
  authority: DesktopTenantCatalogAuthorityV2,
  isOperationActive: () => boolean,
): DesktopTenantCatalogAuthorityV2 {
  return Object.freeze({
    listTenants: (signal?: AbortSignal) => {
      if (!isOperationActive()) {
        throw new RuntimeV2Error(
          'desktop_tenant_catalog_operation_released',
          'desktop tenant catalog operation has been released',
        );
      }
      return authority.listTenants(signal);
    },
  });
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopTenantCatalogAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function cloneDesktopRuntimeConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
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
    (copy.mode !== 'cloud' && copy.mode !== 'local')
  ) {
    throw new RuntimeV2Error(
      'desktop_tenant_catalog_runtime_config_invalid',
      'desktop tenant catalog operation requires a complete runtime config',
    );
  }
  return Object.freeze(copy);
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === DESKTOP_TENANT_CATALOG_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_tenant_catalog_authority_catalog_missing',
      'desktop tenant catalog authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
