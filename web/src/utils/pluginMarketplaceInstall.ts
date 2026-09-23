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

/**
 * The catalog redacts signature secrets by contract (no PEM material is ever
 * exposed), so the install request carries no signature/provenance and the
 * backend resolves the signing material from the catalog row plus its own
 * trust store. Availability therefore hinges on the row carrying the redacted
 * integrity anchors that resolution verifies against.
 */
const marketplaceIntegrityAnchors = (entry: MarketplacePackageCatalogEntry): boolean => {
  const fingerprint = stringValue(entry.signature.public_key_sha256);
  const signatureDigest = stringValue(entry.signature.signature_sha256);
  const provenance = isRecord(entry.provenance)
    ? Object.values(entry.provenance).some((value) => typeof value === 'string' && value.trim())
    : false;
  return Boolean(fingerprint && signatureDigest && provenance);
};

export const marketplaceInstallAvailability = (
  entry: MarketplacePackageCatalogEntry
): MarketplaceInstallAvailability => {
  if (entry.revoked) return 'revoked';
  if (entry.install_status === 'installed') return 'installed';
  if (entry.security_scan_status !== 'passed') return 'scan_pending';
  return marketplaceIntegrityAnchors(entry) ? 'ready' : 'unsigned';
};

/**
 * Build the exact protocol-v2 install request from one catalog entry. Returns
 * null when the catalog row lacks the redacted integrity anchors, so callers
 * can present an honest unavailable state instead of a doomed request.
 */
export const buildMarketplaceInstallRequest = (
  entry: MarketplacePackageCatalogEntry,
  tenantId: string
): MarketplacePackageInstallRequest | null => {
  const tenant = tenantId.trim();
  if (!marketplaceIntegrityAnchors(entry) || !tenant) return null;
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
    approved_permissions: marketplacePackagePermissions(entry.manifest),
    tenant_admin_approved: true,
    security_scan_passed: entry.security_scan_status === 'passed',
  };
};
