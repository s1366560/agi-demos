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

import {
  buildReleasePackageEvidenceIndex,
  writeReleasePackageEvidenceIndex,
} from './release-evidence-index.mjs';

const PLATFORM_POLICIES = Object.freeze({
  macos: Object.freeze({
    evidence: 'release-evidence-macos.json',
    required: Object.freeze([/\.dmg$/u, /\.zip$/u, /\.zip\.blockmap$/u, /^latest-mac\.yml$/u]),
  }),
  windows: Object.freeze({
    evidence: 'release-evidence-windows.json',
    required: Object.freeze([/\.exe$/u, /\.exe\.blockmap$/u, /^latest\.yml$/u]),
  }),
  linux: Object.freeze({
    evidence: 'release-evidence-linux.json',
    required: Object.freeze([/\.AppImage$/u, /\.deb$/u, /^latest-linux\.yml$/u]),
  }),
});

const RELEASE_EVIDENCE_KEYS = Object.freeze([
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
const WORKFLOW_RUN_KEYS = Object.freeze(['id', 'attempt', 'url']);
const ASSET_KEYS = Object.freeze(['name', 'size', 'sha512']);
const VERIFICATION_CHECK_KEYS = Object.freeze(['id', 'status', 'reason_code']);
const VERIFIED_ASSET_MANIFEST_KEYS = Object.freeze(['name', 'path', 'size', 'sha256']);
const PACKAGE_VERIFICATION_KEYS = Object.freeze({
  macos: Object.freeze([
    'architecture',
    'app_architectures',
    'sidecar_architectures',
    'developer_id_authority',
    'team_identifier',
    'signing_certificate_sha256',
    'same_signature_identity',
    'app_signature_valid',
    'sidecar_signature_valid',
    'notarization_verified',
    'app_stapler_valid',
    'dmg_stapler_valid',
    'app_spctl_valid',
    'dmg_spctl_valid',
    'sidecar_sha256',
    'zip_sidecar_sha256',
    'dmg_sidecar_sha256',
    'package_sidecars_identical',
    'zip_app_verified',
    'dmg_app_verified',
  ]),
  windows: Object.freeze([
    'architecture',
    'signer_thumbprint',
    'installer_authenticode_valid',
    'sidecar_authenticode_valid',
    'sidecar_sha256',
    'sidecar_architecture',
    'installer_payload_extracted',
    'installer_payload_archive',
  ]),
  linux: Object.freeze([
    'architecture',
    'deb_architecture',
    'sidecar_executable',
    'package_sidecars_identical',
    'appimage_executable',
    'appimage_extract_smoke',
    'deb_extract_smoke',
    'appimage_desktop_entry',
    'deb_desktop_entry',
    'sidecar_sha256',
  ]),
});

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

function assertTrueFields(value, fields, platform) {
  for (const field of fields) {
    if (value[field] !== true) {
      throw new Error(`${platform} package evidence ${field} must be true`);
    }
  }
}

function assertSidecarDigest(value, platform) {
  if (!/^[a-f0-9]{64}$/u.test(value.sidecar_sha256 ?? '')) {
    throw new Error(`${platform} sidecar SHA-256 evidence is invalid`);
  }
}

function validateMacPackageEvidence(verification) {
  const expectedArchitectures = JSON.stringify(['arm64', 'x86_64']);
  if (
    verification.architecture !== 'universal' ||
    JSON.stringify(verification.app_architectures) !== expectedArchitectures ||
    JSON.stringify(verification.sidecar_architectures) !== expectedArchitectures
  ) {
    throw new Error('macOS app and sidecar must both be universal');
  }
  if (
    !/^[A-Z0-9]{10}$/u.test(verification.team_identifier ?? '') ||
    !/^[a-f0-9]{64}$/u.test(verification.signing_certificate_sha256 ?? '') ||
    !/^Developer ID Application:\s+\S/u.test(verification.developer_id_authority ?? '') ||
    !verification.developer_id_authority.endsWith(`(${verification.team_identifier})`)
  ) {
    throw new Error('macOS release identity evidence is invalid');
  }
  if (
    verification.zip_sidecar_sha256 !== verification.sidecar_sha256 ||
    verification.dmg_sidecar_sha256 !== verification.sidecar_sha256
  ) {
    throw new Error('macOS zip and dmg sidecar digest evidence does not match');
  }
  assertTrueFields(
    verification,
    [
      'same_signature_identity',
      'app_signature_valid',
      'sidecar_signature_valid',
      'package_sidecars_identical',
      'zip_app_verified',
      'dmg_app_verified',
      'notarization_verified',
      'app_stapler_valid',
      'dmg_stapler_valid',
      'app_spctl_valid',
      'dmg_spctl_valid',
    ],
    'macos',
  );
}

function validateWindowsPackageEvidence(verification) {
  if (
    !/^[A-F0-9]{40}$/u.test(verification.signer_thumbprint ?? '') ||
    !['x64', 'arm64'].includes(verification.architecture)
  ) {
    throw new Error('Windows Authenticode identity evidence is invalid');
  }
  assertTrueFields(
    verification,
    ['installer_authenticode_valid', 'sidecar_authenticode_valid', 'installer_payload_extracted'],
    'windows',
  );
  const expectedPayloadArchive = verification.architecture === 'x64' ? 'app-64.7z' : 'app-arm64.7z';
  if (
    verification.sidecar_architecture !== verification.architecture ||
    verification.installer_payload_archive !== expectedPayloadArchive
  ) {
    throw new Error('Windows NSIS payload architecture evidence does not match');
  }
}

function validateLinuxPackageEvidence(verification) {
  if (
    !['x64', 'arm64'].includes(verification.architecture) ||
    (verification.architecture === 'x64'
      ? verification.deb_architecture !== 'amd64'
      : verification.deb_architecture !== 'arm64')
  ) {
    throw new Error('Linux package architecture evidence does not match');
  }
  assertTrueFields(
    verification,
    [
      'sidecar_executable',
      'package_sidecars_identical',
      'appimage_executable',
      'appimage_extract_smoke',
      'deb_extract_smoke',
    ],
    'linux',
  );
  for (const field of ['appimage_desktop_entry', 'deb_desktop_entry']) {
    const name = verification[field];
    if (typeof name !== 'string' || basename(name) !== name || !name.endsWith('.desktop')) {
      throw new Error(`Linux ${field} evidence is invalid`);
    }
  }
}

function validatePackageEvidence(platform, verification) {
  assertExactRecordKeys(
    verification,
    PACKAGE_VERIFICATION_KEYS[platform],
    `${platform} package verification`,
  );
  assertSidecarDigest(verification, platform);
  if (platform === 'macos') {
    validateMacPackageEvidence(verification);
  } else if (platform === 'windows') {
    validateWindowsPackageEvidence(verification);
  } else {
    validateLinuxPackageEvidence(verification);
  }
}

function readEvidence(path, platform) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    throw new Error(`${platform} release evidence is invalid JSON`);
  }
}

