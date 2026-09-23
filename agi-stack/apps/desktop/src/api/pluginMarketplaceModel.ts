import type {
  ManagedPlugin,
  MarketplacePluginCatalogEntry,
  MarketplacePluginInstallRequest,
  RuntimeMode,
} from '../types';

export function managedPluginFromMarketplaceEntry(
  entry: MarketplacePluginCatalogEntry,
): ManagedPlugin {
  return {
    ...entry,
    id: `${entry.plugin_id}@${entry.version}`,
    name: entry.plugin_id,
    source: 'marketplace-v2',
    package: entry.artifact_repository,
    kind: 'bundle-v2',
    enabled: entry.install_status === 'installed' && !entry.revoked,
    discovered: !entry.revoked,
    targets: marketplacePluginTargets(entry.manifest),
  };
}

export function marketplacePluginTargets(manifest: Record<string, unknown>): string[] {
  const targets: string[] = [];
  appendTargets(targets, manifest.targets);
  appendModuleTargets(targets, manifest.modules);

  if (Array.isArray(manifest.manifests)) {
    for (const candidate of manifest.manifests) {
      if (!isRecord(candidate)) continue;
      appendTargets(targets, candidate.targets);
      appendModuleTargets(targets, candidate.modules);
    }
  }
  return [...new Set(targets)];
}

function appendModuleTargets(targets: string[], modules: unknown): void {
  if (!Array.isArray(modules)) return;
  for (const candidate of modules) {
    if (isRecord(candidate)) appendTargets(targets, candidate.targets);
  }
}

function appendTargets(targets: string[], candidates: unknown): void {
  if (!Array.isArray(candidates)) return;
  for (const candidate of candidates) {
    if (typeof candidate !== 'string') continue;
    const target = candidate.trim();
    if (target) targets.push(target);
  }
}

export type MarketplaceInstallAvailability =
  | 'ready'
  | 'installed'
  | 'revoked'
  | 'scan_pending'
  | 'unsigned'
  | 'local_unavailable';

export function marketplaceInstallAvailability(
  mode: RuntimeMode,
  entry: MarketplacePluginCatalogEntry,
): MarketplaceInstallAvailability {
  if (mode !== 'cloud') return 'local_unavailable';
  if (entry.revoked) return 'revoked';
  if (entry.install_status === 'installed') return 'installed';
  if (entry.security_scan_status !== 'passed') return 'scan_pending';
  return marketplaceIntegrityAnchors(entry) ? 'ready' : 'unsigned';
}

export function marketplacePluginPermissions(manifest: Record<string, unknown>): string[] {
  const permissions: string[] = [];
  if (Array.isArray(manifest.manifests)) {
    for (const candidate of manifest.manifests) {
      if (!isRecord(candidate)) continue;
      appendTargets(permissions, candidate.permissions);
    }
  }
  return [...new Set(permissions)].sort();
}

export function buildMarketplaceInstallRequest(
  entry: MarketplacePluginCatalogEntry,
  tenantId: string,
): MarketplacePluginInstallRequest | null {
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
    approved_permissions: marketplacePluginPermissions(entry.manifest),
    tenant_admin_approved: true,
    security_scan_passed: entry.security_scan_status === 'passed',
  };
}

/**
 * The catalog redacts signature secrets by contract (no PEM material is ever
 * exposed), so the install request carries no signature/provenance and the
 * backend resolves the signing material from the catalog row plus its own
 * trust store. Availability therefore hinges on the row carrying the redacted
 * integrity anchors that resolution verifies against.
 */
function marketplaceIntegrityAnchors(entry: MarketplacePluginCatalogEntry): boolean {
  const fingerprint = stringValue(entry.signature.public_key_sha256);
  const signatureDigest = stringValue(entry.signature.signature_sha256);
  const provenance = isRecord(entry.provenance)
    ? Object.values(entry.provenance).some(
        (value) => typeof value === 'string' && value.trim(),
      )
    : false;
  return Boolean(fingerprint && signatureDigest && provenance);
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
