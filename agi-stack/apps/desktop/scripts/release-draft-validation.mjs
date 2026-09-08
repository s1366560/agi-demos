import { createHash } from 'node:crypto';
import {
  existsSync,
  lstatSync,
  readFileSync,
  readdirSync,
  realpathSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import { verifyReleaseRootMetadata } from './release-artifact-contract.mjs';

const PLATFORM_POLICIES = Object.freeze({ macos: 'darwin', windows: 'win32', linux: 'linux' });
const VERIFIED_ASSET_MANIFEST_KEYS = Object.freeze(['name', 'path', 'size', 'sha256']);

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function assertExactRecordKeys(value, expectedKeys, label) {
  if (!isRecord(value)) {
    throw new Error(`${label} must be an object`);
  }
  const expected = new Set(expectedKeys);
  for (const key of Object.keys(value)) {
    if (!expected.has(key)) {
      throw new Error(`${label} contains unexpected field: ${key}`);
    }
  }
  for (const key of expectedKeys) {
    if (!Object.hasOwn(value, key)) {
      throw new Error(`${label} is missing required field: ${key}`);
    }
  }
}

function fileDigest(path, algorithm, encoding) {
  return createHash(algorithm).update(readFileSync(path)).digest(encoding);
}

export async function validateCombinedReleaseAssets({ root = process.cwd(), env = process.env } = {}) {
  const resolvedRoot = resolve(root);
  const version = env.AGISTACK_RELEASE_VERSION;
  if (typeof version !== 'string' || !version || env.GITHUB_REF_NAME !== `v${version}`) {
    throw new Error('release tag must match the authorized version');
  }
  const owners = new Set();
  const manifest = [];
  for (const [name, platform] of Object.entries(PLATFORM_POLICIES)) {
    const directory = join(resolvedRoot, 'verified', name);
    const stats = lstatSync(directory);
    if (!stats.isDirectory() || stats.isSymbolicLink()) {
      throw new Error(`release platform directory must be a non-symlink directory: ${name}`);
    }
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (!entry.isFile() || entry.isSymbolicLink()) {
        throw new Error(`unexpected ${name} release entry: ${entry.name}`);
      }
    }
    const result = await verifyReleaseRootMetadata({
      releaseRoot: directory, platform, version, expectedVersion: version,
      expectedTag: env.GITHUB_REF_NAME,
    });
    for (const path of result.publishableArtifacts) {
      const name = basename(path);
      if (owners.has(name)) throw new Error(`release asset basename collision: ${name}`);
      owners.add(name);
      manifest.push({ name, path, size: statSync(path).size, sha256: fileDigest(path, 'sha256', 'hex') });
    }
  }
  manifest.sort((left, right) => left.name.localeCompare(right.name));
  writeFileSync(join(resolvedRoot, 'verified-assets.txt'), `${manifest.map(({ name }) => name).join('\n')}\n`);
  writeFileSync(join(resolvedRoot, 'verified-asset-paths.txt'), `${manifest.map(({ path }) => path).join('\n')}\n`);
  writeFileSync(join(resolvedRoot, 'verified-assets.json'), JSON.stringify(manifest));
  return manifest;
}

function pathStaysWithin(root, candidate) {
  const relativePath = relative(root, candidate);
  return (
    relativePath !== '' &&
    relativePath !== '..' &&
    !relativePath.startsWith(`..${sep}`) &&
    !isAbsolute(relativePath)
  );
}

