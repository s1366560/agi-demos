import type { MarketplaceClient } from '../../../../packages/plugin-marketplace-ui/src/client';
import type { LocalPluginClient } from '../api/localPluginClient';

export type DesktopMarketplaceCatalogV3 = Pick<
  MarketplaceClient,
  'catalog' | 'sources' | 'installations' | 'oauthStatus' | 'cache'
>;
export type DesktopMarketplaceManagementV3 = Omit<
  MarketplaceClient,
  keyof DesktopMarketplaceCatalogV3
>;
export type DesktopLocalPluginCatalogV2 = Pick<LocalPluginClient, 'list'>;
export type DesktopLocalPluginManagementV2 = Omit<LocalPluginClient, 'list'>;

/** Every nested method keeps the same lifetime as its operation authority. */
export function guardMarketplaceCatalogV3(
  client: DesktopMarketplaceCatalogV3,
  assertActive: () => void,
): DesktopMarketplaceCatalogV3 {
  return Object.freeze({
    catalog: (...args) => {
      assertActive();
      return client.catalog(...args);
    },
    sources: (...args) => {
      assertActive();
      return client.sources(...args);
    },
    installations: (...args) => {
      assertActive();
      return client.installations(...args);
    },
    oauthStatus: (...args) => {
      assertActive();
      return client.oauthStatus(...args);
    },
    cache: (...args) => {
      assertActive();
      return client.cache(...args);
    },
  } satisfies DesktopMarketplaceCatalogV3);
}

export function guardMarketplaceManagementV3(
  client: DesktopMarketplaceManagementV3,
  assertActive: () => void,
): DesktopMarketplaceManagementV3 {
  return Object.freeze({
    addSource: (...args) => {
      assertActive();
      return client.addSource(...args);
    },
    removeSource: (...args) => {
      assertActive();
      return client.removeSource(...args);
    },
    preflight: (...args) => {
      assertActive();
      return client.preflight(...args);
    },
    install: (...args) => {
      assertActive();
      return client.install(...args);
    },
    action: (...args) => {
      assertActive();
      return client.action(...args);
    },
    oauthAction: (...args) => {
      assertActive();
      return client.oauthAction(...args);
    },
    cleanupCache: (...args) => {
      assertActive();
      return client.cleanupCache(...args);
    },
  } satisfies DesktopMarketplaceManagementV3);
}

export function guardLocalPluginCatalogV2(
  client: DesktopLocalPluginCatalogV2,
  assertActive: () => void,
): DesktopLocalPluginCatalogV2 {
  return Object.freeze({
    list: (...args) => {
      assertActive();
      return client.list(...args);
    },
  } satisfies DesktopLocalPluginCatalogV2);
}

export function guardLocalPluginManagementV2(
  client: DesktopLocalPluginManagementV2,
  assertActive: () => void,
): DesktopLocalPluginManagementV2 {
  return Object.freeze({
    inspect: (...args) => {
      assertActive();
      return client.inspect(...args);
    },
    install: (...args) => {
      assertActive();
      return client.install(...args);
    },
    control: (...args) => {
      assertActive();
      return client.control(...args);
    },
  } satisfies DesktopLocalPluginManagementV2);
}
