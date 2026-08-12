import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { deflateRawSync, gzipSync } from 'node:zlib';
import { parse, stringify } from 'yaml';

import {
  assertMacAudioInputEntitlement,
  buildReleaseEvidence,
  verifyReleaseRootMetadata,
} from '../scripts/verify-release-artifacts.mjs';
import {
  inspectPortableExecutableArchitecture,
  verifyMacPackageArtifacts,
  verifyWindowsInstallerArtifact,
} from '../scripts/release-package-verification.mjs';
import { platformPolicy, writeReleaseEvidence } from '../scripts/release-artifact-contract.mjs';
import { verifyDownloadedReleaseAssets } from '../scripts/release-draft-validation.mjs';

const VERSION = '0.1.0';
const PLATFORM_FIXTURES = Object.freeze({
  darwin: {
    metadata: 'latest-mac.yml',
    installers: [
      'agi-stack-desktop-0.1.0-mac-universal.dmg',
      'agi-stack-desktop-0.1.0-mac-universal.zip',
    ],
    externalBlockmapSuffix: '.zip',
  },
  win32: {
    metadata: 'latest.yml',
    installers: ['agi-stack-desktop-0.1.0-win-x64.exe'],
    externalBlockmapSuffix: '.exe',
  },
  linux: {
    metadata: 'latest-linux.yml',
    installers: [
      'agi-stack-desktop-0.1.0-linux-x64.AppImage',
      'agi-stack-desktop-0.1.0-linux-x64.deb',
    ],
    embeddedBlockmapSuffix: '.AppImage',
  },
});

function sha512(content) {
  return createHash('sha512').update(content).digest('base64');
}

function blockMap(size) {
  return {
    version: '2',
    files: [
      {
        name: 'file',
        offset: 0,
        checksums: [Buffer.alloc(18, 7).toString('base64')],
        sizes: [size],
      },
    ],
  };
}

function createFixture(platform, { macArchitecture = 'universal' } = {}) {
  const fixture = PLATFORM_FIXTURES[platform];
  const releaseRoot = mkdtempSync(join(tmpdir(), `agistack-release-${platform}-`));
  const installers = fixture.installers.map((name) =>
    platform === 'darwin' ? name.replace('-universal.', `-${macArchitecture}.`) : name,
  );
  for (const [index, name] of installers.entries()) {
    const content = Buffer.from(`${platform}-installer-${index}`);
    writeFileSync(join(releaseRoot, name), content);
  }
  const embeddedInstaller = installers.find((name) =>
    name.endsWith(fixture.embeddedBlockmapSuffix ?? '\0'),
  );
  let embeddedBlockMapSize;
  if (embeddedInstaller) {
    const path = join(releaseRoot, embeddedInstaller);
    const original = readFileSync(path);
    const compressed = deflateRawSync(Buffer.from(JSON.stringify(blockMap(original.byteLength))));
    const sizeTrailer = Buffer.alloc(4);
    sizeTrailer.writeUInt32BE(compressed.byteLength);
    writeFileSync(path, Buffer.concat([original, compressed, sizeTrailer]));
    embeddedBlockMapSize = compressed.byteLength;
  }
  const externalInstaller = installers.find((name) =>
    name.endsWith(fixture.externalBlockmapSuffix ?? '\0'),
  );
  if (externalInstaller) {
    const installerSize = statSync(join(releaseRoot, externalInstaller)).size;
    writeFileSync(
      join(releaseRoot, `${externalInstaller}.blockmap`),
      gzipSync(Buffer.from(JSON.stringify(blockMap(installerSize)))),
    );
  }
  const files = installers.map((name) => {
    const content = readFileSync(join(releaseRoot, name));
    return {
      url: name,
      sha512: sha512(content),
      size: content.byteLength,
      ...(name === embeddedInstaller ? { blockMapSize: embeddedBlockMapSize } : {}),
    };
  });
  const metadata = {
    version: VERSION,
    files,
    path: files[0].url,
    sha512: files[0].sha512,
  };
  writeFileSync(join(releaseRoot, fixture.metadata), stringify(metadata));
  return {
    releaseRoot,
    metadataPath: join(releaseRoot, fixture.metadata),
    metadata,
  };
}

function withFixture(platform, run) {
  const fixture = createFixture(platform);
  return Promise.resolve(run(fixture)).finally(() => {
    rmSync(fixture.releaseRoot, { recursive: true, force: true });
  });
}

