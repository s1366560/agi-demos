export interface PluginDescriptor {
  id: string;
  name: string;
  description: string;
  version: string;
  publisher: string;
  source_id: string;
  format: 'codex' | 'v2';
  install_strategy?: 'signed-v2';
  category: string;
  capabilities: string[];
  targets: string[];
  permissions: string[];
  compatible: boolean;
  reasons: string[];
  readme?: string;
  changelog?: string;
}
export interface MarketplaceSource {
  id: string;
  name: string;
  kind: 'https' | 'git' | 'local';
  location: string;
  trusted: boolean;
}
export interface MarketplaceInstallation {
  install_strategy?: 'signed-v2';
  id: string;
  plugin_id: string;
  source_id: string;
  name: string;
  version: string;
  status:
    | 'downloaded'
    | 'needs_configuration'
    | 'enabled'
    | 'disabled'
    | 'failed'
    | 'uninstalled';
  capabilities: string[];
  error?: string;
  job_id?: string;
  required_credentials?: string[];
  oauth_services?: Array<MarketplaceOAuthStatus & { name: string }>;
}
export interface MarketplaceOAuthStatus {
  status: 'not_connected' | 'needs_configuration' | 'authorizing' | 'connected' | 'expired' | 'error';
  authorization_url?: string;
  expires_at?: string | number;
  reason?: string;
}
export interface MarketplaceCache {
  total_bytes: number;
  reclaimable_bytes: number;
  entries: number;
  removed_bytes?: number;
  removed_entries?: number;
}
export interface MarketplacePreflight {
  id: string;
  plugin: PluginDescriptor;
  permissions: string[];
  compatible: boolean;
  reasons: string[];
  digest: string;
}
export interface MarketplaceScope {
  tenant_id: string;
  project_id?: string;
}
export type MarketplaceAction =
  | 'enable'
  | 'disable'
  | 'update'
  | 'uninstall'
  | 'configure'
  | 'verify';
export type MarketplaceTransport = <T>(
  path: string,
  options: {
    method?: 'GET' | 'POST' | 'DELETE';
    body?: unknown;
    signal?: AbortSignal;
  },
) => Promise<T>;
const ROOT = '/api/v1/plugin-marketplace/v3';

export function createMarketplaceClient(
  transport: MarketplaceTransport,
  scope: MarketplaceScope,
  scopedCatalog = false,
) {
  const query = new URLSearchParams({ ...scope });
  return {
    oauthStatus: (id: string, server: string, signal?: AbortSignal) =>
      transport<MarketplaceOAuthStatus>(`${ROOT}/installations/${encodeURIComponent(id)}/oauth/${encodeURIComponent(server)}/status?${query}`, { ...(signal ? { signal } : {}) }),
    oauthAction: (id: string, server: string, action: 'start' | 'cancel' | 'disconnect', configuration: { client_id?: string; client_metadata_url?: string } = {}, key = crypto.randomUUID()) =>
      transport<MarketplaceOAuthStatus>(`${ROOT}/installations/${encodeURIComponent(id)}/oauth/${encodeURIComponent(server)}/${action}`, { method: 'POST', body: { ...configuration, ...scope, idempotency_key: key } }),
    cache: (signal?: AbortSignal) => transport<MarketplaceCache>(`${ROOT}/cache?${query}`, { ...(signal ? { signal } : {}) }),
    cleanupCache: (key = crypto.randomUUID()) => transport<MarketplaceCache>(`${ROOT}/cache/cleanup`, { method: 'POST', body: { ...scope, idempotency_key: key } }),
    catalog: (signal?: AbortSignal) =>
      transport<{
        items: PluginDescriptor[];
        errors?: Array<{ source_id: string; error: string }>;
      }>(`${ROOT}/catalog${scopedCatalog ? '/scoped' : ''}?${query}`, {
        ...(signal ? { signal } : {}),
      }),
    sources: (signal?: AbortSignal) =>
      transport<{ items: MarketplaceSource[] }>(`${ROOT}/sources?${query}`, {
        ...(signal ? { signal } : {}),
      }),
    installations: (signal?: AbortSignal) =>
      transport<{ items: MarketplaceInstallation[] }>(
        `${ROOT}/installations?${query}`,
        { ...(signal ? { signal } : {}) },
      ),
    addSource: (source: Omit<MarketplaceSource, 'id'>) =>
      transport<MarketplaceSource>(`${ROOT}/sources`, {
        method: 'POST',
        body: { ...source, ...scope },
      }),
    removeSource: (id: string) =>
      transport<unknown>(`${ROOT}/sources/${encodeURIComponent(id)}?${query}`, {
        method: 'DELETE',
      }),
    preflight: (plugin: PluginDescriptor) =>
      transport<MarketplacePreflight>(`${ROOT}/preflight`, {
        method: 'POST',
        body: {
          ...scope,
          plugin_id: plugin.id,
          source_id: plugin.source_id,
          version: plugin.version,
        },
      }),
    install: (preflight: MarketplacePreflight, idempotencyKey: string) =>
      transport<MarketplaceInstallation>(`${ROOT}/installations`, {
        method: 'POST',
        body: {
          ...scope,
          preflight_id: preflight.id,
          approved_permissions: preflight.permissions,
          idempotency_key: idempotencyKey,
        },
      }),
    action: (
      installation: MarketplaceInstallation,
      action: MarketplaceAction,
      payload: Record<string, unknown> = {},
      idempotencyKey: string = crypto.randomUUID(),
    ) =>
      transport<MarketplaceInstallation>(
        `${ROOT}/installations/${encodeURIComponent(installation.id)}/${action}`,
        {
          method: 'POST',
          body: { ...payload, ...scope, idempotency_key: idempotencyKey },
        },
      ),
  };
}
export type MarketplaceClient = ReturnType<typeof createMarketplaceClient>;

export function filterPlugins(
  items: PluginDescriptor[],
  filters: {
    query: string;
    category: string;
    capability: string;
    target: string;
    source: string;
  },
) {
  const query = filters.query.trim().toLocaleLowerCase();
  return items.filter(
    (plugin) =>
      (!query ||
        `${plugin.name} ${plugin.description}`
          .toLocaleLowerCase()
          .includes(query)) &&
      (!filters.category || plugin.category === filters.category) &&
      (!filters.capability ||
        plugin.capabilities.includes(filters.capability)) &&
      (!filters.target || plugin.targets.includes(filters.target)) &&
      (!filters.source || plugin.source_id === filters.source),
  );
}
