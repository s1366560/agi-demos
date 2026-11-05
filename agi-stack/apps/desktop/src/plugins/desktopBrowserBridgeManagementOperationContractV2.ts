import type {
  BrowserBridgeInstallResult,
  BrowserBridgeStatus,
  BrowserBridgeUninstallResult,
  BrowserProviderConfiguration,
  DesktopRuntimeConfig,
  LocalRuntimeStatus,
} from '../types';

export const BROWSER_BRIDGE_MANAGEMENT_METHODS_V2 = [
  'loadSnapshot',
  'setEnabled',
  'setFullCdpEnabled',
  'setProviders',
  'install',
  'uninstall',
] as const;
export type BrowserBridgeManagementMethodV2 = (typeof BROWSER_BRIDGE_MANAGEMENT_METHODS_V2)[number];
export type BrowserBridgeManagementRuntimeStatusV2 = {
  config: { browser_bridge?: import('../types').BrowserBridgeConfig };
};
export function projectBridgeRuntimeStatusV2(
  value: LocalRuntimeStatus,
): BrowserBridgeManagementRuntimeStatusV2 {
  const bridge = value.config.browser_bridge;
  return {
    config: bridge
      ? {
          browser_bridge: {
            enabled: bridge.enabled,
            port: bridge.port,
            extension_ids: [...bridge.extension_ids],
            ...providerFields(bridge),
            ...(bridge.full_cdp_access_enabled === undefined
              ? {}
              : { full_cdp_access_enabled: bridge.full_cdp_access_enabled }),
          },
        }
      : {},
  };
}
export type BrowserBridgeManagementResultsV2 = {
  loadSnapshot: {
    runtimeStatus: BrowserBridgeManagementRuntimeStatusV2;
    bridgeStatus: BrowserBridgeStatus;
  };
  setEnabled: BrowserBridgeManagementRuntimeStatusV2;
  setFullCdpEnabled: BrowserBridgeManagementRuntimeStatusV2;
  setProviders: BrowserBridgeManagementRuntimeStatusV2;
  install: BrowserBridgeInstallResult;
  uninstall: BrowserBridgeUninstallResult;
};
export type BrowserBridgeManagementInputV2 = {
  config: DesktopRuntimeConfig;
  enabled?: boolean;
  providers?: BrowserProviderConfiguration;
  signal?: AbortSignal;
};
export interface DesktopBrowserBridgeManagementAuthorityV2 {
  execute<K extends BrowserBridgeManagementMethodV2>(
    method: K,
    input: BrowserBridgeManagementInputV2,
  ): Promise<BrowserBridgeManagementResultsV2[K]>;
}
export function bridgeManagementCheckV2(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
}
export function bridgeManagementRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
export function bridgeManagementInvalidV2(): never {
  throw new Error('browser_bridge_management_contract_invalid');
}