function writeCombinedEvidencePlatform({
  root,
  platform,
  evidencePlatform,
  names,
  packageVerification,
}) {
  const directory = join(root, 'verified', platform);
  mkdirSync(directory, { recursive: true });
  const assets = names.map((name, index) => {
    const content = Buffer.from(`${platform}-release-asset-${index}`);
    writeFileSync(join(directory, name), content);
    return {
      name,
      size: content.byteLength,
      sha512: sha512(content),
    };
  });
  const evidence = buildReleaseEvidence({
    platform: evidencePlatform,
    version: VERSION,
    expectedVersion: VERSION,
    tag: `v${VERSION}`,
    commitSha: 'a'.repeat(40),
    runId: '12345',
    runAttempt: '2',
    runUrl: 'https://github.com/example/repository/actions/runs/12345',
    assets,
    packageVerification,
  });
  writeFileSync(
    join(directory, `release-evidence-${evidencePlatform}.json`),
    JSON.stringify(evidence),
  );
}

for (const platform of Object.keys(PLATFORM_FIXTURES)) {
  test(`${platform} release metadata validates exact root installers`, async () => {
    await withFixture(platform, async ({ releaseRoot }) => {
      const result = await verifyReleaseRootMetadata({
        releaseRoot,
        platform,
        version: VERSION,
        expectedTag: `v${VERSION}`,
      });
      assert.equal(result.installers.length, PLATFORM_FIXTURES[platform].installers.length);
    });
  });
}

test('macOS release validation requires a true audio input entitlement', () => {
  assert.doesNotThrow(() => {
    assertMacAudioInputEntitlement(
      '/Applications/AGI Stack Desktop.app',
      '<key>com.apple.security.device.audio-input</key><true/>',
    );
  });
  assert.throws(() => {
    assertMacAudioInputEntitlement(
      '/Applications/AGI Stack Desktop.app',
      '<key>com.apple.security.device.audio-input</key><false/>',
    );
  }, /audio-input entitlement is missing/u);
});

test('macOS package verification inspects the app and sidecar from both uploaded artifacts', async () => {
  const fixtureRoot = mkdtempSync(join(tmpdir(), 'agistack-mac-package-fixture-'));
  const mountedRoot = join(fixtureRoot, 'mounted-dmg');
  const inspectedSources = [];
  try {
    const result = await verifyMacPackageArtifacts({
      zipPath: join(fixtureRoot, 'release.zip'),
      dmgPath: join(fixtureRoot, 'release.dmg'),
      extractZip: async (_path, destination) => {
        mkdirSync(join(destination, 'AGI Stack Desktop.app'), {
          recursive: true,
        });
      },
      withMountedDmg: async (_path, inspect) => {
        mkdirSync(join(mountedRoot, 'AGI Stack Desktop.app'), {
          recursive: true,
        });
        return inspect(mountedRoot);
      },
      inspectAppBundle: async (appPath, source) => {
        inspectedSources.push({ appPath, source });
        return {
          sidecar_sha256: 'a'.repeat(64),
          workspace_core_sha256: 'c'.repeat(64),
          developer_id_authority: 'Developer ID Application: Example Company (TEAMID1234)',
          team_identifier: 'TEAMID1234',
          signing_certificate_sha256: 'b'.repeat(64),
          app_architectures: ['arm64', 'x86_64'],
          sidecar_architectures: ['arm64', 'x86_64'],
          workspace_core_architectures: ['arm64', 'x86_64'],
        };
      },
    });

    assert.deepEqual(
      inspectedSources.map(({ source }) => source),
      ['zip', 'dmg'],
    );
    assert.ok(inspectedSources[0].appPath.includes('.zip-extracted-'));
    assert.ok(inspectedSources[1].appPath.startsWith(mountedRoot));
    assert.equal(result.package_sidecars_identical, true);
    assert.equal(result.package_workspace_cores_identical, true);
    assert.equal(result.zip_app_verified, true);
    assert.equal(result.dmg_app_verified, true);
    assert.equal(result.sidecar_sha256, 'a'.repeat(64));
    assert.equal(result.workspace_core_sha256, 'c'.repeat(64));
  } finally {
    rmSync(fixtureRoot, { recursive: true, force: true });
  }
});

test('macOS package verification rejects different sidecars in the zip and dmg', async () => {
  const fixtureRoot = mkdtempSync(join(tmpdir(), 'agistack-mac-package-drift-'));
  const mountedRoot = join(fixtureRoot, 'mounted-dmg');
  try {
    await assert.rejects(
      verifyMacPackageArtifacts({
        zipPath: join(fixtureRoot, 'release.zip'),
        dmgPath: join(fixtureRoot, 'release.dmg'),
        extractZip: async (_path, destination) => {
          mkdirSync(join(destination, 'AGI Stack Desktop.app'), {
            recursive: true,
          });
        },
        withMountedDmg: async (_path, inspect) => {
          mkdirSync(join(mountedRoot, 'AGI Stack Desktop.app'), {
            recursive: true,
          });
          return inspect(mountedRoot);
        },
        inspectAppBundle: async (_appPath, source) => ({
          sidecar_sha256: (source === 'zip' ? 'a' : 'c').repeat(64),
          workspace_core_sha256: 'd'.repeat(64),
          developer_id_authority: 'Developer ID Application: Example Company (TEAMID1234)',
          team_identifier: 'TEAMID1234',
          signing_certificate_sha256: 'b'.repeat(64),
          app_architectures: ['arm64', 'x86_64'],
          sidecar_architectures: ['arm64', 'x86_64'],
          workspace_core_architectures: ['arm64', 'x86_64'],
        }),
      }),
      /zip and dmg sidecar digests do not match/u,
    );
  } finally {
    rmSync(fixtureRoot, { recursive: true, force: true });
  }
});

