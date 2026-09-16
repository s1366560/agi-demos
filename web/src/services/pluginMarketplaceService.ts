import { httpClient } from '@/services/client/httpClient';

import type {
  MarketplacePackageApprovalResponse,
  MarketplacePackageApproveRequest,
  MarketplacePackageCatalogEntry,
  MarketplacePackageDetail,
  MarketplacePackageInstallRequest,
  MarketplacePackageInstallResponse,
  MarketplacePackageRevocationResponse,
  MarketplacePackageRevokeRequest,
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

  installPackage(
    pluginId: string,
    request: MarketplacePackageInstallRequest
  ): Promise<MarketplacePackageInstallResponse> {
    return httpClient.post<MarketplacePackageInstallResponse>(
      `${BASE_URL}/${encodeURIComponent(pluginId)}/install`,
      request
    );
  },

  approvePackage(
    pluginId: string,
    request: MarketplacePackageApproveRequest
  ): Promise<MarketplacePackageApprovalResponse> {
    return httpClient.post<MarketplacePackageApprovalResponse>(
      `${BASE_URL}/${encodeURIComponent(pluginId)}/approve`,
      request
    );
  },

  revokePackage(
    pluginId: string,
    request: MarketplacePackageRevokeRequest
  ): Promise<MarketplacePackageRevocationResponse> {
    return httpClient.post<MarketplacePackageRevocationResponse>(
      `${BASE_URL}/${encodeURIComponent(pluginId)}/revoke`,
      request
    );
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
