import { createHash, createPublicKey, verify as verifySignature } from 'node:crypto';
import {
  mkdirSync,
  readFileSync,
  writeFileSync,
} from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { inflateRawSync } from 'node:zlib';

const EXTENSION_ID_PATTERN = /^[a-p]{32}$/u;
const VERSION_PATTERN = /^\d+(?:\.\d+){1,3}$/u;
const NATIVE_HOST_NAME = 'com.memstack.browserbridge';
const CRX3_MAGIC = 'Cr24';
const CRX3_VERSION = 3;
const CRX3_SIGNED_DATA_PREFIX = Buffer.from('CRX3 SignedData\0', 'ascii');

const POLICY_TARGETS = Object.freeze({
  chrome: String.raw`Software\Policies\Google\Chrome`,
  edge: String.raw`Software\Policies\Microsoft\Edge`,
  chromium: String.raw`Software\Policies\Chromium`,
  brave: String.raw`Software\Policies\BraveSoftware\Brave`,
});

const MACOS_POLICY_TARGETS = Object.freeze([
  {
    target: 'chrome',
    domain: 'com.google.Chrome',
    identifier: 'ai.memstack.browser-bridge.chrome',
    uuid: '609B9AC8-7E89-4C2C-9CBB-DA5075CB6251',
  },
  {
    target: 'edge',
    domain: 'com.microsoft.Edge',
    identifier: 'ai.memstack.browser-bridge.edge',
    uuid: '47DE8249-13B5-4DA2-B6A1-9574665E0F7A',
  },
  {
    target: 'chromium',
    domain: 'org.chromium.Chromium',
    identifier: 'ai.memstack.browser-bridge.chromium',
    uuid: '57F00B50-A97D-41A3-86F1-A8D6D1ED6D1B',
  },
  {
    target: 'brave',
    domain: 'com.brave.Browser',
    identifier: 'ai.memstack.browser-bridge.brave',
    uuid: 'D99A6D13-CF3D-4B11-B3B7-A7D46D1E845B',
  },
]);

const LINUX_POLICY_PATHS = Object.freeze({
  chrome: '/etc/opt/chrome/policies/managed/memstack-browser-bridge.json',
  edge: '/etc/opt/edge/policies/managed/memstack-browser-bridge.json',
  chromium: '/etc/chromium/policies/managed/memstack-browser-bridge.json',
  brave: '/etc/brave/policies/managed/memstack-browser-bridge.json',
});

export function extensionIdFromPublicKey(publicKeyBase64) {
  if (typeof publicKeyBase64 !== 'string' || publicKeyBase64.length === 0) {
    throw new Error('extension public key is missing');
  }
  const publicKey = Buffer.from(publicKeyBase64, 'base64');
  createPublicKey({ key: publicKey, format: 'der', type: 'spki' });
  const prefix = createHash('sha256').update(publicKey).digest().subarray(0, 16);
  return [...prefix]
    .flatMap((byte) => [byte >> 4, byte & 0x0f])
    .map((nibble) => String.fromCharCode('a'.charCodeAt(0) + nibble))
    .join('');
}

export function createEnterprisePolicyBundle({ extensionId, updateUrl }) {
  assertExtensionId(extensionId);
  const update = assertHttpsUrl(updateUrl, 'enterprise extension update URL');
  const policy = () => ({
    ExtensionInstallForcelist: [`${extensionId};${update}`],
    ExtensionSettings: {
      [extensionId]: {
        installation_mode: 'force_installed',
        update_url: update,
      },
    },
    NativeMessagingAllowlist: [NATIVE_HOST_NAME],
    NativeMessagingBlocklist: ['*'],
  });
  return Object.fromEntries(Object.keys(POLICY_TARGETS).map((target) => [target, policy()]));
}