test('Windows package verification extracts the uploaded NSIS installer fail-closed', async () => {
  const fixtureRoot = mkdtempSync(join(tmpdir(), 'agistack-windows-package-'));
  const installerPath = join(fixtureRoot, 'agi-stack-desktop-0.1.0-win-x64.exe');
  const extracted = [];
  try {
    const result = await verifyWindowsInstallerArtifact({
      installerPath,
      expectedArchitecture: 'x64',
      sidecarName: 'agistack-desktop-sidecar.exe',
      workspaceCoreName: 'memstack-workspace-core.exe',
      extractArchive: async (archivePath, destination) => {
        extracted.push(archivePath);
        if (archivePath === installerPath) {
          mkdirSync(join(destination, '$PLUGINSDIR'), { recursive: true });
          writeFileSync(join(destination, '$PLUGINSDIR', 'app-64.7z'), 'fixture');
          return;
        }
        const sidecarDirectory = join(destination, 'resources', 'sidecar');
        const workspaceCoreDirectory = join(destination, 'resources', 'workspace-core');
        mkdirSync(sidecarDirectory, { recursive: true });
        mkdirSync(workspaceCoreDirectory, { recursive: true });
        writeFileSync(join(sidecarDirectory, 'agistack-desktop-sidecar.exe'), 'signed-sidecar');
        writeFileSync(
          join(workspaceCoreDirectory, 'memstack-workspace-core.exe'),
          'signed-workspace-core',
        );
      },
      inspectInstallerPayload: async ({ packagedSidecarPath, packagedWorkspaceCorePath }) => {
        assert.match(
          packagedSidecarPath,
          /resources[\\/]sidecar[\\/]agistack-desktop-sidecar\.exe$/u,
        );
        assert.match(
          packagedWorkspaceCorePath,
          /resources[\/]workspace-core[\/]memstack-workspace-core\.exe$/u,
        );
        return {
          sidecar_sha256: 'd'.repeat(64),
          workspace_core_sha256: 'f'.repeat(64),
          sidecar_architecture: 'x64',
          workspace_core_architecture: 'x64',
          signer_thumbprint: 'E'.repeat(40),
          installer_authenticode_valid: true,
          sidecar_authenticode_valid: true,
          workspace_core_authenticode_valid: true,
        };
      },
    });

    assert.equal(extracted[0], installerPath);
    assert.equal(basename(extracted[1]), 'app-64.7z');
    assert.equal(result.installer_payload_extracted, true);
    assert.equal(result.installer_payload_archive, 'app-64.7z');
    assert.equal(result.sidecar_sha256, 'd'.repeat(64));
    assert.equal(result.sidecar_architecture, 'x64');
    assert.equal(result.workspace_core_sha256, 'f'.repeat(64));
    assert.equal(result.workspace_core_architecture, 'x64');
  } finally {
    rmSync(fixtureRoot, { recursive: true, force: true });
  }
});

test('Windows package verification rejects a missing embedded NSIS payload', async () => {
  await assert.rejects(
    verifyWindowsInstallerArtifact({
      installerPath: '/release/agi-stack-desktop-0.1.0-win-x64.exe',
      expectedArchitecture: 'x64',
      sidecarName: 'agistack-desktop-sidecar.exe',
      workspaceCoreName: 'memstack-workspace-core.exe',
      extractArchive: async () => {},
      inspectInstallerPayload: async () => {
        throw new Error('must not inspect an absent payload');
      },
    }),
    /NSIS embedded app-64\.7z must have exactly one match; found 0/u,
  );
});

test('portable executable architecture is read from the PE machine header', () => {
  const portableExecutable = (machine) => {
    const buffer = Buffer.alloc(256);
    buffer.write('MZ', 0, 'ascii');
    buffer.writeUInt32LE(128, 0x3c);
    buffer.writeUInt32LE(0x00004550, 128);
    buffer.writeUInt16LE(machine, 132);
    return buffer;
  };

  assert.equal(inspectPortableExecutableArchitecture(portableExecutable(0x8664)), 'x64');
  assert.equal(inspectPortableExecutableArchitecture(portableExecutable(0xaa64)), 'arm64');
  assert.throws(
    () => inspectPortableExecutableArchitecture(Buffer.from('not-a-pe')),
    /portable executable header is invalid/u,
  );
});

