import assert from 'node:assert/strict';
import { createHash, generateKeyPairSync, sign } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
  assertReleaseInputs,
  createEnterprisePolicyBundle,
  createEnterprisePolicyReleaseArtifacts,
  createLinuxManagedPolicyBundle,
  createMacOsConfigurationProfile,
  createUpdateManifest,
  extensionIdFromPublicKey,
  validateUpdateManifest,
  validateLinuxManagedPolicyBundle,
  validateMacOsConfigurationProfile,
  verifyCrx3,
} from './browser-release-contract.mjs';

const config = readFileSync(new URL('../wxt.config.ts', import.meta.url), 'utf8');
const publicKey = config.match(/const EXTENSION_KEY =\s*\n\s*'([^']+)'/u)?.[1];
assert.ok(publicKey, 'pinned extension public key is present');

const extensionId = 'enbljdpbhdllbbkcjhccmbgpkfmcdkkl';
const updateUrl = 'https://updates.memstack.example/browser/update.xml';
const crxUrl = 'https://updates.memstack.example/browser/memstack-browser-bridge.crx';

test('public key deterministically binds the pinned extension id', () => {
  assert.equal(extensionIdFromPublicKey(publicKey), extensionId);
});

test('enterprise policy bundle covers all Chromium-family targets and native messaging', () => {
  const bundle = createEnterprisePolicyBundle({ extensionId, updateUrl });
  assert.deepEqual(Object.keys(bundle), ['chrome', 'edge', 'chromium', 'brave']);
  for (const policy of Object.values(bundle)) {
    assert.deepEqual(policy.ExtensionInstallForcelist, [`${extensionId};${updateUrl}`]);
    assert.deepEqual(policy.NativeMessagingAllowlist, ['com.memstack.browserbridge']);
    assert.deepEqual(policy.NativeMessagingBlocklist, ['*']);
    assert.equal(policy.ExtensionSettings[extensionId].installation_mode, 'force_installed');
    assert.equal(policy.ExtensionSettings[extensionId].update_url, updateUrl);
  }
});

test('macOS and Linux enterprise artifacts are deterministic and contract-validated', () => {
  const macos = createMacOsConfigurationProfile({ extensionId, updateUrl });
  assert.equal(macos, createMacOsConfigurationProfile({ extensionId, updateUrl }));
  validateMacOsConfigurationProfile(macos, { extensionId, updateUrl });
  assert.match(macos, /com\.google\.Chrome/u);
  assert.match(macos, /com\.microsoft\.Edge/u);
  assert.match(macos, /com\.brave\.Browser/u);
  assert.match(macos, /org\.chromium\.Chromium/u);

  const linux = createLinuxManagedPolicyBundle({ extensionId, updateUrl });
  assert.deepEqual(Object.keys(linux), ['chrome', 'edge', 'chromium', 'brave']);
  validateLinuxManagedPolicyBundle(linux, { extensionId, updateUrl });
  for (const artifact of Object.values(linux)) {
    assert.match(artifact.installPath, /^\/etc\//u);
    assert.deepEqual(artifact.policy.ExtensionInstallForcelist, [`${extensionId};${updateUrl}`]);
  }
});

test('enterprise release artifacts bind every policy member and its immutable bytes', () => {
  const artifacts = createEnterprisePolicyReleaseArtifacts({
    extensionId,
    updateUrl,
  });
  assert.equal(artifacts.bundle.contract_version, 'browser-bridge-enterprise-policy-bundle-v1');
  assert.equal(
    artifacts.memberManifest.contract_version,
    'browser-bridge-enterprise-policy-member-manifest-v1',
  );
  assert.equal(artifacts.bundle.extension_id, extensionId);
  assert.equal(artifacts.bundle.update_url, updateUrl);
  assert.deepEqual(
    artifacts.bundle.members.map(({ path }) => path),
    artifacts.memberManifest.members.map(({ path }) => path),
  );
  assert.deepEqual(
    artifacts.memberManifest.members.map(({ path }) => path),
    [...artifacts.memberManifest.members.map(({ path }) => path)].sort(),
  );
  assert.ok(artifacts.memberManifest.members.length >= 10);
  for (const member of artifacts.memberManifest.members) {
    assert.match(member.sha256, /^[a-f0-9]{64}$/u);
    assert.ok(member.size > 0);
    const bundled = artifacts.bundle.members.find(({ path }) => path === member.path);
    assert.ok(bundled);
    const bytes = Buffer.from(bundled.content_base64, 'base64');
    assert.equal(bytes.byteLength, member.size);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), member.sha256);
  }
});

test('update manifest validation rejects identity and version drift', () => {
  const manifest = createUpdateManifest({
    extensionId,
    version: '0.1.0',
    crxUrl,
  });
  validateUpdateManifest(manifest, { extensionId, version: '0.1.0', crxUrl });
  assert.throws(
    () =>
      validateUpdateManifest(manifest, {
        extensionId: `a${extensionId.slice(1)}`,
        version: '0.1.0',
        crxUrl,
      }),
    /extension id/u,
  );
  assert.throws(
    () =>
      validateUpdateManifest(manifest, {
        extensionId,
        version: '0.2.0',
        crxUrl,
      }),
    /version/u,
  );
});

