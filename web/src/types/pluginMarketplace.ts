export interface MarketplacePackageCatalogEntry {
  plugin_id: string;
  version: string;
  publisher: string;
  artifact_digest: string;
  artifact_registry: string;
  artifact_repository: string;
  oci_manifest_digest: string;
  install_status: string;
  manifest: Record<string, unknown>;
  signature: Record<string, unknown>;
  provenance: Record<string, unknown>;
  security_scan_status: string;
  revoked: boolean;
  revocation_reason?: string | null | undefined;
}

export interface MarketplacePackageDetail {
  plugin_id: string;
  versions: MarketplacePackageCatalogEntry[];
}

export interface MarketplacePackageUninstallRequest {
  version: string;
  tenant_id: string;
}

export interface MarketplacePackageUninstallResponse {
  plugin_id: string;
  version: string;
  status: 'uninstalled';
  desired_removed: boolean;
  revoked_permissions: number;
}
