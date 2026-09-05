import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import { createDesktopBrowserBridgeManagementNativeProjectionV2 } from './desktopBrowserBridgeManagementNativeProjectionV2';
import {
  BROWSER_BRIDGE_MANAGEMENT_METHODS_V2,
  requireBrowserBridgeManagementResultV2,
  bridgeManagementCheckV2,
  bridgeManagementRecordV2,
  prepareBrowserBridgeManagementV2,
  type BrowserBridgeManagementInputV2,
  type BrowserBridgeManagementMethodV2,
  type BrowserBridgeManagementResultsV2,
  type DesktopBrowserBridgeManagementAuthorityV2,
} from './desktopBrowserBridgeManagementOperationContractV2';
export const DESKTOP_BROWSER_BRIDGE_MANAGEMENT_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/browser-bridge-management-authority';
export const DESKTOP_BROWSER_BRIDGE_MANAGEMENT_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.browser-bridge-management-authority';
export interface DesktopBrowserBridgeManagementAuthorityServiceV2 {
  bindOperation(config: DesktopRuntimeConfig): DesktopBrowserBridgeManagementAuthorityV2;
}
export type DesktopBrowserBridgeManagementOperationsV2 = {
  readonly [K in BrowserBridgeManagementMethodV2]: (
    input: BrowserBridgeManagementInputV2,
  ) => Promise<BrowserBridgeManagementResultsV2[K]>;
};
export interface DesktopBrowserBridgeManagementClientV2 {
  loadSnapshot(signal?: AbortSignal): Promise<BrowserBridgeManagementResultsV2['loadSnapshot']>;
  setEnabled(
    enabled: boolean,
    signal?: AbortSignal,
  ): Promise<BrowserBridgeManagementResultsV2['setEnabled']>;
  setFullCdpEnabled(
    enabled: boolean,
    signal?: AbortSignal,
  ): Promise<BrowserBridgeManagementResultsV2['setFullCdpEnabled']>;
  install(signal?: AbortSignal): Promise<BrowserBridgeManagementResultsV2['install']>;
  uninstall(signal?: AbortSignal): Promise<BrowserBridgeManagementResultsV2['uninstall']>;
}
export function applyDesktopBrowserBridgeManagementAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'native-browser-bridge')
    throw new RuntimeV2Error(
      'browser_bridge_management_config_invalid',
      'Invalid bridge management config',
    );
  context.provide(
    DESKTOP_BROWSER_BRIDGE_MANAGEMENT_AUTHORITY_SERVICE_V2,
    Object.freeze({ bindOperation: createDesktopBrowserBridgeManagementNativeProjectionV2 }),
  );
}
export const desktopBrowserBridgeManagementAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_BROWSER_BRIDGE_MANAGEMENT_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedDigest(),
    apply: applyDesktopBrowserBridgeManagementAuthorityV2,
  });
export function createDesktopBrowserBridgeManagementOperationsV2(
  resolve: () => DesktopRendererGenerationActionsV2 | null,
): DesktopBrowserBridgeManagementOperationsV2 {
  const run = async <K extends BrowserBridgeManagementMethodV2>(
    method: K,
    input: BrowserBridgeManagementInputV2,
  ): Promise<BrowserBridgeManagementResultsV2[K]> => {
    const prepared = prepareBrowserBridgeManagementV2(method, input);
    const actions = resolve();
    if (!actions) throw new Error('desktop_renderer_generation_actions_unavailable');
    const lease =
      await actions.acquireServiceOperationLease<DesktopBrowserBridgeManagementAuthorityServiceV2>({
        service: DESKTOP_BROWSER_BRIDGE_MANAGEMENT_AUTHORITY_SERVICE_V2,
        version: '1.0.0',
        scope: Object.freeze({ kind: 'root' }),
      });
    if (lease.status !== 'accepted') throw new Error(lease.reasonCode);
    let active = true;
    let failed = false;
    const check = () => {
      if (!active) throw new Error('browser_bridge_management_operation_released');
      bridgeManagementCheckV2(prepared.signal);
    };
    try {
      return await lease.useService(async (candidate) => {
        check();
        if (!bridgeManagementRecordV2(candidate) || typeof candidate.bindOperation !== 'function')
          throw new Error('browser_bridge_management_service_invalid');
        const authority = candidate.bindOperation(prepared.config);
        if (!bridgeManagementRecordV2(authority) || typeof authority.execute !== 'function')
          throw new Error('browser_bridge_management_service_invalid');
        check();
        const result = await authority.execute(method, prepared);
        check();
        return requireBrowserBridgeManagementResultV2(method, result);
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
  return Object.freeze(
    Object.fromEntries(
      BROWSER_BRIDGE_MANAGEMENT_METHODS_V2.map((method) => [
        method,
        (input: BrowserBridgeManagementInputV2) => run(method, input),
      ]),
    ),
  ) as DesktopBrowserBridgeManagementOperationsV2;
}
export function createDesktopBrowserBridgeManagementClientV2(
  operations: DesktopBrowserBridgeManagementOperationsV2,
  config: DesktopRuntimeConfig,
): DesktopBrowserBridgeManagementClientV2 {
  const frozen = Object.freeze({ ...config });
  const client: DesktopBrowserBridgeManagementClientV2 = {
    loadSnapshot: (signal) => operations.loadSnapshot({ config: frozen, signal }),
    setEnabled: (enabled, signal) => operations.setEnabled({ config: frozen, enabled, signal }),
    setFullCdpEnabled: (enabled, signal) =>
      operations.setFullCdpEnabled({ config: frozen, enabled, signal }),
    install: (signal) => operations.install({ config: frozen, signal }),
    uninstall: (signal) => operations.uninstall({ config: frozen, signal }),
  };
  return Object.freeze(client);
}
function generatedDigest(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_BROWSER_BRIDGE_MANAGEMENT_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry)
    throw new RuntimeV2Error(
      'browser_bridge_management_catalog_missing',
      'Bridge management missing from catalog',
    );
  return entry.contract_digest;
}