test('release metadata rejects package/tag version drift', async () => {
  await withFixture('darwin', async ({ releaseRoot }) => {
    await assert.rejects(
      verifyReleaseRootMetadata({
        releaseRoot,
        platform: 'darwin',
        version: VERSION,
        expectedTag: 'v9.9.9',
      }),
      /release tag must exactly match/u,
    );
  });
});

test('release metadata rejects duplicate and unknown update targets', async () => {
  await withFixture('darwin', async ({ releaseRoot, metadataPath, metadata }) => {
    metadata.files[1] = { ...metadata.files[0] };
    writeFileSync(metadataPath, stringify(metadata));
    await assert.rejects(
      verifyReleaseRootMetadata({
        releaseRoot,
        platform: 'darwin',
        version: VERSION,
      }),
      /duplicate update target/u,
    );

    const restored = createFixture('darwin');
    try {
      const document = restored.metadata;
      document.files[0].url = 'unexpected.pkg';
      writeFileSync(restored.metadataPath, stringify(document));
      await assert.rejects(
        verifyReleaseRootMetadata({
          releaseRoot: restored.releaseRoot,
          platform: 'darwin',
          version: VERSION,
        }),
        /unknown update target/u,
      );
    } finally {
      rmSync(restored.releaseRoot, { recursive: true, force: true });
    }
  });
});

test('release metadata verifies SHA-512, size, and legacy path together', async () => {
  await withFixture('linux', async ({ releaseRoot, metadataPath, metadata }) => {
    metadata.files[0].size += 1;
    writeFileSync(metadataPath, stringify(metadata));
    await assert.rejects(
      verifyReleaseRootMetadata({
        releaseRoot,
        platform: 'linux',
        version: VERSION,
      }),
      /size mismatch/u,
    );

    metadata.files[0].size -= 1;
    metadata.sha512 = metadata.files[1].sha512;
    writeFileSync(metadataPath, stringify(metadata));
    await assert.rejects(
      verifyReleaseRootMetadata({
        releaseRoot,
        platform: 'linux',
        version: VERSION,
      }),
      /legacy path\/sha512/u,
    );
  });
});

test('release root rejects files outside the publication allow-list', async () => {
  await withFixture('win32', async ({ releaseRoot }) => {
    writeFileSync(join(releaseRoot, 'unexpected.msi'), 'not allowed');
    await assert.rejects(
      verifyReleaseRootMetadata({
        releaseRoot,
        platform: 'win32',
        version: VERSION,
      }),
      /outside the publish allow-list/u,
    );
  });
});

test('release metadata requires external blockmap structure and full-size coverage', async () => {
  await withFixture('darwin', async ({ releaseRoot }) => {
    const blockmap = join(releaseRoot, 'agi-stack-desktop-0.1.0-mac-universal.zip.blockmap');
    rmSync(blockmap);
    await assert.rejects(
      verifyReleaseRootMetadata({
        releaseRoot,
        platform: 'darwin',
        version: VERSION,
      }),
      /missing required .*\.zip\.blockmap/u,
    );
  });

  await withFixture('win32', async ({ releaseRoot }) => {
    const blockmap = join(releaseRoot, 'agi-stack-desktop-0.1.0-win-x64.exe.blockmap');
    writeFileSync(blockmap, 'not a blockmap');
    await assert.rejects(
      verifyReleaseRootMetadata({
        releaseRoot,
        platform: 'win32',
        version: VERSION,
      }),
      /blockmap/u,
    );
  });
});

test('blockmap evidence is limited to structure and installer-size coverage', async () => {
  await withFixture('win32', async ({ releaseRoot }) => {
    const blockmapPath = join(releaseRoot, 'agi-stack-desktop-0.1.0-win-x64.exe.blockmap');
    const installerPath = join(releaseRoot, 'agi-stack-desktop-0.1.0-win-x64.exe');
    const installerSize = statSync(installerPath).size;
    writeFileSync(
      blockmapPath,
      gzipSync(
        Buffer.from(
          JSON.stringify({
            ...blockMap(installerSize),
            files: [
              {
                ...blockMap(installerSize).files[0],
                checksums: [Buffer.alloc(18, 255).toString('base64')],
              },
            ],
          }),
        ),
      ),
    );

    const result = await verifyReleaseRootMetadata({
      releaseRoot,
      platform: 'win32',
      version: VERSION,
      expectedTag: `v${VERSION}`,
    });

    assert.equal(result.blockmapVerificationScope, 'blockmap_structure_and_coverage_only');
    assert.equal('blockmapChecksumsVerified' in result, false);
  });
});

test('release metadata validates the embedded AppImage blockmap', async () => {
  await withFixture('linux', async ({ releaseRoot, metadataPath, metadata }) => {
    const appImage = metadata.files.find((entry) => entry.url.endsWith('.AppImage'));
    appImage.blockMapSize += 1;
    writeFileSync(metadataPath, stringify(metadata));
    await assert.rejects(
      verifyReleaseRootMetadata({
        releaseRoot,
        platform: 'linux',
        version: VERSION,
      }),
      /embedded blockmap/u,
    );
  });
});