test('release inputs fail closed without a separately provisioned CRX', () => {
  assert.throws(
    () =>
      assertReleaseInputs({
        crxPath: '',
        updateManifestPath: '',
        expectedExtensionId: extensionId,
      }),
    /CRX artifact/u,
  );
  assert.throws(
    () =>
      createEnterprisePolicyBundle({
        extensionId,
        updateUrl: 'http://updates.example.test/update.xml',
      }),
    /HTTPS/u,
  );
});

test('CRX3 verification binds signature, payload manifest, identity, and version', () => {
  const { privateKey, publicKey: publicKeyObject } = generateKeyPairSync('rsa', {
    modulusLength: 2048,
  });
  const publicKeyBytes = publicKeyObject.export({
    format: 'der',
    type: 'spki',
  });
  const syntheticId = extensionIdFromPublicKey(publicKeyBytes.toString('base64'));
  const zip = storedZip(
    'manifest.json',
    Buffer.from(
      JSON.stringify({
        manifest_version: 3,
        name: 'Synthetic release fixture',
        version: '1.2.3',
        key: publicKeyBytes.toString('base64'),
      }),
    ),
  );
  const crxId = extensionIdBytes(syntheticId);
  const signedHeader = protobufBytesField(1, crxId);
  const signatureInput = Buffer.concat([
    Buffer.from('CRX3 SignedData\0', 'ascii'),
    uint32Le(signedHeader.length),
    signedHeader,
    zip,
  ]);
  const proof = Buffer.concat([
    protobufBytesField(1, publicKeyBytes),
    protobufBytesField(2, sign('sha256', signatureInput, privateKey)),
  ]);
  const header = Buffer.concat([
    protobufBytesField(2, proof),
    protobufBytesField(10000, signedHeader),
  ]);
  const crx = Buffer.concat([
    Buffer.from('Cr24'),
    uint32Le(3),
    uint32Le(header.length),
    header,
    zip,
  ]);

  const result = verifyCrx3(crx, {
    expectedExtensionId: syntheticId,
    expectedVersion: '1.2.3',
  });
  assert.equal(result.extensionId, syntheticId);
  assert.equal(result.version, '1.2.3');
  assert.match(result.sha256, /^[a-f0-9]{64}$/u);
});

function uint32Le(value) {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32LE(value);
  return buffer;
}

function uint16Le(value) {
  const buffer = Buffer.alloc(2);
  buffer.writeUInt16LE(value);
  return buffer;
}

function varint(value) {
  let current = BigInt(value);
  const bytes = [];
  do {
    let byte = Number(current & 0x7fn);
    current >>= 7n;
    if (current !== 0n) byte |= 0x80;
    bytes.push(byte);
  } while (current !== 0n);
  return Buffer.from(bytes);
}

function protobufBytesField(field, bytes) {
  return Buffer.concat([varint((BigInt(field) << 3n) | 2n), varint(bytes.length), bytes]);
}

function extensionIdBytes(id) {
  const bytes = Buffer.alloc(16);
  for (let index = 0; index < bytes.length; index += 1) {
    const high = id.charCodeAt(index * 2) - 97;
    const low = id.charCodeAt(index * 2 + 1) - 97;
    bytes[index] = (high << 4) | low;
  }
  return bytes;
}

function storedZip(name, content) {
  const nameBytes = Buffer.from(name);
  const local = Buffer.concat([
    uint32Le(0x04034b50),
    uint16Le(20),
    uint16Le(0),
    uint16Le(0),
    uint16Le(0),
    uint16Le(0),
    uint32Le(0),
    uint32Le(content.length),
    uint32Le(content.length),
    uint16Le(nameBytes.length),
    uint16Le(0),
    nameBytes,
    content,
  ]);
  const central = Buffer.concat([
    uint32Le(0x02014b50),
    uint16Le(20),
    uint16Le(20),
    uint16Le(0),
    uint16Le(0),
    uint16Le(0),
    uint16Le(0),
    uint32Le(0),
    uint32Le(content.length),
    uint32Le(content.length),
    uint16Le(nameBytes.length),
    uint16Le(0),
    uint16Le(0),
    uint16Le(0),
    uint16Le(0),
    uint32Le(0),
    uint32Le(0),
    nameBytes,
  ]);
  const eocd = Buffer.concat([
    uint32Le(0x06054b50),
    uint16Le(0),
    uint16Le(0),
    uint16Le(1),
    uint16Le(1),
    uint32Le(central.length),
    uint32Le(local.length),
    uint16Le(0),
  ]);
  return Buffer.concat([local, central, eocd]);
}
