import type {
  MarketplacePackageCatalogEntry,
  MarketplacePackageInstallRequest,
} from '@/types/pluginMarketplace';

export type MarketplaceInstallAvailability =
  | 'ready'
  | 'installed'
  | 'revoked'
  | 'scan_pending'
  | 'unsigned';

const stringValue = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value : null;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value);

/**
 * Declared permissions of one protocol-v2 bundle, collected from the catalog
 * manifest's plugin manifests, deduplicated and sorted.
 */
export const marketplacePackagePermissions = (manifest: Record<string, unknown>): string[] => {
  const permissions = new Set<string>();
  if (Array.isArray(manifest.manifests)) {
    for (const candidate of manifest.manifests) {
      if (!isRecord(candidate) || !Array.isArray(candidate.permissions)) continue;
      for (const permission of candidate.permissions) {
        if (typeof permission === 'string' && permission.trim()) permissions.add(permission);
      }
    }
  }
  return [...permissions].sort();
};

type MarketplaceSignatureMaterial = Pick<
  MarketplacePackageInstallRequest,
  'signature' | 'provenance'
>;

const marketplaceSignatureMaterial = (
  entry: MarketplacePackageCatalogEntry
): MarketplaceSignatureMaterial | null => {
  const publicKeyPem = stringValue(entry.signature.public_key_pem);
  const signatureBase64 =
    stringValue(entry.signature.signature_base64) ?? stringValue(entry.manifest.signature);
  const predicateType =
    stringValue(entry.provenance.predicate_type) ?? stringValue(entry.provenance.predicateType);
  const builderId =
    stringValue(entry.provenance.builder_id) ?? stringValue(entry.provenance.builderId);
  const subjectName =
    stringValue(entry.provenance.subject_name) ?? stringValue(entry.provenance.subjectName);
  if (!publicKeyPem || !signatureBase64 || !predicateType || !builderId || !subjectName) {
    return null;
  }
  return {
    signature: {
      algorithm: stringValue(entry.signature.algorithm) ?? 'Ed25519',
      public_key_pem: publicKeyPem,
      signature_base64: signatureBase64,
    },
    provenance: {
      predicate_type: predicateType,
      builder_id: builderId,
      subject_name: subjectName,
    },
  };
};

export const marketplaceInstallAvailability = (
  entry: MarketplacePackageCatalogEntry
): MarketplaceInstallAvailability => {
  if (entry.revoked) return 'revoked';
  if (entry.install_status === 'installed') return 'installed';
  if (entry.security_scan_status !== 'passed') return 'scan_pending';
  return marketplaceSignatureMaterial(entry) === null ? 'unsigned' : 'ready';
};

/**
 * Build the exact protocol-v2 install request from one catalog entry. Returns
 * null when the catalog row does not carry verifiable signature material, so
 * callers can present an honest unavailable state instead of a doomed request.
 */
export const buildMarketplaceInstallRequest = (
  entry: MarketplacePackageCatalogEntry,
  tenantId: string
): MarketplacePackageInstallRequest | null => {
  const material = marketplaceSignatureMaterial(entry);
  const tenant = tenantId.trim();
  if (!material || !tenant) return null;
  return {
    plugin_id: entry.plugin_id,
    version: entry.version,
    publisher: entry.publisher,
    tenant_id: tenant,
    artifact: {
      registry: entry.artifact_registry,
      repository: entry.artifact_repository,
      manifest_sha256: entry.oci_manifest_digest,
    },
    artifact_sha256: entry.artifact_digest,
    manifest: entry.manifest,
    signature: material.signature,
    provenance: material.provenance,
    approved_permissions: marketplacePackagePermissions(entry.manifest),
    tenant_admin_approved: true,
    security_scan_passed: entry.security_scan_status === 'passed',
  };
};