test('macOS release metadata accepts only universal artifacts', async () => {
  const fixture = createFixture('darwin', { macArchitecture: 'arm64' });
  try {
    await assert.rejects(
      verifyReleaseRootMetadata({
        releaseRoot: fixture.releaseRoot,
        platform: 'darwin',
        version: VERSION,
      }),
      /universal/u,
    );
  } finally {
    rmSync(fixture.releaseRoot, { recursive: true, force: true });
  }
});

test('release evidence binds tag CI identity and package-only artifact checks', () => {
  const input = {
    platform: 'linux',
    version: VERSION,
    expectedVersion: VERSION,
    tag: `v${VERSION}`,
    commitSha: 'a'.repeat(40),
    runId: '12345',
    runAttempt: '2',
    runUrl: 'https://github.com/example/repository/actions/runs/12345',
    assets: [
      {
        name: 'agi-stack-desktop-0.1.0-linux-x64.AppImage',
        size: 42,
        sha512: Buffer.alloc(64, 3).toString('base64'),
      },
    ],
    packageVerification: {
      architecture: 'x64',
      appimage_extract_smoke: true,
      deb_extract_smoke: true,
      desktop_entry: 'agi-stack-desktop.desktop',
      sidecar_executable: true,
    },
  };
  const evidence = buildReleaseEvidence(input);
  assert.deepEqual(Object.keys(evidence), [
    'contract_version',
    'evidence_scope',
    'blockmap_verification_scope',
    'artifact_verification_status',
    'release_disposition',
    'release_blocker_reason_code',
    'required_native_checks',
    'verification_checks',
    'platform',
    'version',
    'tag',
    'commit_sha',
    'workflow_run',
    'package_verification',
    'assets',
  ]);
  assert.equal(evidence.contract_version, 'desktop-release-package-evidence-v1');
  assert.equal(evidence.evidence_scope, 'package_artifacts_and_promotion_requirements');
  assert.equal(evidence.blockmap_verification_scope, 'blockmap_structure_and_coverage_only');
  assert.equal(evidence.artifact_verification_status, 'verified_by_tag_ci');
  assert.equal(evidence.release_disposition, 'prerelease_only');
  assert.equal(evidence.release_blocker_reason_code, 'stable_promotion_native_evidence_required');
  assert.deepEqual(evidence.required_native_checks, [
    'install',
    'launch',
    'updater_apply',
    'updater_failure_rollback',
  ]);
  assert.deepEqual(evidence.verification_checks, [
    { id: 'package_artifacts', status: 'passed', reason_code: null },
    { id: 'install', status: 'blocked', reason_code: 'native_install_evidence_missing' },
    { id: 'launch', status: 'blocked', reason_code: 'native_launch_evidence_missing' },
    { id: 'updater_apply', status: 'blocked', reason_code: 'updater_apply_evidence_missing' },
    {
      id: 'updater_failure_rollback',
      status: 'blocked',
      reason_code: 'updater_failure_rollback_evidence_missing',
    },
  ]);
  assert.deepEqual(evidence.package_verification, input.packageVerification);
  assert.equal('verification_status' in evidence, false);
  assert.equal('native_verification' in evidence, false);
  assert.equal(evidence.tag, 'v0.1.0');
  assert.equal(evidence.commit_sha, 'a'.repeat(40));
  assert.deepEqual(
    evidence.assets.map((asset) => asset.name),
    ['agi-stack-desktop-0.1.0-linux-x64.AppImage'],
  );

  assert.throws(
    () =>
      buildReleaseEvidence({
        ...input,
        tag: 'v9.9.9',
      }),
    /tag must exactly match/u,
  );
  assert.throws(
    () =>
      buildReleaseEvidence({
        ...input,
        runUrl: 'https://attacker.invalid/example/repository/actions/runs/12345',
      }),
    /run URL is invalid/u,
  );
});

test('release evidence is created once with read-only permissions', async () => {
  const fixture = createFixture('linux');
  try {
    const metadataResult = await verifyReleaseRootMetadata({
      releaseRoot: fixture.releaseRoot,
      platform: 'linux',
      version: VERSION,
      expectedVersion: VERSION,
      expectedTag: `v${VERSION}`,
    });
    const input = {
      releaseRoot: fixture.releaseRoot,
      policy: platformPolicy('linux'),
      version: VERSION,
      expectedVersion: VERSION,
      tag: `v${VERSION}`,
      commitSha: 'b'.repeat(40),
      runId: '54321',
      runAttempt: '1',
      runUrl: 'https://github.com/example/repository/actions/runs/54321',
      artifactPaths: metadataResult.publishableArtifacts,
      packageVerification: { package_verification_fixture: true },
    };
    const evidencePath = await writeReleaseEvidence(input);
    assert.equal(basename(evidencePath), 'release-evidence-linux.json');
    assert.equal(statSync(evidencePath).mode & 0o777, 0o444);
    assert.equal(
      JSON.parse(readFileSync(evidencePath, 'utf8')).artifact_verification_status,
      'verified_by_tag_ci',
    );
    await assert.rejects(writeReleaseEvidence(input), { code: 'EEXIST' });
  } finally {
    rmSync(fixture.releaseRoot, { recursive: true, force: true });
  }
});