export function createWindowsPolicyReg({ extensionId, updateUrl }) {
  const bundle = createEnterprisePolicyBundle({ extensionId, updateUrl });
  const lines = ['Windows Registry Editor Version 5.00', ''];
  for (const [target, base] of Object.entries(POLICY_TARGETS)) {
    const policy = bundle[target];
    const extensionSettings = JSON.stringify(policy.ExtensionSettings[extensionId]).replaceAll(
      '"',
      '\\"',
    );
    lines.push(
      `[HKEY_CURRENT_USER\\${base}\\ExtensionInstallForcelist]`,
      `"1"="${extensionId};${policy.ExtensionSettings[extensionId].update_url}"`,
      '',
      `[HKEY_CURRENT_USER\\${base}\\NativeMessagingAllowlist]`,
      `"1"="${NATIVE_HOST_NAME}"`,
      '',
      `[HKEY_CURRENT_USER\\${base}\\NativeMessagingBlocklist]`,
      '"1"="*"',
      '',
      `[HKEY_CURRENT_USER\\${base}\\ExtensionSettings]`,
      `"${extensionId}"="${extensionSettings}"`,
      '',
    );
  }
  return `${lines.join('\r\n')}\r\n`;
}

export function createLinuxManagedPolicyBundle({ extensionId, updateUrl }) {
  const bundle = createEnterprisePolicyBundle({ extensionId, updateUrl });
  return Object.fromEntries(
    Object.entries(bundle).map(([target, policy]) => [
      target,
      { installPath: LINUX_POLICY_PATHS[target], policy },
    ]),
  );
}

export function validateLinuxManagedPolicyBundle(bundle, expected) {
  const canonical = createLinuxManagedPolicyBundle(expected);
  if (JSON.stringify(bundle) !== JSON.stringify(canonical)) {
    throw new Error('Linux managed-policy bundle is not the canonical fail-closed contract');
  }
}

export function createMacOsConfigurationProfile({ extensionId, updateUrl }) {
  const bundle = createEnterprisePolicyBundle({ extensionId, updateUrl });
  const payloads = MACOS_POLICY_TARGETS.map(({ target, domain, identifier, uuid }) =>
    macOsPolicyPayload({ domain, identifier, uuid, extensionId, policy: bundle[target] }),
  ).join('\n');
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
    '<plist version="1.0">',
    '<dict>',
    '  <key>PayloadContent</key>',
    '  <array>',
    payloads,
    '  </array>',
    '  <key>PayloadDisplayName</key>',
    '  <string>MemStack Browser Bridge</string>',
    '  <key>PayloadIdentifier</key>',
    '  <string>ai.memstack.browser-bridge</string>',
    '  <key>PayloadOrganization</key>',
    '  <string>MemStack</string>',
    '  <key>PayloadRemovalDisallowed</key>',
    '  <false/>',
    '  <key>PayloadType</key>',
    '  <string>Configuration</string>',
    '  <key>PayloadUUID</key>',
    '  <string>4612B005-BA77-4F5A-A8B4-FBFD6B2DD51C</string>',
    '  <key>PayloadVersion</key>',
    '  <integer>1</integer>',
    '</dict>',
    '</plist>',
    '',
  ].join('\n');
}

export function validateMacOsConfigurationProfile(profile, expected) {
  if (profile !== createMacOsConfigurationProfile(expected)) {
    throw new Error('macOS configuration profile is not the canonical fail-closed contract');
  }
}

function macOsPolicyPayload({ domain, identifier, uuid, extensionId, policy }) {
  const extensionSettings = policy.ExtensionSettings[extensionId];
  return [
    '    <dict>',
    '      <key>ExtensionInstallForcelist</key>',
    '      <array>',
    `        <string>${escapeXmlText(policy.ExtensionInstallForcelist[0])}</string>`,
    '      </array>',
    '      <key>ExtensionSettings</key>',
    '      <dict>',
    `        <key>${extensionId}</key>`,
    '        <dict>',
    '          <key>installation_mode</key>',
    `          <string>${extensionSettings.installation_mode}</string>`,
    '          <key>update_url</key>',
    `          <string>${escapeXmlText(extensionSettings.update_url)}</string>`,
    '        </dict>',
    '      </dict>',
    '      <key>NativeMessagingAllowlist</key>',
    '      <array>',
    `        <string>${NATIVE_HOST_NAME}</string>`,
    '      </array>',
    '      <key>NativeMessagingBlocklist</key>',
    '      <array>',
    '        <string>*</string>',
    '      </array>',
    '      <key>PayloadDisplayName</key>',
    `      <string>MemStack Browser Bridge (${escapeXmlText(domain)})</string>`,
    '      <key>PayloadIdentifier</key>',
    `      <string>${identifier}</string>`,
    '      <key>PayloadType</key>',
    `      <string>${domain}</string>`,
    '      <key>PayloadUUID</key>',
    `      <string>${uuid}</string>`,
    '      <key>PayloadVersion</key>',
    '      <integer>1</integer>',
    '    </dict>',
  ].join('\n');
}

