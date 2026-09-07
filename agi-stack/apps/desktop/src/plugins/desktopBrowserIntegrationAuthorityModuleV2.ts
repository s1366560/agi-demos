import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopBrowserIntegrationHttpProjectionV2 } from './desktopBrowserIntegrationHttpProjectionV2';
import {
  BROWSER_INTEGRATION_METHODS_V2,
  freezeBrowserIntegrationConfigV2,
  prepareBrowserIntegrationInputV2,
  browserIntegrationErrorV2,
  browserIntegrationRecordV2,
  type BrowserIntegrationArgumentsV2,
  type BrowserIntegrationInputV2,
  type BrowserIntegrationMethodV2,
  type BrowserIntegrationResultsV2,
  type DesktopBrowserIntegrationAuthorityV2,
} from './desktopBrowserIntegrationOperationContractV2';
import { requireBrowserIntegrationResultV2 } from './desktopBrowserIntegrationResponseContractV2';
export const DESKTOP_BROWSER_INTEGRATION_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/browser-integration-authority';
export const DESKTOP_BROWSER_INTEGRATION_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.browser-integration-authority';
export const DESKTOP_BROWSER_INTEGRATION_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopBrowserIntegrationAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): DesktopBrowserIntegrationAuthorityV2;
}
export type DesktopBrowserIntegrationOperationsV2 = {
  readonly [K in BrowserIntegrationMethodV2]: (
    input: BrowserIntegrationInputV2<K>,
  ) => Promise<BrowserIntegrationResultsV2[K]>;
};
export type DesktopBrowserIntegrationClientV2 = {
  readonly [K in BrowserIntegrationMethodV2]: (
    ...args: [...BrowserIntegrationArgumentsV2[K], signal?: AbortSignal]
  ) => Promise<BrowserIntegrationResultsV2[K]>;
};
export function applyDesktopBrowserIntegrationAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-api-fetch')
    throw new RuntimeV2Error(
      'desktop_browser_integration_authority_config_invalid',
      'invalid Browser integration authority config',
    );
  context.provide(
    DESKTOP_BROWSER_INTEGRATION_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopBrowserIntegrationHttpProjectionV2 }),
  );
}
export const desktopBrowserIntegrationAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_BROWSER_INTEGRATION_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigest(),
  apply: applyDesktopBrowserIntegrationAuthorityV2,
});
export function createDesktopBrowserIntegrationOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopBrowserIntegrationOperationsV2 {
  const run = async <K extends BrowserIntegrationMethodV2>(
    method: K,
    input: BrowserIntegrationInputV2<K>,
  ): Promise<BrowserIntegrationResultsV2[K]> => {
    const p = prepareBrowserIntegrationInputV2(method, input);
    const actions = resolve();
    if (!actions)
      throw browserIntegrationErrorV2('desktop_renderer_generation_actions_unavailable', 503);
    const lease =
      await actions.acquireServiceOperationLease<DesktopBrowserIntegrationAuthorityServiceV2>({
        service: DESKTOP_BROWSER_INTEGRATION_AUTHORITY_SERVICE_V2,
        version: DESKTOP_BROWSER_INTEGRATION_AUTHORITY_VERSION_V2,
        scope: Object.freeze({ kind: 'root' }),
      });
    if (lease.status !== 'accepted') throw browserIntegrationErrorV2(lease.reasonCode, 503);
    let active = true;
    let failed = false;
    const check = () => {
      if (!active)
        throw new RuntimeV2Error(
          'browser_integration_operation_released',
          'Browser integration operation released',
        );
      if (p.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    };
    try {
      return await lease.useService(async (candidate) => {
        check();
        if (
          !browserIntegrationRecordV2(candidate) ||
          Object.keys(candidate).length !== 1 ||
          typeof candidate.bindOperation !== 'function'
        )
          throw browserIntegrationErrorV2('browser_integration_service_invalid', 502);
        const authority = candidate.bindOperation(p.config);
        if (
          !browserIntegrationRecordV2(authority) ||
          Object.keys(authority).length !== 1 ||
          typeof authority.execute !== 'function'
        )
          throw browserIntegrationErrorV2('browser_integration_service_invalid', 502);
        check();
        const raw = await authority.execute(method, p);
        check();
        return requireBrowserIntegrationResultV2(method, raw, p);
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
  return createBrowserIntegrationOperationsTableV2(run);
}
export function createBrowserIntegrationOperationsTableV2(
  run: <K extends BrowserIntegrationMethodV2>(
    method: K,
    input: BrowserIntegrationInputV2<K>,
  ) => Promise<BrowserIntegrationResultsV2[K]>,
): DesktopBrowserIntegrationOperationsV2 {
  return Object.freeze(
    Object.fromEntries(
      BROWSER_INTEGRATION_METHODS_V2.map((method) => [
        method,
        (input: BrowserIntegrationInputV2) => run(method, input),
      ]),
    ),
  ) as DesktopBrowserIntegrationOperationsV2;
}
export function createDesktopBrowserIntegrationClientV2(
  operations: DesktopBrowserIntegrationOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopBrowserIntegrationClientV2 {
  const runtime = freezeBrowserIntegrationConfigV2(config);
  const scope = Object.freeze({ authority: runtime.mode });
  const call = <K extends BrowserIntegrationMethodV2>(
    method: K,
    args: BrowserIntegrationArgumentsV2[K],
    signal?: AbortSignal,
  ) => operations[method]({ config: runtime, scope, args, signal });
  const client: DesktopBrowserIntegrationClientV2 = {
    listBrowserOriginGrants: (signal) => call('listBrowserOriginGrants', [], signal),
    revokeBrowserOriginGrant: (id, signal) => call('revokeBrowserOriginGrant', [id], signal),
    listBrowserCapabilityGrants: (signal) => call('listBrowserCapabilityGrants', [], signal),
    revokeBrowserCapabilityGrant: (id, signal) =>
      call('revokeBrowserCapabilityGrant', [id], signal),
    listBrowserSiteCredentials: (signal) => call('listBrowserSiteCredentials', [], signal),
    upsertBrowserSiteCredential: (input, signal) =>
      call('upsertBrowserSiteCredential', [input], signal),
    deleteBrowserSiteCredential: (id, signal) => call('deleteBrowserSiteCredential', [id], signal),
    listBrowserAuditEntries: (options = {}, signal) =>
      call('listBrowserAuditEntries', [options], signal),
  };
  return Object.freeze(client);
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_BROWSER_INTEGRATION_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'desktop_browser_integration_authority_catalog_missing',
      'Browser integration authority absent from catalog',
    );
  return entry.contract_digest;
}
