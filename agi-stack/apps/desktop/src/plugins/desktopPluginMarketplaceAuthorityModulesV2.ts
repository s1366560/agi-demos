import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import { DesktopApiClient } from '../api/client';
import type {
  DesktopRuntimeConfig,
  ManagedPlugin,
  MarketplacePluginUninstallResponse,
} from '../types';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export const DESKTOP_PLUGIN_MARKETPLACE_CATALOG_MODULE_REF_V2 =
  'builtin://memstack/desktop/plugin-marketplace-catalog-authority';
export const DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2 =
  'service:desktop-renderer.plugin-marketplace-catalog';
export const DESKTOP_PLUGIN_MARKETPLACE_CATALOG_VERSION_V2 = '1.0.0';

export const DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_MODULE_REF_V2 =
  'builtin://memstack/desktop/plugin-marketplace-management-authority';
export const DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2 =
  'service:desktop-renderer.plugin-marketplace-management';
export const DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_VERSION_V2 = '1.0.0';

export type DesktopPluginMarketplaceAuthorityKindV2 = 'catalog' | 'management';

export interface DesktopPluginMarketplaceCatalogAuthorityV2 {
  readonly listMarketplacePlugins: (signal?: AbortSignal) => Promise<ManagedPlugin[]>;
}

export interface DesktopPluginMarketplaceManagementAuthorityV2 {
  readonly uninstallMarketplacePlugin: (
    pluginId: string,
    version: string,
    signal?: AbortSignal,
  ) => Promise<MarketplacePluginUninstallResponse>;
}

export interface DesktopPluginMarketplaceCatalogServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopPluginMarketplaceCatalogAuthorityV2;
}

export interface DesktopPluginMarketplaceManagementServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopPluginMarketplaceManagementAuthorityV2;
}

export interface DesktopPluginMarketplaceOperationsV2 {
  readonly listMarketplacePlugins: (
    config: DesktopRuntimeConfig,
    signal?: AbortSignal,
  ) => Promise<ManagedPlugin[]>;
  readonly projectMarketplacePlugins: <TResult>(
    config: DesktopRuntimeConfig,
    signal: AbortSignal | undefined,
    project: (plugins: ManagedPlugin[]) => TResult | Promise<TResult>,
  ) => Promise<TResult>;
  readonly uninstallMarketplacePlugin: (
    config: DesktopRuntimeConfig,
    pluginId: string,
    version: string,
    signal?: AbortSignal,
  ) => Promise<MarketplacePluginUninstallResponse>;
}

export type DesktopPluginMarketplaceCatalogOperationsV2 = Pick<
  DesktopPluginMarketplaceOperationsV2,
  'listMarketplacePlugins' | 'projectMarketplacePlugins'
>;

export type DesktopPluginMarketplaceManagementOperationsV2 = Pick<
  DesktopPluginMarketplaceOperationsV2,
  'uninstallMarketplacePlugin'
>;

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

export class DesktopPluginMarketplaceAuthorityUnavailableErrorV2 extends Error {
  readonly service: DesktopPluginMarketplaceAuthorityKindV2;
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(
    service: DesktopPluginMarketplaceAuthorityKindV2,
    rejection: AuthorityAdmissionRejectionV2,
  ) {
    super(rejection.reasonCode);
    this.name = 'DesktopPluginMarketplaceAuthorityUnavailableErrorV2';
    this.service = service;
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopPluginMarketplaceCatalogAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  requireDesktopApiClientStrategyV2(config, 'catalog');
  const service: DesktopPluginMarketplaceCatalogServiceV2 = Object.freeze({
    bindOperation: createDesktopPluginMarketplaceCatalogAuthorityV2,
  });
  context.provide(DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2, service);
}

export function applyDesktopPluginMarketplaceManagementAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  requireDesktopApiClientStrategyV2(config, 'management');
  const service: DesktopPluginMarketplaceManagementServiceV2 = Object.freeze({
    bindOperation: createDesktopPluginMarketplaceManagementAuthorityV2,
  });
  context.provide(DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2, service);
}

export const desktopPluginMarketplaceCatalogDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(
    DESKTOP_PLUGIN_MARKETPLACE_CATALOG_MODULE_REF_V2,
    'catalog',
  ),
  apply: applyDesktopPluginMarketplaceCatalogAuthorityV2,
});

export const desktopPluginMarketplaceManagementDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_MODULE_REF_V2,
  contractDigest: generatedContractDigestV2(
    DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_MODULE_REF_V2,
    'management',
  ),
  apply: applyDesktopPluginMarketplaceManagementAuthorityV2,
});

export function createDesktopPluginMarketplaceOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopPluginMarketplaceOperationsV2 {
  return Object.freeze({
    listMarketplacePlugins: (config: DesktopRuntimeConfig, signal?: AbortSignal) => {
      const actions = requireGenerationActionsV2('catalog', resolveActions());
      return withDesktopPluginMarketplaceCatalogOperationV2(
        actions,
        config,
        (authority) => authority.listMarketplacePlugins(signal),
      );
    },
    projectMarketplacePlugins: <TResult>(
      config: DesktopRuntimeConfig,
      signal: AbortSignal | undefined,
      project: (plugins: ManagedPlugin[]) => TResult | Promise<TResult>,
    ) => {
      const actions = requireGenerationActionsV2('catalog', resolveActions());
      return withDesktopPluginMarketplaceCatalogOperationV2(
        actions,
        config,
        async (authority) => project(await authority.listMarketplacePlugins(signal)),
      );
    },
    uninstallMarketplacePlugin: (
      config: DesktopRuntimeConfig,
      pluginId: string,
      version: string,
      signal?: AbortSignal,
    ) => {
      const actions = requireGenerationActionsV2('management', resolveActions());
      return withDesktopPluginMarketplaceManagementOperationV2(
        actions,
        config,
        (authority) => authority.uninstallMarketplacePlugin(pluginId, version, signal),
      );
    },
  });
}