export function createUpdateManifest({ extensionId, version, crxUrl }) {
  assertExtensionId(extensionId);
  assertVersion(version);
  const codebase = assertHttpsUrl(crxUrl, 'CRX codebase URL');
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<gupdate xmlns="http://www.google.com/update2/response" protocol="2.0">',
    `  <app appid="${extensionId}">`,
    `    <updatecheck codebase="${escapeXmlAttribute(codebase)}" version="${version}"/>`,
    '  </app>',
    '</gupdate>',
    '',
  ].join('\n');
}

export function validateUpdateManifest(manifest, expected) {
  const appId = readAttribute(manifest, '<app ', 'appid');
  if (appId !== expected.extensionId) {
    throw new Error(`update manifest extension id mismatch: ${appId || 'missing'}`);
  }
  const version = readAttribute(manifest, '<updatecheck ', 'version');
  if (version !== expected.version) {
    throw new Error(`update manifest version mismatch: ${version || 'missing'}`);
  }
  const codebase = readAttribute(manifest, '<updatecheck ', 'codebase');
  if (codebase !== expected.crxUrl) {
    throw new Error(`update manifest CRX URL mismatch: ${codebase || 'missing'}`);
  }
  const canonical = createUpdateManifest(expected);
  if (manifest.replaceAll('\r\n', '\n') !== canonical) {
    throw new Error('update manifest is not the canonical fail-closed contract');
  }
}

export function assertReleaseInputs({ crxPath, updateManifestPath, expectedExtensionId }) {
  assertExtensionId(expectedExtensionId);
  if (typeof crxPath !== 'string' || crxPath.length === 0) {
    throw new Error('CRX artifact must be provisioned by the release environment');
  }
  if (typeof updateManifestPath !== 'string' || updateManifestPath.length === 0) {
    throw new Error('update manifest artifact must be provisioned by the release environment');
  }
  return {
    crxPath: resolve(crxPath),
    updateManifestPath: resolve(updateManifestPath),
    expectedExtensionId,
  };
}

