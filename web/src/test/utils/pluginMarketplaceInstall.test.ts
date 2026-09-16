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
    manifests: [{ permissions: ['tools.execute', 'network.egress'] }, { permissions: ['tools.execute'] }],
  },
  signature: { algorithm: 'Ed25519', public_key_pem: 'pem-public', signature_base64: 'c2ln' },
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
        provenance: { builder_id: 'builder-v2' },
      })
    ).toBe('unsigned');
  });

  it('collects declared permissions from bundle manifests, deduplicated and sorted', () => {
    expect(marketplacePackagePermissions(signedEntry.manifest)).toEqual([
      'network.egress',
      'tools.execute',
    ]);
    expect(marketplacePackagePermissions({})).toEqual([]);
  });

  it('pins the exact protocol-v2 install request shape', () => {
    expect(buildMarketplaceInstallRequest(signedEntry, 'tenant-1')).toEqual({
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
      signature: {
        algorithm: 'Ed25519',
        public_key_pem: 'pem-public',
        signature_base64: 'c2ln',
      },
      provenance: {
        predicate_type: 'https://slsa.dev/provenance/v1',
        builder_id: 'builder-v2',
        subject_name: 'release/notifier',
      },
      approved_permissions: ['network.egress', 'tools.execute'],
      tenant_admin_approved: true,
      security_scan_passed: true,
    });
  });

  it('maps snake_case provenance and falls back to the manifest signature', () => {
    const request = buildMarketplaceInstallRequest(
      {
        ...signedEntry,
        signature: { public_key_pem: 'pem-public' },
        provenance: {
          predicate_type: 'https://slsa.dev/provenance/v1',
          builder_id: 'builder-v2',
          subject_name: 'release/notifier',
        },
      },
      'tenant-1'
    );
    expect(request?.signature.signature_base64).toBe('c2ln');
    expect(request?.provenance.builder_id).toBe('builder-v2');
    expect(buildMarketplaceInstallRequest(signedEntry, '  ')).toBeNull();
  });
});