export async function withDesktopPluginMarketplaceCatalogOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  config: DesktopRuntimeConfig,
  operation: (
    authority: DesktopPluginMarketplaceCatalogAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const admission =
    await actions.acquireServiceOperationLease<DesktopPluginMarketplaceCatalogServiceV2>({
      service: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_SERVICE_V2,
      version: DESKTOP_PLUGIN_MARKETPLACE_CATALOG_VERSION_V2,
      scope: Object.freeze({ kind: 'root' }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopPluginMarketplaceAuthorityUnavailableErrorV2('catalog', admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((service) =>
      operation(
        createRevocableCatalogAuthorityV2(
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

export async function withDesktopPluginMarketplaceManagementOperationV2<TResult>(
  actions: DesktopRendererGenerationActionsV2,
  config: DesktopRuntimeConfig,
  operation: (
    authority: DesktopPluginMarketplaceManagementAuthorityV2,
  ) => TResult | Promise<TResult>,
): Promise<TResult> {
  const operationConfig = cloneDesktopRuntimeConfigV2(config);
  const admission =
    await actions.acquireServiceOperationLease<DesktopPluginMarketplaceManagementServiceV2>({
      service: DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_SERVICE_V2,
      version: DESKTOP_PLUGIN_MARKETPLACE_MANAGEMENT_VERSION_V2,
      scope: Object.freeze({ kind: 'root' }),
    });
  if (admission.status === 'rejected') {
    throw new DesktopPluginMarketplaceAuthorityUnavailableErrorV2('management', admission);
  }

  let operationFailed = false;
  let operationActive = true;
  try {
    return await admission.useService((service) =>
      operation(
        createRevocableManagementAuthorityV2(
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

function createDesktopPluginMarketplaceCatalogAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopPluginMarketplaceCatalogAuthorityV2 {
  const authority = new DesktopApiClient(cloneDesktopRuntimeConfigV2(config));
  return Object.freeze({
    listMarketplacePlugins: (signal?: AbortSignal) =>
      authority.listMarketplacePlugins(signal),
  });
}

function createDesktopPluginMarketplaceManagementAuthorityV2(
  config: DesktopRuntimeConfig,
): DesktopPluginMarketplaceManagementAuthorityV2 {
  const authority = new DesktopApiClient(cloneDesktopRuntimeConfigV2(config));
  return Object.freeze({
    uninstallMarketplacePlugin: (
      pluginId: string,
      version: string,
      signal?: AbortSignal,
    ) => authority.uninstallMarketplacePlugin(pluginId, version, signal),
  });
}

function createRevocableCatalogAuthorityV2(
  authority: DesktopPluginMarketplaceCatalogAuthorityV2,
  isOperationActive: () => boolean,
): DesktopPluginMarketplaceCatalogAuthorityV2 {
  return Object.freeze({
    listMarketplacePlugins: (signal?: AbortSignal) => {
      assertOperationActiveV2('catalog', isOperationActive());
      return authority.listMarketplacePlugins(signal);
    },
  });
}

function createRevocableManagementAuthorityV2(
  authority: DesktopPluginMarketplaceManagementAuthorityV2,
  isOperationActive: () => boolean,
): DesktopPluginMarketplaceManagementAuthorityV2 {
  return Object.freeze({
    uninstallMarketplacePlugin: (
      pluginId: string,
      version: string,
      signal?: AbortSignal,
    ) => {
      assertOperationActiveV2('management', isOperationActive());
      return authority.uninstallMarketplacePlugin(pluginId, version, signal);
    },
  });
}

function assertOperationActiveV2(
  service: DesktopPluginMarketplaceAuthorityKindV2,
  active: boolean,
): void {
  if (active) return;
  throw new RuntimeV2Error(
    `desktop_plugin_marketplace_${service}_operation_released`,
    `desktop plugin marketplace ${service} operation has been released`,
  );
}

function requireGenerationActionsV2(
  service: DesktopPluginMarketplaceAuthorityKindV2,
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopPluginMarketplaceAuthorityUnavailableErrorV2(service, {
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function requireDesktopApiClientStrategyV2(
  config: Readonly<Record<string, unknown>>,
  service: DesktopPluginMarketplaceAuthorityKindV2,
): void {
  if (config.strategy === 'desktop-api-client') return;
  throw new RuntimeV2Error(
    `desktop_plugin_marketplace_${service}_authority_config_invalid`,
    `desktop plugin marketplace ${service} authority requires desktop-api-client strategy`,
  );
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
      'desktop_plugin_marketplace_runtime_config_invalid',
      'desktop plugin marketplace operation requires a complete runtime config',
    );
  }
  return Object.freeze(copy);
}

function generatedContractDigestV2(
  moduleRef: string,
  service: DesktopPluginMarketplaceAuthorityKindV2,
): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) => candidate.module_ref === moduleRef,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      `desktop_plugin_marketplace_${service}_catalog_missing`,
      `desktop plugin marketplace ${service} authority is absent from the generated catalog`,
    );
  }
  return entry.contract_digest;
}