export function verifyCrx3(crxBytes, { expectedExtensionId, expectedVersion }) {
  assertExtensionId(expectedExtensionId);
  assertVersion(expectedVersion);
  if (!Buffer.isBuffer(crxBytes) || crxBytes.length < 12) {
    throw new Error('CRX artifact is truncated');
  }
  if (crxBytes.subarray(0, 4).toString('ascii') !== CRX3_MAGIC) {
    throw new Error('CRX artifact has an invalid magic header');
  }
  if (crxBytes.readUInt32LE(4) !== CRX3_VERSION) {
    throw new Error('CRX artifact must use CRX3');
  }
  const headerLength = crxBytes.readUInt32LE(8);
  const headerEnd = 12 + headerLength;
  if (headerLength === 0 || headerEnd >= crxBytes.length) {
    throw new Error('CRX3 header length is invalid');
  }
  const header = crxBytes.subarray(12, headerEnd);
  const zip = crxBytes.subarray(headerEnd);
  const headerFields = readProtobufFields(header);
  const signedHeader = requireSingleBytesField(headerFields, 10000, 'CRX3 signed header');
  const signedFields = readProtobufFields(signedHeader);
  const crxId = requireSingleBytesField(signedFields, 1, 'CRX3 extension id');
  if (crxId.length !== 16) {
    throw new Error('CRX3 extension id must be 16 bytes');
  }
  const signedExtensionId = extensionIdFromCrxId(crxId);
  if (signedExtensionId !== expectedExtensionId) {
    throw new Error(`CRX extension id mismatch: ${signedExtensionId}`);
  }
  const signatureInput = Buffer.concat([
    CRX3_SIGNED_DATA_PREFIX,
    uint32Le(signedHeader.length),
    signedHeader,
    zip,
  ]);
  const rsaProofs = headerFields.get(2) ?? [];
  if (rsaProofs.length === 0) {
    throw new Error('CRX3 RSA proof is missing');
  }
  let verifiedPublicKey = null;
  for (const proofBytes of rsaProofs) {
    const proof = readProtobufFields(proofBytes);
    const publicKey = requireSingleBytesField(proof, 1, 'CRX3 RSA public key');
    const signature = requireSingleBytesField(proof, 2, 'CRX3 RSA signature');
    const publicKeyId = extensionIdFromPublicKey(publicKey.toString('base64'));
    if (publicKeyId !== signedExtensionId) continue;
    const key = createPublicKey({ key: publicKey, format: 'der', type: 'spki' });
    if (verifySignature('sha256', signatureInput, key, signature)) {
      verifiedPublicKey = publicKey;
      break;
    }
  }
  if (verifiedPublicKey === null) {
    throw new Error('CRX3 signature or public-key identity is invalid');
  }
  const manifestBytes = readZipEntry(zip, 'manifest.json');
  let manifest;
  try {
    manifest = JSON.parse(manifestBytes.toString('utf8'));
  } catch (error) {
    throw new Error(`CRX manifest.json is invalid: ${error.message}`);
  }
  if (manifest.version !== expectedVersion) {
    throw new Error(`CRX manifest version mismatch: ${manifest.version || 'missing'}`);
  }
  if (typeof manifest.key !== 'string') {
    throw new Error('CRX manifest public key is missing');
  }
  const manifestExtensionId = extensionIdFromPublicKey(manifest.key);
  if (manifestExtensionId !== expectedExtensionId) {
    throw new Error(`CRX manifest extension id mismatch: ${manifestExtensionId}`);
  }
  if (!Buffer.from(manifest.key, 'base64').equals(verifiedPublicKey)) {
    throw new Error('CRX manifest public key does not match the signing proof');
  }
  return {
    extensionId: expectedExtensionId,
    version: expectedVersion,
    sha256: createHash('sha256').update(crxBytes).digest('hex'),
  };
}

function assertExtensionId(extensionId) {
  if (typeof extensionId !== 'string' || !EXTENSION_ID_PATTERN.test(extensionId)) {
    throw new Error('extension id must contain exactly 32 characters in the a-p alphabet');
  }
}

function assertVersion(version) {
  if (typeof version !== 'string' || !VERSION_PATTERN.test(version)) {
    throw new Error('extension version is invalid');
  }
}

function assertHttpsUrl(value, label) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${label} must be an absolute HTTPS URL`);
  }
  if (url.protocol !== 'https:' || url.username || url.password || url.hash) {
    throw new Error(`${label} must be an absolute HTTPS URL without credentials or fragments`);
  }
  return url.toString();
}

function escapeXmlAttribute(value) {
  return value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
}

function escapeXmlText(value) {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function unescapeXmlAttribute(value) {
  return value.replaceAll('&lt;', '<').replaceAll('&quot;', '"').replaceAll('&amp;', '&');
}

function readAttribute(document, tagPrefix, attribute) {
  if (typeof document !== 'string') return null;
  const tagStart = document.indexOf(tagPrefix);
  if (tagStart < 0) return null;
  const tagEnd = document.indexOf('>', tagStart);
  if (tagEnd < 0) return null;
  const marker = `${attribute}="`;
  const attributeStart = document.indexOf(marker, tagStart + tagPrefix.length);
  if (attributeStart < 0 || attributeStart > tagEnd) return null;
  const valueStart = attributeStart + marker.length;
  const valueEnd = document.indexOf('"', valueStart);
  if (valueEnd < 0 || valueEnd > tagEnd) return null;
  return unescapeXmlAttribute(document.slice(valueStart, valueEnd));
}

