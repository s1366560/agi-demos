import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import {
  mkdtempSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { stringify } from 'yaml';

import {
  assertMacAudioInputEntitlement,
  verifyReleaseRootMetadata,
} from '../scripts/verify-release-artifacts.mjs';

const VERSION = '0.1.0';
const PLATFORM_FIXTURES = Object.freeze({
  darwin: {
    metadata: 'latest-mac.yml',
    installers: [
      'agi-stack-desktop-0.1.0-mac-arm64.dmg',
      'agi-stack-desktop-0.1.0-mac-arm64.zip',
    ],
  },
  win32: {
    metadata: 'latest.yml',
    installers: ['agi-stack-desktop-0.1.0-win-x64.exe'],
  },
  linux: {
    metadata: 'latest-linux.yml',
    installers: [
      'agi-stack-desktop-0.1.0-linux-x64.AppImage',
      'agi-stack-desktop-0.1.0-linux-x64.deb',
    ],
  },
});

function sha512(content) {
  return createHash('sha512').update(content).digest('base64');
}

function createFixture(platform) {
  const fixture = PLATFORM_FIXTURES[platform];
  const releaseRoot = mkdtempSync(join(tmpdir(), `agistack-release-${platform}-`));
  const files = fixture.installers.map((name, index) => {
    const content = Buffer.from(`${platform}-installer-${index}`);
    writeFileSync(join(releaseRoot, name), content);
    return {
      url: name,
      sha512: sha512(content),
      size: content.byteLength,
    };
  });
  if (platform === 'win32') {
    writeFileSync(join(releaseRoot, `${files[0].url}.blockmap`), 'blockmap');
  }
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
