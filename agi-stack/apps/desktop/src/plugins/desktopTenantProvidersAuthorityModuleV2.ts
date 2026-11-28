import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopTenantProvidersHttpProjectionV2 } from './desktopTenantProvidersHttpProjectionV2';
import {
  PROVIDER_METHODS_V2,
  freezeProviderConfigV2,
  prepareProviderInputV2,
  requireProviderResultV2,
  providerErrorV2,
  providerRecordV2,
  type ProviderArgumentsV2,
  type ProviderInputV2,
  type ProviderMethodV2,
  type ProviderResultsV2,
  type DesktopTenantProvidersAuthorityV2,
} from './desktopTenantProvidersOperationContractV2';
export const DESKTOP_TENANT_PROVIDERS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/tenant-providers-authority';
export const DESKTOP_TENANT_PROVIDERS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.tenant-providers-authority';
export const DESKTOP_TENANT_PROVIDERS_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopTenantProvidersAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): DesktopTenantProvidersAuthorityV2;
}
export type DesktopTenantProvidersOperationsV2 = {
  readonly [K in ProviderMethodV2]: (input: ProviderInputV2<K>) => Promise<ProviderResultsV2[K]>;
};
export type DesktopTenantProvidersClientV2 = {
  readonly [K in ProviderMethodV2]: (
    ...args: [...ProviderArgumentsV2[K], signal?: AbortSignal]
  ) => Promise<ProviderResultsV2[K]>;
};
export function applyDesktopTenantProvidersAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_tenant_providers_authority_config_invalid',
      'invalid providers authority config',
    );
  context.provide(
    DESKTOP_TENANT_PROVIDERS_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopTenantProvidersHttpProjectionV2 }),
  );
}
export const desktopTenantProvidersAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_TENANT_PROVIDERS_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopTenantProvidersAuthorityV2,
});
export function createDesktopTenantProvidersOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopTenantProvidersOperationsV2 {
  const run = async <K extends ProviderMethodV2>(
    method: K,
    input: ProviderInputV2<K>,
  ): Promise<ProviderResultsV2[K]> => {
    const p = prepareProviderInputV2(method, input);
    const actions = resolve();
    if (!actions) throw providerErrorV2('desktop_renderer_generation_actions_unavailable', 503);
    const lease =
      await actions.acquireServiceOperationLease<DesktopTenantProvidersAuthorityServiceV2>({
        service: DESKTOP_TENANT_PROVIDERS_AUTHORITY_SERVICE_V2,
        version: DESKTOP_TENANT_PROVIDERS_AUTHORITY_VERSION_V2,
        scope: Object.freeze({ kind: 'tenant', tenant_id: p.scope.tenantId }),
      });
    if (lease.status !== 'accepted') throw providerErrorV2(lease.reasonCode, 503);
    let active = true;
    let failed = false;
    const check = () => {
      if (!active)
        throw new RuntimeV2Error(
          'tenant_provider_operation_released',
          'provider operation released',
        );
      if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    };
    try {
      return await lease.useService(async (candidate) => {
        check();
        if (
          !providerRecordV2(candidate) ||
          Object.keys(candidate).length !== 1 ||
          typeof candidate.bindOperation !== 'function'
        )
          throw providerErrorV2('tenant_provider_service_invalid', 502);
        const authority = candidate.bindOperation(p.config);
        if (
          !providerRecordV2(authority) ||
          Object.keys(authority).length !== 1 ||
          typeof authority.execute !== 'function'
        )
          throw providerErrorV2('tenant_provider_service_invalid', 502);
        check();
        const raw = await authority.execute(method, p);
        check();
        return requireProviderResultV2(method, raw, p);
      });
    } catch (error) {
      failed = true;
      throw error;
    } finally {
      active = false;
      try {
        await lease.release();
      } catch (error) {
        if (!failed) throw error;
      }
    }
  };
  return createProviderOperationsTableV2(run);
}
export function createProviderOperationsTableV2(
  run: <K extends ProviderMethodV2>(
    method: K,
    input: ProviderInputV2<K>,
  ) => Promise<ProviderResultsV2[K]>,
): DesktopTenantProvidersOperationsV2 {
  return Object.freeze(
    Object.fromEntries(
      PROVIDER_METHODS_V2.map((method) => [method, (input: ProviderInputV2) => run(method, input)]),
    ),
  ) as DesktopTenantProvidersOperationsV2;
}
export function createDesktopTenantProvidersClientV2(
  operations: DesktopTenantProvidersOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopTenantProvidersClientV2 {
  const runtime = freezeProviderConfigV2(config);
  const scope = Object.freeze({ authority: runtime.mode, tenantId: runtime.tenantId });
  const call = <K extends ProviderMethodV2>(
    method: K,
    args: ProviderArgumentsV2[K],
    signal?: AbortSignal,
  ) => operations[method]({ config: runtime, scope, args, signal });
  const client: DesktopTenantProvidersClientV2 = {
    listLlmProviders: (signal) => call('listLlmProviders', [], signal),
    getLlmProviderRoutingPolicy: (projectId, workspaceId, signal) =>
      call('getLlmProviderRoutingPolicy', [projectId, workspaceId], signal),
    updateLlmProviderRoutingPolicy: (input, signal) =>
      call('updateLlmProviderRoutingPolicy', [input], signal),
    createLlmProvider: (input, key, signal) => call('createLlmProvider', [input, key], signal),
    listLlmProviderTypes: (signal) => call('listLlmProviderTypes', [], signal),
    listLlmProviderModels: (type, signal) => call('listLlmProviderModels', [type], signal),
    discoverLlmProviderModels: (id, revision, signal) =>
      call('discoverLlmProviderModels', [id, revision], signal),
    getLlmProviderUsage: (id, signal) => call('getLlmProviderUsage', [id], signal),
    testLlmProviderDraft: (input, signal) => call('testLlmProviderDraft', [input], signal),
    updateLlmProvider: (id, input, signal) => call('updateLlmProvider', [id, input], signal),
    deleteLlmProvider: (id, revision, key, signal) =>
      call('deleteLlmProvider', [id, revision, key], signal),
    checkLlmProvider: (id, revision, signal) => call('checkLlmProvider', [id, revision], signal),
  };
  return Object.freeze(client);
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_TENANT_PROVIDERS_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_tenant_providers_authority_catalog_missing',
      'providers authority absent from catalog',
    );
  return entry.contract_digest;
}
