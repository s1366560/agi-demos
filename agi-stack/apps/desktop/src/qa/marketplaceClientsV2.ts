import type { MarketplaceClient } from '../../../../packages/plugin-marketplace-ui/src/client';
import { createLocalPluginClient } from '../api/localPluginClient';
import type { DesktopPluginMarketplaceOperationsV2 } from '../plugins/desktopPluginMarketplaceAuthorityModulesV2';

const unavailable = async (): Promise<never> => {
  throw new Error('qa_marketplace_operation_unavailable');
};

/** Isolated settings fixtures expose no host transport or installation authority. */
export const qaMarketplaceClientsV2: Pick<
  DesktopPluginMarketplaceOperationsV2,
  'marketplaceClient' | 'localPluginClient' | 'instanceClient'
> = Object.freeze({
  instanceClient: () => ({ list: unavailable, apply: unavailable }),
  marketplaceClient: (): MarketplaceClient =>
    Object.freeze({
      catalog: async () => ({ items: [] }),
      sources: async () => ({ items: [] }),
      installations: async () => ({ items: [] }),
      oauthStatus: async () => ({ status: 'not_connected' as const }),
      cache: async () => ({ total_bytes: 0, reclaimable_bytes: 0, entries: 0 }),
      oauthAction: unavailable,
      cleanupCache: unavailable,
      addSource: unavailable,
      removeSource: unavailable,
      preflight: unavailable,
      install: unavailable,
      action: unavailable,
    }),
  localPluginClient: (config) => createLocalPluginClient(config, unavailable),
});
