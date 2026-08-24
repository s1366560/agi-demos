import { httpClient } from '@/services/client/httpClient';

import type {
  MarketplacePackageCatalogEntry,
  MarketplacePackageDetail,
  MarketplacePackageUninstallRequest,
  MarketplacePackageUninstallResponse,
} from '@/types/pluginMarketplace';

const BASE_URL = '/plugin-marketplace/packages';

interface PackageVisibilityOptions {
  includeRevoked?: boolean | undefined;
}

const visibilityParams = ({ includeRevoked = false }: PackageVisibilityOptions = {}) => ({
  include_revoked: includeRevoked,
});

export const pluginMarketplaceService = {
  listPackages(options: PackageVisibilityOptions = {}): Promise<MarketplacePackageCatalogEntry[]> {
    return httpClient.get<MarketplacePackageCatalogEntry[]>(BASE_URL, {
      params: visibilityParams(options),
    });
  },

  getPackage(
    pluginId: string,
    options: PackageVisibilityOptions = {}
  ): Promise<MarketplacePackageDetail> {
    return httpClient.get<MarketplacePackageDetail>(`${BASE_URL}/${encodeURIComponent(pluginId)}`, {
      params: visibilityParams(options),
    });
  },

  uninstallPackage(
    pluginId: string,
    request: MarketplacePackageUninstallRequest
  ): Promise<MarketplacePackageUninstallResponse> {
    return httpClient.post<MarketplacePackageUninstallResponse>(
      `${BASE_URL}/${encodeURIComponent(pluginId)}/uninstall`,
      request
    );
  },
};
