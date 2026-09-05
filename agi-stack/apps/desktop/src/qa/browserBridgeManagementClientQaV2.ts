import type { DesktopBrowserBridgeManagementClientV2 } from '../plugins/desktopBrowserBridgeManagementAuthorityModuleV2';
import type { BrowserBridgeManagementRuntimeStatusV2 } from '../plugins/desktopBrowserBridgeManagementOperationContractV2';
import type { BrowserBridgeStatus } from '../types';

/** Explicit display fixture; it neither installs native hosts nor proves native authority. */
export function createBrowserBridgeManagementClientQaV2(): DesktopBrowserBridgeManagementClientV2 {
  const runtimeStatus: BrowserBridgeManagementRuntimeStatusV2 = {
    config: {
      browser_bridge: { enabled: false, port: 0, extension_ids: [], full_cdp_access_enabled: false },
    },
  };
  const bridgeStatus: BrowserBridgeStatus = {
    enabled: false,
    port: 0,
    brokerConnected: false,
    extensionId: null,
    extensionVersion: null,
    hostVersion: 'qa-fixture',
    protocolMin: 1,
    protocolMax: 1,
    manifests: [],
    registryPath: '',
    extensionIds: [],
  };
  return {
    async loadSnapshot(signal) {
      signal?.throwIfAborted();
      return structuredClone({ runtimeStatus, bridgeStatus });
    },
    async setEnabled(enabled, signal) {
      signal?.throwIfAborted();
      runtimeStatus.config.browser_bridge!.enabled = enabled;
      bridgeStatus.enabled = enabled;
      return structuredClone(runtimeStatus);
    },
    async setFullCdpEnabled(enabled, signal) {
      signal?.throwIfAborted();
      runtimeStatus.config.browser_bridge!.full_cdp_access_enabled = enabled;
      return structuredClone(runtimeStatus);
    },
    async install(signal) {
      signal?.throwIfAborted();
      return { installed: [], skipped: ['qa-fixture'] };
    },
    async uninstall(signal) {
      signal?.throwIfAborted();
      return { removed: [] };
    },
  };
}