function readAssetManifest(path) {
  const resolvedManifestPath = resolve(path);
  if (path !== resolvedManifestPath) {
    throw new Error('verified asset manifest path must be canonical');
  }
  const manifestStats = lstatSync(resolvedManifestPath);
  if (!manifestStats.isFile() || manifestStats.isSymbolicLink()) {
    throw new Error('verified asset manifest must be a regular non-symlink');
  }
  const validationRoot = dirname(resolvedManifestPath);
  const physicalValidationRoot = realpathSync(validationRoot);
  const manifest = JSON.parse(readFileSync(resolvedManifestPath, 'utf8'));
  if (!Array.isArray(manifest) || manifest.length === 0) {
    throw new Error('verified asset manifest is invalid');
  }
  const names = new Set();
  for (const asset of manifest) {
    assertExactRecordKeys(asset, VERIFIED_ASSET_MANIFEST_KEYS, 'verified asset manifest entry');
    if (
      typeof asset.name !== 'string' ||
      basename(asset.name) !== asset.name ||
      typeof asset.path !== 'string' ||
      !Number.isSafeInteger(asset.size) ||
      asset.size <= 0 ||
      !/^[a-f0-9]{64}$/u.test(asset.sha256 ?? '') ||
      names.has(asset.name)
    ) {
      throw new Error('verified asset manifest entry is invalid');
    }
    const resolvedAssetPath = resolve(asset.path);
    if (asset.path !== resolvedAssetPath) {
      throw new Error(`verified asset path must be canonical: ${asset.name}`);
    }
    if (basename(resolvedAssetPath) !== asset.name) {
      throw new Error(`verified asset path and name do not match: ${asset.name}`);
    }
    if (!pathStaysWithin(validationRoot, resolvedAssetPath)) {
      throw new Error(`verified asset is outside the validation root: ${asset.name}`);
    }
    const sourceStats = lstatSync(resolvedAssetPath);
    if (!sourceStats.isFile() || sourceStats.isSymbolicLink()) {
      throw new Error(`verified asset must be a regular non-symlink: ${asset.name}`);
    }
    if (!pathStaysWithin(physicalValidationRoot, realpathSync(resolvedAssetPath))) {
      throw new Error(`verified asset is outside the validation root: ${asset.name}`);
    }
    if (
      sourceStats.size !== asset.size ||
      fileDigest(resolvedAssetPath, 'sha256', 'hex') !== asset.sha256
    ) {
      throw new Error(`verified asset source digest mismatch: ${asset.name}`);
    }
    names.add(asset.name);
  }
  return manifest;
}

export function verifyDownloadedReleaseAssets({ manifestPath, remoteRoot, mode }) {
  if (!['subset', 'exact'].includes(mode)) {
    throw new Error(`unknown remote verification mode: ${mode}`);
  }
  const manifest = readAssetManifest(manifestPath);
  const expectedByName = new Map(manifest.map((asset) => [asset.name, asset]));
  const remoteNames = readdirSync(remoteRoot)
    .filter((name) => statSync(join(remoteRoot, name)).isFile())
    .sort();
  for (const name of remoteNames) {
    if (basename(name) !== name || !expectedByName.has(name)) {
      throw new Error(`unexpected existing asset: ${name}`);
    }
    const path = join(remoteRoot, name);
    const expectedAsset = expectedByName.get(name);
    if (statSync(path).size !== expectedAsset.size) {
      throw new Error(`remote asset size mismatch: ${name}`);
    }
    if (fileDigest(path, 'sha256', 'hex') !== expectedAsset.sha256) {
      throw new Error(`remote asset SHA-256 mismatch: ${name}`);
    }
  }
  if (
    mode === 'exact' &&
    (remoteNames.length !== manifest.length ||
      manifest.some((asset) => !remoteNames.includes(asset.name)))
  ) {
    throw new Error('remote release asset set is not exact');
  }
  return remoteNames;
}

export function listMissingReleaseAssetPaths({ manifestPath, remoteRoot }) {
  return readAssetManifest(manifestPath)
    .filter((asset) => !existsSync(join(remoteRoot, asset.name)))
    .map((asset) => asset.path);
}

async function main() {
  const command = process.argv[2];
  const manifestPath = resolve('verified-assets.json');
  if (command === 'validate-combined') {
    await validateCombinedReleaseAssets();
    return;
  }
  if (command === 'verify-remote') {
    verifyDownloadedReleaseAssets({
      manifestPath,
      mode: process.argv[3],
      remoteRoot: resolve(process.argv[4]),
    });
    return;
  }
  if (command === 'list-missing') {
    for (const path of listMissingReleaseAssetPaths({
      manifestPath,
      remoteRoot: resolve(process.argv[3]),
    })) {
      process.stdout.write(`${path}\n`);
    }
    return;
  }
  throw new Error(`unknown release draft validation command: ${command}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
