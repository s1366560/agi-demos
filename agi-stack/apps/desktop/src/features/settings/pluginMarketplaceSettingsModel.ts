import type { DesktopPluginMarketplaceCatalogOperationsV2 } from '../../plugins/desktopPluginMarketplaceAuthorityModulesV2';
import type { DesktopRuntimeConfig, ManagedPlugin, RuntimeMode } from '../../types';

export function pluginMarketplaceSettingsAvailable(mode: RuntimeMode): boolean {
  return mode === 'cloud';
}

export async function loadPluginMarketplaceSettings(
  config: DesktopRuntimeConfig,
  operations: DesktopPluginMarketplaceCatalogOperationsV2,
  signal?: AbortSignal,
): Promise<ManagedPlugin[]> {
  if (!pluginMarketplaceSettingsAvailable(config.mode)) return [];
  return operations.listMarketplacePlugins(config, signal);
}