function extensionIdFromCrxId(crxId) {
  return [...crxId]
    .flatMap((byte) => [byte >> 4, byte & 0x0f])
    .map((nibble) => String.fromCharCode('a'.charCodeAt(0) + nibble))
    .join('');
}

function readProtobufFields(bytes) {
  const fields = new Map();
  let offset = 0;
  while (offset < bytes.length) {
    const key = readVarint(bytes, offset);
    offset = key.offset;
    const field = Number(key.value >> 3n);
    const wire = Number(key.value & 7n);
    if (!Number.isSafeInteger(field) || field <= 0 || wire !== 2) {
      throw new Error('CRX3 protobuf contains an unsupported field');
    }
    const length = readVarint(bytes, offset);
    offset = length.offset;
    const byteLength = Number(length.value);
    if (!Number.isSafeInteger(byteLength) || byteLength < 0 || offset + byteLength > bytes.length) {
      throw new Error('CRX3 protobuf field is truncated');
    }
    const values = fields.get(field) ?? [];
    values.push(bytes.subarray(offset, offset + byteLength));
    fields.set(field, values);
    offset += byteLength;
  }
  return fields;
}

function readVarint(bytes, start) {
  let value = 0n;
  let shift = 0n;
  for (let offset = start; offset < bytes.length && offset < start + 10; offset += 1) {
    const byte = bytes[offset];
    value |= BigInt(byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) return { value, offset: offset + 1 };
    shift += 7n;
  }
  throw new Error('CRX3 protobuf varint is invalid');
}

function requireSingleBytesField(fields, field, label) {
  const values = fields.get(field) ?? [];
  if (values.length !== 1 || values[0].length === 0) {
    throw new Error(`${label} must appear exactly once`);
  }
  return values[0];
}

function uint32Le(value) {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32LE(value);
  return buffer;
}

function readZipEntry(zip, expectedName) {
  const eocdOffset = findEndOfCentralDirectory(zip);
  const entryCount = zip.readUInt16LE(eocdOffset + 10);
  let offset = zip.readUInt32LE(eocdOffset + 16);
  for (let index = 0; index < entryCount; index += 1) {
    if (offset + 46 > zip.length || zip.readUInt32LE(offset) !== 0x02014b50) {
      throw new Error('CRX ZIP central directory is invalid');
    }
    const compression = zip.readUInt16LE(offset + 10);
    const compressedSize = zip.readUInt32LE(offset + 20);
    const uncompressedSize = zip.readUInt32LE(offset + 24);
    const nameLength = zip.readUInt16LE(offset + 28);
    const extraLength = zip.readUInt16LE(offset + 30);
    const commentLength = zip.readUInt16LE(offset + 32);
    const localOffset = zip.readUInt32LE(offset + 42);
    const nameStart = offset + 46;
    const nameEnd = nameStart + nameLength;
    if (nameEnd > zip.length) throw new Error('CRX ZIP entry name is truncated');
    const name = zip.subarray(nameStart, nameEnd).toString('utf8');
    if (name === expectedName) {
      return readLocalZipEntry(zip, localOffset, compression, compressedSize, uncompressedSize);
    }
    offset = nameEnd + extraLength + commentLength;
  }
  throw new Error(`CRX ZIP is missing ${expectedName}`);
}

function findEndOfCentralDirectory(zip) {
  const minimum = Math.max(0, zip.length - 65_557);
  for (let offset = zip.length - 22; offset >= minimum; offset -= 1) {
    if (zip.readUInt32LE(offset) === 0x06054b50) return offset;
  }
  throw new Error('CRX ZIP end-of-central-directory record is missing');
}

function readLocalZipEntry(zip, offset, compression, compressedSize, uncompressedSize) {
  if (offset + 30 > zip.length || zip.readUInt32LE(offset) !== 0x04034b50) {
    throw new Error('CRX ZIP local entry is invalid');
  }
  const nameLength = zip.readUInt16LE(offset + 26);
  const extraLength = zip.readUInt16LE(offset + 28);
  const dataStart = offset + 30 + nameLength + extraLength;
  const dataEnd = dataStart + compressedSize;
  if (dataEnd > zip.length) throw new Error('CRX ZIP entry data is truncated');
  const compressed = zip.subarray(dataStart, dataEnd);
  const content =
    compression === 0
      ? compressed
      : compression === 8
        ? inflateRawSync(compressed)
        : null;
  if (content === null) throw new Error(`CRX ZIP compression method ${compression} is unsupported`);
  if (content.length !== uncompressedSize) {
    throw new Error('CRX ZIP entry size does not match its central directory');
  }
  return content;
}