function assertEvidenceIdentity(evidence, platform, env) {
  const expectedTag = `v${env.AGISTACK_RELEASE_VERSION}`;
  const expectedRunUrl =
    `https://github.com/${env.GITHUB_REPOSITORY}` + `/actions/runs/${env.GITHUB_RUN_ID}`;
  assertExactRecordKeys(evidence, RELEASE_EVIDENCE_KEYS, `${platform} release evidence`);
  if (evidence.contract_version !== 'desktop-release-package-evidence-v1') {
    throw new Error(`${platform} release evidence contract is invalid`);
  }
  if (
    evidence.release_disposition !== 'prerelease_only' ||
    evidence.release_blocker_reason_code !== 'stable_promotion_native_evidence_required' ||
    JSON.stringify(evidence.required_native_checks) !==
      JSON.stringify(['install', 'launch', 'updater_apply', 'updater_failure_rollback'])
  ) {
    throw new Error(`${platform} release evidence must remain prerelease-only`);
  }
  if (
    evidence.evidence_scope !== 'package_artifacts_and_promotion_requirements' ||
    evidence.blockmap_verification_scope !== 'blockmap_structure_and_coverage_only' ||
    evidence.artifact_verification_status !== 'verified_by_tag_ci'
  ) {
    throw new Error(`${platform} package artifact evidence status is invalid`);
  }
  const expectedChecks = [
    ['package_artifacts', 'passed', null],
    ['install', 'blocked', 'native_install_evidence_missing'],
    ['launch', 'blocked', 'native_launch_evidence_missing'],
    ['updater_apply', 'blocked', 'updater_apply_evidence_missing'],
    [
      'updater_failure_rollback',
      'blocked',
      'updater_failure_rollback_evidence_missing',
    ],
  ];
  if (!Array.isArray(evidence.verification_checks) || evidence.verification_checks.length !== 5) {
    throw new Error(`${platform} release verification checks are invalid`);
  }
  evidence.verification_checks.forEach((check, index) => {
    assertExactRecordKeys(check, VERIFICATION_CHECK_KEYS, `${platform} verification check`);
    if (JSON.stringify([check.id, check.status, check.reason_code]) !== JSON.stringify(expectedChecks[index])) {
      throw new Error(`${platform} release verification checks are invalid`);
    }
  });
  assertExactRecordKeys(
    evidence.workflow_run,
    WORKFLOW_RUN_KEYS,
    `${platform} release evidence workflow_run`,
  );
  if (
    evidence.platform !== platform ||
    evidence.version !== env.AGISTACK_RELEASE_VERSION ||
    evidence.tag !== expectedTag ||
    evidence.tag !== env.GITHUB_REF_NAME ||
    evidence.commit_sha !== env.GITHUB_SHA ||
    evidence.workflow_run.id !== env.GITHUB_RUN_ID ||
    evidence.workflow_run.attempt !== env.GITHUB_RUN_ATTEMPT ||
    evidence.workflow_run.url !== expectedRunUrl
  ) {
    throw new Error(`${platform} release evidence CI identity does not match`);
  }
}

