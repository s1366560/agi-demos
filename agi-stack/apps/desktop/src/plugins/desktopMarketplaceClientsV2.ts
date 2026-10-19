import type { MarketplaceClient } from '../../../../packages/plugin-marketplace-ui/src/client';
import type { LocalPluginClient } from '../api/localPluginClient';
import type { DesktopRuntimeConfig } from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import {
  requireDesktopMarketplaceGenerationActionsV2,
  withDesktopPluginMarketplaceCatalogOperationV2,
  withDesktopPluginMarketplaceManagementOperationV2,
  type DesktopPluginMarketplaceCatalogAuthorityV2,
  type DesktopPluginMarketplaceManagementAuthorityV2,
} from './desktopPluginMarketplaceAuthorityModulesV2';

type ResolveActions = () => DesktopRendererGenerationActionsV2 | null;

/** Resolve an active service for each invocation; never retain an authority past its lease. */
export function createDesktopMarketplaceClientV3(
  config: DesktopRuntimeConfig,
  resolveActions: ResolveActions,
): MarketplaceClient {
  const snapshot = Object.freeze({ ...config });
  const catalog = <T>(run: (authority: DesktopPluginMarketplaceCatalogAuthorityV2) => Promise<T>) =>
    withDesktopPluginMarketplaceCatalogOperationV2(
      requireDesktopMarketplaceGenerationActionsV2('catalog', resolveActions()),
      snapshot,
      run,
    );
  const management = <T>(
    run: (authority: DesktopPluginMarketplaceManagementAuthorityV2) => Promise<T>,
  ) =>
    withDesktopPluginMarketplaceManagementOperationV2(
      requireDesktopMarketplaceGenerationActionsV2('management', resolveActions()),
      snapshot,
      run,
    );
  return Object.freeze({
    catalog: (...args) => catalog((authority) => authority.marketplaceV3.catalog(...args)),
    sources: (...args) => catalog((authority) => authority.marketplaceV3.sources(...args)),
    installations: (...args) =>
      catalog((authority) => authority.marketplaceV3.installations(...args)),
    oauthStatus: (...args) => catalog((authority) => authority.marketplaceV3.oauthStatus(...args)),
    cache: (...args) => catalog((authority) => authority.marketplaceV3.cache(...args)),
    addSource: (...args) => management((authority) => authority.marketplaceV3.addSource(...args)),
    removeSource: (...args) =>
      management((authority) => authority.marketplaceV3.removeSource(...args)),
    preflight: (...args) => management((authority) => authority.marketplaceV3.preflight(...args)),
    install: (...args) => management((authority) => authority.marketplaceV3.install(...args)),
    action: (...args) => management((authority) => authority.marketplaceV3.action(...args)),
    oauthAction: (...args) =>
      management((authority) => authority.marketplaceV3.oauthAction(...args)),
    cleanupCache: (...args) =>
      management((authority) => authority.marketplaceV3.cleanupCache(...args)),
  } satisfies MarketplaceClient);
}

export function createDesktopLocalPluginClientV2(
  config: DesktopRuntimeConfig,
  resolveActions: ResolveActions,
): LocalPluginClient {
  const snapshot = Object.freeze({ ...config });
  const management = <T>(
    run: (authority: DesktopPluginMarketplaceManagementAuthorityV2) => Promise<T>,
  ) =>
    withDesktopPluginMarketplaceManagementOperationV2(
      requireDesktopMarketplaceGenerationActionsV2('management', resolveActions()),
      snapshot,
      run,
    );
  return Object.freeze({
    list: (...args) =>
      withDesktopPluginMarketplaceCatalogOperationV2(
        requireDesktopMarketplaceGenerationActionsV2('catalog', resolveActions()),
        snapshot,
        (authority) => authority.localPlugins.list(...args),
      ),
    inspect: (...args) => management((authority) => authority.localPlugins.inspect(...args)),
    install: (...args) => management((authority) => authority.localPlugins.install(...args)),
    control: (...args) => management((authority) => authority.localPlugins.control(...args)),
  } satisfies LocalPluginClient);
}