function requiredEnvironment(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function writeArtifact(path, content) {
  const resolved = resolve(path);
  mkdirSync(dirname(resolved), { recursive: true });
  writeFileSync(resolved, content, { flag: 'wx' });
  return resolved;
}

function runCli() {
  const command = process.argv[2];
  if (command === 'verify') {
    const inputs = assertReleaseInputs({
      crxPath: requiredEnvironment('AGISTACK_BROWSER_EXTENSION_CRX'),
      updateManifestPath: requiredEnvironment('AGISTACK_BROWSER_EXTENSION_UPDATE_MANIFEST'),
      expectedExtensionId: requiredEnvironment('AGISTACK_BROWSER_EXTENSION_ID'),
    });
    const expectedVersion = requiredEnvironment('AGISTACK_BROWSER_EXTENSION_VERSION');
    const crxUrl = requiredEnvironment('AGISTACK_BROWSER_EXTENSION_CRX_URL');
    const result = verifyCrx3(readFileSync(inputs.crxPath), {
      expectedExtensionId: inputs.expectedExtensionId,
      expectedVersion,
    });
    const updateManifest = readFileSync(inputs.updateManifestPath, 'utf8');
    validateUpdateManifest(updateManifest, {
      extensionId: inputs.expectedExtensionId,
      version: expectedVersion,
      crxUrl,
    });
    process.stdout.write(`${JSON.stringify(result)}\n`);
    return;
  }
  if (command === 'generate-policy') {
    const extensionId = requiredEnvironment('AGISTACK_BROWSER_EXTENSION_ID');
    const updateUrl = requiredEnvironment('AGISTACK_BROWSER_EXTENSION_UPDATE_URL');
    const outputDirectory = resolve(requiredEnvironment('AGISTACK_BROWSER_POLICY_OUTPUT_DIR'));
    const bundle = createEnterprisePolicyBundle({ extensionId, updateUrl });
    mkdirSync(outputDirectory, { recursive: true });
    for (const [target, policy] of Object.entries(bundle)) {
      writeArtifact(resolve(outputDirectory, `${target}.managed-policy.json`), `${JSON.stringify(policy, null, 2)}\n`);
    }
    const linux = createLinuxManagedPolicyBundle({ extensionId, updateUrl });
    validateLinuxManagedPolicyBundle(linux, { extensionId, updateUrl });
    for (const [target, artifact] of Object.entries(linux)) {
      writeArtifact(
        resolve(outputDirectory, 'linux', `${target}.managed-policy.json`),
        `${JSON.stringify(artifact.policy, null, 2)}\n`,
      );
    }
    const macos = createMacOsConfigurationProfile({ extensionId, updateUrl });
    validateMacOsConfigurationProfile(macos, { extensionId, updateUrl });
    writeArtifact(resolve(outputDirectory, 'macos-configuration-profile.mobileconfig'), macos);
    writeArtifact(
      resolve(outputDirectory, 'windows-current-user-policy.reg'),
      createWindowsPolicyReg({ extensionId, updateUrl }),
    );
    return;
  }
  if (command === 'generate-update-manifest') {
    const outputPath = requiredEnvironment('AGISTACK_BROWSER_EXTENSION_UPDATE_MANIFEST');
    writeArtifact(
      outputPath,
      createUpdateManifest({
        extensionId: requiredEnvironment('AGISTACK_BROWSER_EXTENSION_ID'),
        version: requiredEnvironment('AGISTACK_BROWSER_EXTENSION_VERSION'),
        crxUrl: requiredEnvironment('AGISTACK_BROWSER_EXTENSION_CRX_URL'),
      }),
    );
    return;
  }
  throw new Error('expected command: verify, generate-policy, or generate-update-manifest');
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  try {
    runCli();
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