function assertEvidenceAssets({ evidence, directory, platform, publishableNames }) {
  if (!Array.isArray(evidence.assets)) {
    throw new Error(`${platform} release evidence assets must be an array`);
  }
  const claimedAssets = new Map();
  for (const asset of evidence.assets) {
    assertExactRecordKeys(asset, ASSET_KEYS, `${platform} release evidence asset`);
    if (
      typeof asset.name !== 'string' ||
      basename(asset.name) !== asset.name ||
      !Number.isSafeInteger(asset.size) ||
      asset.size <= 0 ||
      !/^[A-Za-z0-9+/]{86}==$/u.test(asset.sha512 ?? '') ||
      claimedAssets.has(asset.name)
    ) {
      throw new Error(`${platform} release evidence asset is invalid`);
    }
    claimedAssets.set(asset.name, asset);
  }
  if (
    claimedAssets.size !== publishableNames.length ||
    publishableNames.some((name) => !claimedAssets.has(name))
  ) {
    throw new Error(`${platform} release evidence asset set does not match`);
  }
  for (const name of publishableNames) {
    const path = join(directory, name);
    const claimed = claimedAssets.get(name);
    if (
      statSync(path).size !== claimed.size ||
      fileDigest(path, 'sha512', 'base64') !== claimed.sha512
    ) {
      throw new Error(`${platform} release evidence digest mismatch: ${name}`);
    }
  }
}

function expectedPlatformAssetNames(platform, evidence) {
  const prefix = `agi-stack-desktop-${evidence.version}`;
  const architecture = evidence.package_verification.architecture;
  if (platform === 'macos') {
    return new Set([
      `${prefix}-mac-universal.dmg`,
      `${prefix}-mac-universal.zip`,
      `${prefix}-mac-universal.zip.blockmap`,
      'latest-mac.yml',
      PLATFORM_POLICIES.macos.evidence,
    ]);
  }
  if (platform === 'windows') {
    const installer = `${prefix}-win-${architecture}.exe`;
    return new Set([
      installer,
      `${installer}.blockmap`,
      'latest.yml',
      PLATFORM_POLICIES.windows.evidence,
    ]);
  }
  return new Set([
    `${prefix}-linux-${architecture}.AppImage`,
    `${prefix}-linux-${architecture}.deb`,
    'latest-linux.yml',
    PLATFORM_POLICIES.linux.evidence,
  ]);
}

