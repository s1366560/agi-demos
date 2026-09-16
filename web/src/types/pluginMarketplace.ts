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

export interface MarketplacePackageArtifactSource {
  registry: string;
  repository: string;
  manifest_sha256: string;
}

export interface MarketplacePackageInstallRequest {
  plugin_id: string;
  version: string;
  publisher: string;
  tenant_id: string;
  artifact: MarketplacePackageArtifactSource;
  artifact_sha256: string;
  manifest: Record<string, unknown>;
  signature: {
    algorithm: string;
    public_key_pem: string;
    signature_base64: string;
  };
  provenance: {
    predicate_type: string;
    builder_id: string;
    subject_name: string;
  };
  approved_permissions: string[];
  tenant_admin_approved: boolean;
  security_scan_passed: boolean;
}

export interface MarketplacePackageInstallResponse {
  plugin_id: string;
  version: string;
  status: string;
  reason: string;
}

export interface MarketplacePackageApproveRequest {
  version: string;
  tenant_id: string;
  approved_permissions: string[];
}

export interface MarketplacePackageApprovalResponse {
  plugin_id: string;
  version: string;
  status: 'approved' | 'revoked';
  granted_permissions: string[];
}

export interface MarketplacePackageRevokeRequest {
  reason: string;
  version?: string | undefined;
}

export interface MarketplacePackageRevocationResponse {
  plugin_id: string;
  revoked_versions: string[];
  revoked_permissions: number;
}
