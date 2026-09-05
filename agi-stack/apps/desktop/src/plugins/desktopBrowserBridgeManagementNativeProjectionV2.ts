import type { DesktopRuntimeConfig } from '../types';
import {
  bridgeManagementCheckV2,
  projectBridgeRuntimeStatusV2,
  requireBridgeRegistrationV2,
  requireBridgeRuntimeStatusV2,
  requireBridgeStatusV2,
  type BrowserBridgeManagementInputV2,
  type BrowserBridgeManagementMethodV2,
  type BrowserBridgeManagementResultsV2,
  type DesktopBrowserBridgeManagementAuthorityV2,
} from './desktopBrowserBridgeManagementOperationContractV2';

// Application-global kernel config: serialize writes across clients and pinned generations.
let configurationTail: Promise<void> = Promise.resolve();
function serializeConfigurationV2<T>(work: () => Promise<T>): Promise<T> {
  const result = configurationTail.then(work);
  configurationTail = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}
export function createDesktopBrowserBridgeManagementNativeProjectionV2(
  _config: DesktopRuntimeConfig,
): DesktopBrowserBridgeManagementAuthorityV2 {
  const authority: DesktopBrowserBridgeManagementAuthorityV2 = {
    async execute<K extends BrowserBridgeManagementMethodV2>(
      method: K,
      input: BrowserBridgeManagementInputV2,
    ): Promise<BrowserBridgeManagementResultsV2[K]> {
      bridgeManagementCheckV2(input.signal);
      const desktop = typeof window === 'undefined' ? undefined : window.__MEMSTACK_DESKTOP__;
      if (desktop?.runtime !== 'electron' || typeof desktop.core?.invoke !== 'function')
        throw new Error('browser_bridge_management_native_unavailable');
      const invoke = desktop.core.invoke.bind(desktop.core);
      // Never race IPC against abort: accepted native effects must settle before the lease releases.
      const call = async (command: string, args?: Record<string, unknown>): Promise<unknown> => {
        bridgeManagementCheckV2(input.signal);
        const result = await invoke(command, args);
        bridgeManagementCheckV2(input.signal);
        return result;
      };
      let result: unknown;
      if (method === 'loadSnapshot') {
        const runtimeStatus = requireBridgeRuntimeStatusV2(await call('local_runtime_status'));
        const bridgeStatus = requireBridgeStatusV2(await call('browser_bridge_status'));
        result = { runtimeStatus: projectBridgeRuntimeStatusV2(runtimeStatus), bridgeStatus };
      } else if (method === 'setEnabled' || method === 'setFullCdpEnabled') {
        result = await serializeConfigurationV2(async () => {
          const current = requireBridgeRuntimeStatusV2(await call('local_runtime_status'));
          const field = method === 'setEnabled' ? 'enabled' : 'full_cdp_access_enabled';
          const config = {
            ...current.config,
            browser_bridge: {
              ...current.config.browser_bridge,
              [field]: input.enabled,
            },
          };
          return projectBridgeRuntimeStatusV2(
            requireBridgeRuntimeStatusV2(await call('local_runtime_configure', { config })),
          );
        });
      } else {
        result = await serializeConfigurationV2(async () =>
          requireBridgeRegistrationV2(
            method,
            await call(
              method === 'install' ? 'browser_bridge_install' : 'browser_bridge_uninstall',
            ),
          ),
        );
      }
      return result as BrowserBridgeManagementResultsV2[K];
    },
  };
  return Object.freeze(authority);
}
