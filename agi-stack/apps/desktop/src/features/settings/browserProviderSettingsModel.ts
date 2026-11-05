import type { BrowserBridgeConfig, BrowserProviderInstance } from '../../types';

export function browserProviderOptions(
  config: Partial<BrowserBridgeConfig>,
  instances: BrowserProviderInstance[],
) {
  const options = new Map<string, { id: string; name: string; online: boolean }>([
    ['iab', { id: 'iab', name: 'iab', online: false }],
  ]);
  for (const endpoint of config.cdp_endpoints ?? []) {
    const id = `cdp:${endpoint.id}`;
    options.set(id, { id, name: endpoint.name, online: false });
  }
  for (const instance of instances) {
    const id =
      instance.metadata?.stableId ??
      (['iab', 'mcpapps'].includes(instance.id) ? instance.id : null);
    if (!id) continue;
    options.set(id, {
      id,
      name: instance.metadata?.name ?? options.get(id)?.name ?? id,
      online: true,
    });
  }
  const selected = config.default_browser_id ?? 'iab';
  if (!options.has(selected))
    options.set(selected, { id: selected, name: selected, online: false });
  return [...options.values()];
}

export function removeBrowserEndpoint<T extends Partial<BrowserBridgeConfig>>(
  config: T,
  id: string,
): T {
  return {
    ...config,
    cdp_endpoints: (config.cdp_endpoints ?? []).filter((endpoint) => endpoint.id !== id),
    default_browser_id:
      config.default_browser_id === `cdp:${id}` ? 'iab' : (config.default_browser_id ?? 'iab'),
  };
}