test('draft staging validation accepts exact evidence and rejects a mutated asset', () => {
  const root = mkdtempSync(join(tmpdir(), 'agistack-combined-evidence-'));
  try {
    writeCombinedEvidencePlatform({
      root,
      platform: 'macos',
      evidencePlatform: 'macos',
      names: [
        'agi-stack-desktop-0.1.0-mac-universal.dmg',
        'agi-stack-desktop-0.1.0-mac-universal.zip',
        'agi-stack-desktop-0.1.0-mac-universal.zip.blockmap',
        'latest-mac.yml',
      ],
      packageVerification: {
        architecture: 'universal',
        app_architectures: ['arm64', 'x86_64'],
        sidecar_architectures: ['arm64', 'x86_64'],
        developer_id_authority: 'Developer ID Application: Example Company (TEAMID1234)',
        team_identifier: 'TEAMID1234',
        signing_certificate_sha256: 'b'.repeat(64),
        same_signature_identity: true,
        app_signature_valid: true,
        sidecar_signature_valid: true,
        package_sidecars_identical: true,
        zip_app_verified: true,
        dmg_app_verified: true,
        notarization_verified: true,
        app_stapler_valid: true,
        dmg_stapler_valid: true,
        app_spctl_valid: true,
        dmg_spctl_valid: true,
        sidecar_sha256: 'c'.repeat(64),
        zip_sidecar_sha256: 'c'.repeat(64),
        dmg_sidecar_sha256: 'c'.repeat(64),
      },
    });
    writeCombinedEvidencePlatform({
      root,
      platform: 'windows',
      evidencePlatform: 'windows',
      names: [
        'agi-stack-desktop-0.1.0-win-x64.exe',
        'agi-stack-desktop-0.1.0-win-x64.exe.blockmap',
        'latest.yml',
      ],
      packageVerification: {
        architecture: 'x64',
        signer_thumbprint: 'D'.repeat(40),
        installer_authenticode_valid: true,
        sidecar_authenticode_valid: true,
        installer_payload_extracted: true,
        installer_payload_archive: 'app-64.7z',
        sidecar_architecture: 'x64',
        sidecar_sha256: 'e'.repeat(64),
      },
    });
    writeCombinedEvidencePlatform({
      root,
      platform: 'linux',
      evidencePlatform: 'linux',
      names: [
        'agi-stack-desktop-0.1.0-linux-x64.AppImage',
        'agi-stack-desktop-0.1.0-linux-x64.deb',
        'latest-linux.yml',
      ],
      packageVerification: {
        architecture: 'x64',
        deb_architecture: 'amd64',
        sidecar_executable: true,
        package_sidecars_identical: true,
        appimage_executable: true,
        appimage_extract_smoke: true,
        deb_extract_smoke: true,
        appimage_desktop_entry: 'agi-stack-desktop.desktop',
        deb_desktop_entry: 'agi-stack-desktop.desktop',
        sidecar_sha256: 'f'.repeat(64),
      },
    });

    const validationTool = fileURLToPath(
      new URL('../scripts/release-draft-validation.mjs', import.meta.url),
    );
    const evidenceIndexTool = fileURLToPath(
      new URL('../scripts/release-evidence-index.mjs', import.meta.url),
    );
    const evidenceIndexSchema = fileURLToPath(
      new URL('../scripts/desktop-release-package-evidence-index.v1.schema.json', import.meta.url),
    );
    const schemaValidator = fileURLToPath(
      new URL('../contracts/desktop-web-parity/schema-validator.mjs', import.meta.url),
    );
    const toolDirectory = join(root, 'release-tools');
    mkdirSync(toolDirectory);
    copyFileSync(validationTool, join(toolDirectory, 'release-draft-validation.mjs'));
    copyFileSync(evidenceIndexTool, join(toolDirectory, 'release-evidence-index.mjs'));
    copyFileSync(
      evidenceIndexSchema,
      join(toolDirectory, 'desktop-release-package-evidence-index.v1.schema.json'),
    );
    const contractDirectory = join(root, 'contracts', 'desktop-web-parity');
    mkdirSync(contractDirectory, { recursive: true });
    copyFileSync(schemaValidator, join(contractDirectory, 'schema-validator.mjs'));
    assert.match(
      readFileSync(join(toolDirectory, 'release-draft-validation.mjs'), 'utf8'),
      /assertExactRecordKeys/u,
    );
    const workflow = parse(
      readFileSync(
        new URL('../../../../.github/workflows/desktop-release.yml', import.meta.url),
        'utf8',
      ),
    );
    const validationScript = workflow.jobs['stage-draft'].steps.find(
      (step) => step.name === 'Validate the combined release asset set',
    ).run;
    assert.equal(
      validationScript.trim(),
      'node agi-stack/apps/desktop/scripts/release-draft-validation.mjs validate-combined',
    );
    const env = {
      ...process.env,
      AGISTACK_RELEASE_VERSION: VERSION,
      GITHUB_REPOSITORY: 'example/repository',
      GITHUB_REF_NAME: `v${VERSION}`,
      GITHUB_SHA: 'a'.repeat(40),
      GITHUB_RUN_ID: '12345',
      GITHUB_RUN_ATTEMPT: '2',
    };
    const validate = () =>
      spawnSync(
        process.execPath,
        ['release-tools/release-draft-validation.mjs', 'validate-combined'],
        {
          cwd: root,
          encoding: 'utf8',
          env,
        },
      );

    const valid = validate();
    assert.equal(valid.status, 0, valid.stderr);

    const macEvidencePath = join(root, 'verified', 'macos', 'release-evidence-macos.json');
    const macEvidence = JSON.parse(readFileSync(macEvidencePath, 'utf8'));
    const unexpectedMacAssetPath = join(
      root,
      'verified',
      'macos',
      'unexpected-windows-payload.exe',
    );
    const unexpectedMacAsset = Buffer.from('cross-platform payload');
    writeFileSync(unexpectedMacAssetPath, unexpectedMacAsset);
    writeFileSync(
      macEvidencePath,
      JSON.stringify({
        ...macEvidence,
        assets: [
          ...macEvidence.assets,
          {
            name: basename(unexpectedMacAssetPath),
            size: unexpectedMacAsset.byteLength,
            sha512: sha512(unexpectedMacAsset),
          },
        ],
      }),
    );
    const crossPlatformAsset = validate();
    assert.notEqual(crossPlatformAsset.status, 0);
    assert.match(crossPlatformAsset.stderr, /unexpected macos release asset/u);
    writeFileSync(macEvidencePath, JSON.stringify(macEvidence));
    rmSync(unexpectedMacAssetPath);

    const linuxEvidencePath = join(root, 'verified', 'linux', 'release-evidence-linux.json');
    const packageEvidence = JSON.parse(readFileSync(linuxEvidencePath, 'utf8'));
    writeFileSync(
      linuxEvidencePath,
      JSON.stringify({
        ...packageEvidence,
        contract_version: 'desktop-release-evidence-v1',
      }),
    );
    const legacyContract = validate();
    assert.notEqual(legacyContract.status, 0);
    assert.match(legacyContract.stderr, /release evidence contract is invalid/u);
    writeFileSync(linuxEvidencePath, JSON.stringify(packageEvidence));

    for (const [label, mutate] of [
      [
        'top-level',
        (evidence) => {
          evidence.verification_status = 'verified';
        },
      ],
      [
        'workflow-run',
        (evidence) => {
          evidence.workflow_run.native_verification = true;
        },
      ],
      [
        'asset',
        (evidence) => {
          evidence.assets[0].release_ready = true;
        },
      ],
    ]) {
      const mutatedEvidence = structuredClone(packageEvidence);
      mutate(mutatedEvidence);
      writeFileSync(linuxEvidencePath, JSON.stringify(mutatedEvidence));
      const mutationResult = validate();
      assert.notEqual(mutationResult.status, 0, label);
      assert.match(mutationResult.stderr, /unexpected field/u, label);
      writeFileSync(linuxEvidencePath, JSON.stringify(packageEvidence));
    }

    const packageBooleanFields = {
      macos: 'same_signature_identity',
      windows: 'installer_authenticode_valid',
      linux: 'sidecar_executable',
    };
    for (const platform of Object.keys(packageBooleanFields)) {
      const evidencePath = join(root, 'verified', platform, `release-evidence-${platform}.json`);
      const originalEvidence = JSON.parse(readFileSync(evidencePath, 'utf8'));
      const mutatedEvidence = structuredClone(originalEvidence);
      mutatedEvidence.package_verification.native_verification = true;
      writeFileSync(evidencePath, JSON.stringify(mutatedEvidence));
      const mutationResult = validate();
      assert.notEqual(mutationResult.status, 0, platform);
      assert.match(
        mutationResult.stderr,
        new RegExp(`${platform} package verification.*unexpected field`, 'u'),
        platform,
      );
      writeFileSync(evidencePath, JSON.stringify(originalEvidence));

      const mistypedEvidence = structuredClone(originalEvidence);
      mistypedEvidence.package_verification[packageBooleanFields[platform]] = 'true';
      writeFileSync(evidencePath, JSON.stringify(mistypedEvidence));
      const mistypedResult = validate();
      assert.notEqual(mistypedResult.status, 0, platform);
      assert.match(mistypedResult.stderr, /must be true/u, platform);
      writeFileSync(evidencePath, JSON.stringify(originalEvidence));
    }

    const missingScopeEvidence = structuredClone(packageEvidence);
    delete missingScopeEvidence.blockmap_verification_scope;
    writeFileSync(linuxEvidencePath, JSON.stringify(missingScopeEvidence));
    const missingScope = validate();
    assert.notEqual(missingScope.status, 0);
    assert.match(missingScope.stderr, /missing required field/u);
    writeFileSync(linuxEvidencePath, JSON.stringify(packageEvidence));

    const overstatedBlockmapEvidence = structuredClone(packageEvidence);
    overstatedBlockmapEvidence.blockmap_verification_scope = 'blockmap_chunk_checksums_verified';
    writeFileSync(linuxEvidencePath, JSON.stringify(overstatedBlockmapEvidence));
    const overstatedBlockmapScope = validate();
    assert.notEqual(overstatedBlockmapScope.status, 0);
    assert.match(overstatedBlockmapScope.stderr, /package artifact evidence status is invalid/u);
    writeFileSync(linuxEvidencePath, JSON.stringify(packageEvidence));

    writeFileSync(
      linuxEvidencePath,
      JSON.stringify({
        ...packageEvidence,
        release_disposition: 'publishable',
      }),
    );
    const publishableClaim = validate();
    assert.notEqual(publishableClaim.status, 0);
    assert.match(publishableClaim.stderr, /release evidence must remain prerelease-only/u);
    writeFileSync(linuxEvidencePath, JSON.stringify(packageEvidence));

    writeFileSync(
      join(root, 'verified', 'linux', 'agi-stack-desktop-0.1.0-linux-x64.AppImage'),
      'mutated after package verification',
    );
    const mutated = validate();
    assert.notEqual(mutated.status, 0);
    assert.match(mutated.stderr, /release evidence digest mismatch/u);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('downloaded draft assets are compared by exact size and SHA-256', () => {
  const root = mkdtempSync(join(tmpdir(), 'agistack-remote-release-assets-'));
  const validationRoot = join(root, 'validation');
  const localRoot = join(validationRoot, 'local');
  const outsideRoot = join(root, 'outside');
  const remoteRoot = join(root, 'remote');
  const manifestPath = join(validationRoot, 'verified-assets.json');
  try {
    mkdirSync(localRoot, { recursive: true });
    mkdirSync(outsideRoot, { recursive: true });
    mkdirSync(remoteRoot, { recursive: true });
    const name = 'agi-stack-desktop-0.1.0-linux-x64.AppImage';
    const content = Buffer.from('verified package bytes');
    const localPath = join(localRoot, name);
    const digest = createHash('sha256').update(content).digest('hex');
    const writeManifest = (assetName, assetPath) => {
      writeFileSync(
        manifestPath,
        JSON.stringify([
          {
            name: assetName,
            path: assetPath,
            size: content.byteLength,
            sha256: digest,
          },
        ]),
      );
    };
    writeFileSync(localPath, content);
    writeFileSync(join(remoteRoot, name), content);
    writeManifest(name, localPath);

    assert.deepEqual(
      verifyDownloadedReleaseAssets({
        manifestPath,
        remoteRoot,
        mode: 'exact',
      }),
      [name],
    );

    const outsidePath = join(outsideRoot, name);
    writeFileSync(outsidePath, content);
    writeManifest(name, outsidePath);
    assert.throws(
      () =>
        verifyDownloadedReleaseAssets({
          manifestPath,
          remoteRoot,
          mode: 'subset',
        }),
      /outside the validation root/u,
    );

    writeManifest(name, `${localRoot}/../local/${name}`);
    assert.throws(
      () =>
        verifyDownloadedReleaseAssets({
          manifestPath,
          remoteRoot,
          mode: 'subset',
        }),
      /canonical/u,
    );

    writeManifest('renamed.AppImage', localPath);
    assert.throws(
      () =>
        verifyDownloadedReleaseAssets({
          manifestPath,
          remoteRoot,
          mode: 'subset',
        }),
      /path and name do not match/u,
    );

    const symlinkName = 'symlinked.AppImage';
    const symlinkPath = join(localRoot, symlinkName);
    symlinkSync(localPath, symlinkPath);
    writeManifest(symlinkName, symlinkPath);
    assert.throws(
      () =>
        verifyDownloadedReleaseAssets({
          manifestPath,
          remoteRoot,
          mode: 'subset',
        }),
      /regular non-symlink/u,
    );

    writeManifest(name, localPath);
    writeFileSync(join(remoteRoot, name), Buffer.from('mutated package bytes'));
    assert.throws(
      () =>
        verifyDownloadedReleaseAssets({
          manifestPath,
          remoteRoot,
          mode: 'exact',
        }),
      /remote asset (?:size|SHA-256) mismatch/u,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