function providerFields(
  value: Record<string, unknown> | import('../types').BrowserBridgeConfig,
): Partial<BrowserProviderConfiguration> {
  if (
    (value.default_browser_id !== undefined &&
      (typeof value.default_browser_id !== 'string' || !value.default_browser_id)) ||
    (value.cdp_endpoints !== undefined &&
      (!Array.isArray(value.cdp_endpoints) ||
        !value.cdp_endpoints.every(
          (row) =>
            bridgeManagementRecordV2(row) &&
            ['id', 'name', 'endpoint'].every((key) => typeof row[key] === 'string' && row[key]) &&
            typeof row.enabled === 'boolean',
        )))
  )
    bridgeManagementInvalidV2();
  return {
    ...(value.default_browser_id === undefined
      ? {}
      : { default_browser_id: value.default_browser_id as string }),
    ...(value.cdp_endpoints === undefined
      ? {}
      : {
          cdp_endpoints: (value.cdp_endpoints as BrowserProviderConfiguration['cdp_endpoints']).map(
            (row) => ({
              id: row.id,
              name: row.name,
              endpoint: row.endpoint,
              enabled: row.enabled,
            }),
          ),
        }),
  };
}
export function prepareBrowserBridgeManagementV2(
  method: BrowserBridgeManagementMethodV2,
  input: BrowserBridgeManagementInputV2,
): BrowserBridgeManagementInputV2 {
  bridgeManagementCheckV2(input.signal);
  if (
    !BROWSER_BRIDGE_MANAGEMENT_METHODS_V2.includes(method) ||
    !bridgeManagementRecordV2(input.config) ||
    !['cloud', 'local'].includes(input.config.mode) ||
    ((method === 'setEnabled' || method === 'setFullCdpEnabled') &&
      typeof input.enabled !== 'boolean')
  )
    bridgeManagementInvalidV2();
  let providers: BrowserProviderConfiguration | undefined;
  if (method === 'setProviders') {
    if (
      !bridgeManagementRecordV2(input.providers) ||
      Object.keys(input.providers).some(
        (key) => !['cdp_endpoints', 'default_browser_id'].includes(key),
      ) ||
      input.providers.cdp_endpoints === undefined ||
      input.providers.default_browser_id === undefined
    )
      bridgeManagementInvalidV2();
    providers = providerFields(input.providers) as BrowserProviderConfiguration;
    providers.cdp_endpoints.forEach(Object.freeze);
    Object.freeze(providers.cdp_endpoints);
    Object.freeze(providers);
  }
  return Object.freeze({
    ...input,
    ...(providers ? { providers } : {}),
    config: Object.freeze({ ...input.config }),
  });
}
const strings = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((x) => typeof x === 'string');
const number = (v: unknown) => typeof v === 'number' && Number.isFinite(v);
export function requireBridgeRuntimeStatusV2(value: unknown): LocalRuntimeStatus {
  if (
    !bridgeManagementRecordV2(value) ||
    typeof value.running !== 'boolean' ||
    !['api_base_url', 'api_token', 'workspace_root'].every((k) => typeof value[k] === 'string') ||
    !number(value.tool_count) ||
    !strings(value.tools) ||
    !Array.isArray(value.runtime_providers) ||
    !bridgeManagementRecordV2(value.config) ||
    typeof value.config.workspace_root !== 'string'
  )
    bridgeManagementInvalidV2();
  const bridge = value.config.browser_bridge;
  if (
    bridge !== undefined &&
    (!bridgeManagementRecordV2(bridge) ||
      typeof bridge.enabled !== 'boolean' ||
      !number(bridge.port) ||
      !strings(bridge.extension_ids) ||
      (bridge.full_cdp_access_enabled !== undefined &&
        typeof bridge.full_cdp_access_enabled !== 'boolean'))
  )
    bridgeManagementInvalidV2();
  if (bridgeManagementRecordV2(bridge)) providerFields(bridge);
  // Preserve the complete native config during read/modify/write, including kernel-owned fields.
  return structuredClone(value) as LocalRuntimeStatus;
}
export function requireBridgeStatusV2(value: unknown): BrowserBridgeStatus {
  if (
    !bridgeManagementRecordV2(value) ||
    typeof value.enabled !== 'boolean' ||
    typeof value.brokerConnected !== 'boolean' ||
    !number(value.port) ||
    !number(value.protocolMin) ||
    !number(value.protocolMax) ||
    typeof value.hostVersion !== 'string' ||
    typeof value.registryPath !== 'string' ||
    !strings(value.extensionIds) ||
    !Array.isArray(value.manifests) ||
    !['extensionId', 'extensionVersion'].every(
      (k) => value[k] === null || typeof value[k] === 'string',
    ) ||
    !value.manifests.every(
      (row) =>
        bridgeManagementRecordV2(row) &&
        ['browser', 'path', 'registrationLocation', 'reasonCode'].every(
          (k) => typeof row[k] === 'string',
        ) &&
        typeof row.present === 'boolean' &&
        ['missing', 'valid', 'owned_stale', 'collision', 'invalid'].includes(String(row.state)) &&
        Array.isArray(row.allowedActions) &&
        row.allowedActions.every((x) => ['install', 'repair', 'uninstall'].includes(x)),
    )
  )
    bridgeManagementInvalidV2();
  return {
    enabled: value.enabled,
    port: value.port,
    brokerConnected: value.brokerConnected,
    extensionId: value.extensionId,
    extensionVersion: value.extensionVersion,
    hostVersion: value.hostVersion,
    protocolMin: value.protocolMin,
    protocolMax: value.protocolMax,
    registryPath: value.registryPath,
    extensionIds: [...value.extensionIds],
    ...(value.browserInstances === undefined
      ? {}
      : { browserInstances: requireBrowserInstances(value.browserInstances) }),
    ...(value.cdpEndpoints === undefined
      ? {}
      : { cdpEndpoints: requireCdpStatuses(value.cdpEndpoints) }),
    manifests: value.manifests.map((row) => ({
      browser: row.browser,
      path: row.path,
      registrationLocation: row.registrationLocation,
      present: row.present,
      state: row.state,
      reasonCode: row.reasonCode,
      allowedActions: [...row.allowedActions],
      ...(typeof row.brokerDigest === 'string' ? { brokerDigest: row.brokerDigest } : {}),
      ...(typeof row.error === 'string' ? { error: row.error } : {}),
    })),
  } as BrowserBridgeStatus;
}

