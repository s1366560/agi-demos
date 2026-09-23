import { describe, expect, it } from 'vitest';

import {
  buildMarketplaceInstallRequest,
  marketplaceInstallAvailability,
  marketplacePackagePermissions,
} from '@/utils/pluginMarketplaceInstall';

import type { MarketplacePackageCatalogEntry } from '@/types/pluginMarketplace';

const signedEntry: MarketplacePackageCatalogEntry = {
  plugin_id: 'release/notifier',
  version: '2.4.1',
  publisher: 'MemStack Labs',
  artifact_digest: 'a'.repeat(64),
  artifact_registry: 'https://registry.example.test',
  artifact_repository: 'plugins/release-notifier',
  oci_manifest_digest: 'b'.repeat(64),
  install_status: 'uninstalled',
  manifest: {
    signature: 'c2ln',
    manifests: [
      { permissions: ['tools.execute', 'network.egress'] },
      { permissions: ['tools.execute'] },
    ],
  },
  // Catalog rows redact signature secrets; the anchors below are what the
  // backend resolution verifies against.
  signature: {
    algorithm: 'Ed25519',
    public_key_sha256: 'f'.repeat(64),
    signature_sha256: 'e'.repeat(64),
  },
  provenance: {
    predicateType: 'https://slsa.dev/provenance/v1',
    builderId: 'builder-v2',
    subjectName: 'release/notifier',
  },
  security_scan_status: 'passed',
  revoked: false,
  revocation_reason: null,
};

describe('pluginMarketplaceInstall model', () => {
  it('distinguishes ready, installed, revoked, scan-pending and unsigned entries', () => {
    expect(marketplaceInstallAvailability(signedEntry)).toBe('ready');
    expect(marketplaceInstallAvailability({ ...signedEntry, install_status: 'installed' })).toBe(
      'installed'
    );
    expect(marketplaceInstallAvailability({ ...signedEntry, revoked: true })).toBe('revoked');
    expect(
      marketplaceInstallAvailability({ ...signedEntry, security_scan_status: 'pending' })
    ).toBe('scan_pending');
    expect(
      marketplaceInstallAvailability({
        ...signedEntry,
        signature: { algorithm: 'Ed25519' },
      })
    ).toBe('unsigned');
    expect(marketplaceInstallAvailability({ ...signedEntry, provenance: {} })).toBe('unsigned');
  });

  it('collects declared permissions from bundle manifests, deduplicated and sorted', () => {
    expect(marketplacePackagePermissions(signedEntry.manifest)).toEqual([
      'network.egress',
      'tools.execute',
    ]);
    expect(marketplacePackagePermissions({})).toEqual([]);
  });

  it('pins the exact protocol-v2 install request shape without signature material', () => {
    const request = buildMarketplaceInstallRequest(signedEntry, 'tenant-1');
    expect(Object.keys(request ?? {})).not.toContain('signature');
    expect(Object.keys(request ?? {})).not.toContain('provenance');
    expect(request).toEqual({
      plugin_id: 'release/notifier',
      version: '2.4.1',
      publisher: 'MemStack Labs',
      tenant_id: 'tenant-1',
      artifact: {
        registry: 'https://registry.example.test',
        repository: 'plugins/release-notifier',
        manifest_sha256: 'b'.repeat(64),
      },
      artifact_sha256: 'a'.repeat(64),
      manifest: signedEntry.manifest,
      approved_permissions: ['network.egress', 'tools.execute'],
      tenant_admin_approved: true,
      security_scan_passed: true,
    });
  });

  it('refuses entries without integrity anchors and blank tenants', () => {
    expect(
      buildMarketplaceInstallRequest(
        { ...signedEntry, signature: { public_key_pem: 'pem-public' } },
        'tenant-1'
      )
    ).toBeNull();
    expect(buildMarketplaceInstallRequest(signedEntry, '  ')).toBeNull();
  });
});
