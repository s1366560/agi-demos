import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import test from 'node:test';
import { deflateRawSync, gzipSync } from 'node:zlib';
import { parse, stringify } from 'yaml';

import {
  assertMacAudioInputEntitlement,
  buildReleaseEvidence,
  verifyReleaseRootMetadata,
} from '../scripts/verify-release-artifacts.mjs';
import {
  platformPolicy,
  writeReleaseEvidence,
} from '../scripts/release-artifact-contract.mjs';

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
    platform === 'darwin'
      ? name.replace('-universal.', `-${macArchitecture}.`)
      : name,
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
    const compressed = deflateRawSync(
      Buffer.from(JSON.stringify(blockMap(original.byteLength))),
    );
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
      ...(name === embeddedInstaller
        ? { blockMapSize: embeddedBlockMapSize }
        : {}),
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
  nativeVerification,
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
    nativeVerification,
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
  assert.throws(
    () => {
      assertMacAudioInputEntitlement(
        '/Applications/AGI Stack Desktop.app',
        '<key>com.apple.security.device.audio-input</key><false/>',
      );
    },
    /audio-input entitlement is missing/u,
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

test('release metadata requires and validates external updater blockmaps', async () => {
  await withFixture('darwin', async ({ releaseRoot }) => {
    const blockmap = join(
      releaseRoot,
      'agi-stack-desktop-0.1.0-mac-universal.zip.blockmap',
    );
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
    const blockmap = join(
      releaseRoot,
      'agi-stack-desktop-0.1.0-win-x64.exe.blockmap',
    );
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

test('release evidence binds tag CI identity, native checks, and exact asset digests', () => {
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
    nativeVerification: {
      architecture: 'x64',
      appimage_extract_smoke: true,
      deb_extract_smoke: true,
      desktop_entry: 'agi-stack-desktop.desktop',
      sidecar_executable: true,
    },
  };
  const evidence = buildReleaseEvidence(input);
  assert.equal(evidence.contract_version, 'desktop-release-evidence-v1');
  assert.equal(evidence.verification_status, 'verified_by_tag_ci');
  assert.equal(evidence.tag, 'v0.1.0');
  assert.equal(evidence.commit_sha, 'a'.repeat(40));
  assert.deepEqual(evidence.assets.map((asset) => asset.name), [
    'agi-stack-desktop-0.1.0-linux-x64.AppImage',
  ]);

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
      nativeVerification: { package_verification_fixture: true },
    };
    const evidencePath = await writeReleaseEvidence(input);
    assert.equal(basename(evidencePath), 'release-evidence-linux.json');
    assert.equal(statSync(evidencePath).mode & 0o777, 0o444);
    assert.equal(
      JSON.parse(readFileSync(evidencePath, 'utf8')).verification_status,
      'verified_by_tag_ci',
    );
    await assert.rejects(writeReleaseEvidence(input), { code: 'EEXIST' });
  } finally {
    rmSync(fixture.releaseRoot, { recursive: true, force: true });
  }
});

test('publish validation accepts exact evidence and rejects a mutated asset', () => {
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
      nativeVerification: {
        architecture: 'universal',
        app_architectures: ['arm64', 'x86_64'],
        sidecar_architectures: ['arm64', 'x86_64'],
        developer_id_authority:
          'Developer ID Application: Example Company (TEAMID1234)',
        team_identifier: 'TEAMID1234',
        signing_certificate_sha256: 'b'.repeat(64),
        same_signature_identity: true,
        app_signature_valid: true,
        sidecar_signature_valid: true,
        notarization_verified: true,
        app_stapler_valid: true,
        dmg_stapler_valid: true,
        app_spctl_valid: true,
        dmg_spctl_valid: true,
        sidecar_sha256: 'c'.repeat(64),
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
      nativeVerification: {
        architecture: 'x64',
        signer_thumbprint: 'D'.repeat(40),
        installer_authenticode_valid: true,
        sidecar_authenticode_valid: true,
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
      nativeVerification: {
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

    const workflow = parse(
      readFileSync(
        new URL('../../../../.github/workflows/desktop-release.yml', import.meta.url),
        'utf8',
      ),
    );
    const validationScript = workflow.jobs.publish.steps.find(
      (step) => step.name === 'Validate the combined release asset set',
    ).run;
    const env = {
      ...process.env,
      AGISTACK_RELEASE_VERSION: VERSION,
      APPLE_TEAM_ID: 'TEAMID1234',
      WIN_CSC_SHA1: 'D'.repeat(40),
      GITHUB_REPOSITORY: 'example/repository',
      GITHUB_REF_NAME: `v${VERSION}`,
      GITHUB_SHA: 'a'.repeat(40),
      GITHUB_RUN_ID: '12345',
      GITHUB_RUN_ATTEMPT: '2',
    };
    const validate = () =>
      spawnSync(
        process.execPath,
        ['--input-type=commonjs', '--eval', validationScript],
        { cwd: root, encoding: 'utf8', env },
      );

    const valid = validate();
    assert.equal(valid.status, 0, valid.stderr);
    writeFileSync(
      join(
        root,
        'verified',
        'linux',
        'agi-stack-desktop-0.1.0-linux-x64.AppImage',
      ),
      'mutated after native verification',
    );
    const mutated = validate();
    assert.notEqual(mutated.status, 0);
    assert.match(mutated.stderr, /release evidence digest mismatch/u);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