function requireCdpStatuses(value: unknown): NonNullable<BrowserBridgeStatus['cdpEndpoints']> {
  if (
    !Array.isArray(value) ||
    !value.every(
      (row) =>
        bridgeManagementRecordV2(row) &&
        typeof row.id === 'string' &&
        typeof row.name === 'string' &&
        ['disabled', 'connecting', 'connected', 'disconnected'].includes(String(row.status)) &&
        (row.error === null || typeof row.error === 'string'),
    )
  )
    bridgeManagementInvalidV2();
  return value.map((row) => ({
    id: row.id,
    name: row.name,
    status: row.status,
    error: row.error,
  })) as NonNullable<BrowserBridgeStatus['cdpEndpoints']>;
}

function requireBrowserInstances(value: unknown): import('../types').BrowserProviderInstance[] {
  if (
    !Array.isArray(value) ||
    !value.every((row) => {
      if (!bridgeManagementRecordV2(row) || typeof row.id !== 'string') return false;
      const metadata = row.metadata;
      return (
        metadata === undefined ||
        (bridgeManagementRecordV2(metadata) &&
          ['stableId', 'name'].every(
            (key) => metadata[key] === undefined || typeof metadata[key] === 'string',
          ))
      );
    })
  )
    bridgeManagementInvalidV2();
  return structuredClone(value) as import('../types').BrowserProviderInstance[];
}
export function requireBridgeRegistrationV2(
  method: 'install' | 'uninstall',
  value: unknown,
): BrowserBridgeInstallResult | BrowserBridgeUninstallResult {
  if (!bridgeManagementRecordV2(value)) bridgeManagementInvalidV2();
  if (method === 'uninstall') {
    if (!strings(value.removed)) bridgeManagementInvalidV2();
  } else if (
    !strings(value.skipped) ||
    !Array.isArray(value.installed) ||
    !value.installed.every(
      (row) =>
        bridgeManagementRecordV2(row) &&
        typeof row.browser === 'string' &&
        typeof row.manifestPath === 'string',
    )
  )
    bridgeManagementInvalidV2();
  return method === 'uninstall'
    ? { removed: [...(value.removed as string[])] }
    : {
        installed: (value.installed as BrowserBridgeInstallResult['installed']).map((row) => ({
          browser: row.browser,
          manifestPath: row.manifestPath,
        })),
        skipped: [...(value.skipped as string[])],
      };
}

export function requireBrowserBridgeManagementResultV2<K extends BrowserBridgeManagementMethodV2>(
  method: K,
  value: unknown,
): BrowserBridgeManagementResultsV2[K] {
  const runtime = (raw: unknown): BrowserBridgeManagementRuntimeStatusV2 => {
    if (!bridgeManagementRecordV2(raw) || !bridgeManagementRecordV2(raw.config))
      bridgeManagementInvalidV2();
    const b = raw.config.browser_bridge;
    if (b === undefined) return { config: {} };
    if (
      !bridgeManagementRecordV2(b) ||
      typeof b.enabled !== 'boolean' ||
      !number(b.port) ||
      !strings(b.extension_ids) ||
      (b.full_cdp_access_enabled !== undefined && typeof b.full_cdp_access_enabled !== 'boolean')
    )
      bridgeManagementInvalidV2();
    return {
      config: {
        browser_bridge: {
          enabled: b.enabled,
          port: b.port as number,
          extension_ids: [...b.extension_ids],
          ...providerFields(b),
          ...(b.full_cdp_access_enabled === undefined
            ? {}
            : {
                full_cdp_access_enabled: b.full_cdp_access_enabled as boolean,
              }),
        },
      },
    };
  };
  let result: unknown;
  if (method === 'loadSnapshot') {
    if (!bridgeManagementRecordV2(value)) bridgeManagementInvalidV2();
    result = {
      runtimeStatus: runtime(value.runtimeStatus),
      bridgeStatus: requireBridgeStatusV2(value.bridgeStatus),
    };
  } else if (method === 'setEnabled' || method === 'setFullCdpEnabled' || method === 'setProviders')
    result = runtime(value);
  else result = requireBridgeRegistrationV2(method, value);
  return result as BrowserBridgeManagementResultsV2[K];
}