function validatePlatformDirectory({ root, platform, policy, env, owners, assetPaths }) {
  const directory = join(root, 'verified', platform);
  const entries = readdirSync(directory, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isFile() || entry.isSymbolicLink()) {
      throw new Error(`unexpected ${platform} release entry: ${entry.name}`);
    }
  }
  const names = entries.map(({ name }) => name).sort();
  if (names.length === 0) throw new Error(`no verified ${platform} assets`);
  for (const name of names) {
    if (basename(name) !== name) {
      throw new Error(`unexpected ${platform} release asset: ${name}`);
    }
  }
  for (const pattern of policy.required) {
    const matches = names.filter((name) => pattern.test(name));
    if (matches.length !== 1) {
      throw new Error(`${platform} must provide exactly one ${pattern}; found ${matches.length}`);
    }
  }
  const evidenceNames = names.filter((name) =>
    /^release-evidence-(?:macos|windows|linux)\.json$/u.test(name),
  );
  if (evidenceNames.length !== 1 || evidenceNames[0] !== policy.evidence) {
    throw new Error(`${platform} must provide only ${policy.evidence} as release evidence`);
  }
  const evidence = readEvidence(join(directory, policy.evidence), platform);
  assertEvidenceIdentity(evidence, platform, env);
  validatePackageEvidence(platform, evidence.package_verification);
  const expectedNames = expectedPlatformAssetNames(platform, evidence);
  const unexpectedNames = names.filter((name) => !expectedNames.has(name));
  if (unexpectedNames.length > 0) {
    throw new Error(`unexpected ${platform} release asset: ${unexpectedNames.join(', ')}`);
  }
  const missingNames = [...expectedNames].filter((name) => !names.includes(name));
  if (missingNames.length > 0 || names.length !== expectedNames.size) {
    throw new Error(`${platform} release asset set is missing: ${missingNames.join(', ')}`);
  }
  for (const name of names) {
    const priorOwner = owners.get(name);
    if (priorOwner) {
      throw new Error(`release asset basename collision: ${name} (${priorOwner}, ${platform})`);
    }
    owners.set(name, platform);
    assetPaths.push(join(directory, name));
  }
  const publishableNames = names.filter((name) => name !== policy.evidence);
  assertEvidenceAssets({
    evidence,
    directory,
    platform,
    publishableNames,
  });
}

export function validateCombinedReleaseAssets({ root = process.cwd(), env = process.env } = {}) {
  const resolvedRoot = resolve(root);
  const owners = new Map();
  const assetPaths = [];
  for (const [platform, policy] of Object.entries(PLATFORM_POLICIES)) {
    validatePlatformDirectory({
      root: resolvedRoot,
      platform,
      policy,
      env,
      owners,
      assetPaths,
    });
  }
  const preliminaryManifest = assetPaths
    .map((path) => ({
      name: basename(path),
      path,
      size: statSync(path).size,
      sha256: fileDigest(path, 'sha256', 'hex'),
    }))
    .sort((left, right) => left.name.localeCompare(right.name));
  const platformEvidence = Object.keys(PLATFORM_POLICIES).map((platform) => {
    const name = PLATFORM_POLICIES[platform].evidence;
    const asset = preliminaryManifest.find((entry) => entry.name === name);
    if (!asset) throw new Error(`release evidence index is missing ${name}`);
    return { platform, name, sha256: asset.sha256 };
  });
  const index = buildReleasePackageEvidenceIndex({
    version: env.AGISTACK_RELEASE_VERSION,
    tag: env.GITHUB_REF_NAME,
    commitSha: env.GITHUB_SHA,
    workflowRun: {
      id: env.GITHUB_RUN_ID,
      attempt: env.GITHUB_RUN_ATTEMPT,
      url: `https://github.com/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}`,
    },
    platformEvidence,
    assets: preliminaryManifest.map(({ name, size, sha256 }) => ({ name, size, sha256 })),
  });
  const indexPath = writeReleasePackageEvidenceIndex({ releaseRoot: resolvedRoot, index });
  const manifest = [
    ...preliminaryManifest,
    {
      name: basename(indexPath),
      path: indexPath,
      size: statSync(indexPath).size,
      sha256: fileDigest(indexPath, 'sha256', 'hex'),
    },
  ].sort((left, right) => left.name.localeCompare(right.name));
  writeFileSync(
    join(resolvedRoot, 'verified-assets.txt'),
    `${manifest.map(({ name }) => name).join('\n')}\n`,
  );
  writeFileSync(
    join(resolvedRoot, 'verified-asset-paths.txt'),
    `${manifest.map(({ path }) => path).join('\n')}\n`,
  );
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

function main() {
  const command = process.argv[2];
  const manifestPath = resolve('verified-assets.json');
  if (command === 'validate-combined') {
    validateCombinedReleaseAssets();
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
  main();
}
