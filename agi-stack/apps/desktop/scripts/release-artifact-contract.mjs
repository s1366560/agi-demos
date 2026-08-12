import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { access, chmod, readFile, readdir, stat, writeFile } from 'node:fs/promises';
import { basename, dirname, resolve } from 'node:path';
import { gunzipSync, inflateRawSync } from 'node:zlib';
import { parseDocument } from 'yaml';

const RELEASE_EVIDENCE_CONTRACT = 'desktop-release-package-evidence-v1';
const BLOCKMAP_VERIFICATION_SCOPE = 'blockmap_structure_and_coverage_only';
const DIAGNOSTIC_ROOT_FILES = new Set(['builder-debug.yml', 'builder-effective-config.yaml']);
const PLATFORM_POLICIES = Object.freeze({
  darwin: Object.freeze({
    metadata: 'latest-mac.yml',
    os: 'mac',
    architectures: Object.freeze(['universal']),
    installerSuffixes: Object.freeze(['.dmg', '.zip']),
    externalBlockmapSuffixes: Object.freeze(['.zip']),
    embeddedBlockmapSuffixes: Object.freeze([]),
    evidencePlatform: 'macos',
  }),
  win32: Object.freeze({
    metadata: 'latest.yml',
    os: 'win',
    architectures: Object.freeze(['x64', 'arm64']),
    installerSuffixes: Object.freeze(['.exe']),
    externalBlockmapSuffixes: Object.freeze(['.exe']),
    embeddedBlockmapSuffixes: Object.freeze([]),
    evidencePlatform: 'windows',
  }),
  linux: Object.freeze({
    metadata: 'latest-linux.yml',
    os: 'linux',
    architectures: Object.freeze(['x64', 'arm64']),
    installerSuffixes: Object.freeze(['.AppImage', '.deb']),
    externalBlockmapSuffixes: Object.freeze([]),
    embeddedBlockmapSuffixes: Object.freeze(['.AppImage']),
    evidencePlatform: 'linux',
  }),
});

export function platformPolicy(platform) {
  const policy = PLATFORM_POLICIES[platform];
  if (!policy) {
    throw new Error(`unsupported release verification platform: ${platform}`);
  }
  return policy;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&');
}

function artifactPattern(version, os, suffix, architectures) {
  const architecturePattern = architectures.map(escapeRegExp).join('|');
  return new RegExp(
    `^agi-stack-desktop-${escapeRegExp(
      version,
    )}-${os}-(?:${architecturePattern})${escapeRegExp(suffix)}$`,
    'u',
  );
}

function artifactArchitecture(name, version, os, suffix) {
  return name.match(
    new RegExp(
      `^agi-stack-desktop-${escapeRegExp(
        version,
      )}-${os}-(x64|arm64|universal)${escapeRegExp(suffix)}$`,
      'u',
    ),
  )?.[1];
}

function requireUniquePath(paths, label) {
  if (paths.length !== 1) {
    throw new Error(`${label} must have exactly one match; found ${paths.length}`);
  }
  return paths[0];
}

function parseMetadata(source, metadataName) {
  const document = parseDocument(source, {
    maxAliasCount: 0,
    uniqueKeys: true,
  });
  if (document.errors.length > 0) {
    throw new Error(
      `${metadataName} is invalid YAML: ${document.errors
        .map((error) => error.message)
        .join('; ')}`,
    );
  }
  const metadata = document.toJS({ maxAliasCount: 0 });
  if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
    throw new Error(`${metadataName} must contain a mapping`);
  }
  return metadata;
}

function canonicalSha512(value, label) {
  if (typeof value !== 'string') {
    throw new Error(`${label} must be a base64 SHA-512 digest`);
  }
  const digest = Buffer.from(value, 'base64');
  if (digest.byteLength !== 64 || digest.toString('base64') !== value) {
    throw new Error(`${label} must be a canonical base64 SHA-512 digest`);
  }
  return value;
}

async function fileSha512(path) {
  return createHash('sha512')
    .update(await readFile(path))
    .digest('base64');
}

function assertSafeRootFilename(value, label) {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    basename(value) !== value ||
    value.includes('/') ||
    value.includes('\\') ||
    value === '.' ||
    value === '..'
  ) {
    throw new Error(`${label} must name a file in the release root`);
  }
  return value;
}

function parseBlockMap(buffer, label, compression) {
  let decompressed;
  try {
    decompressed = compression === 'gzip' ? gunzipSync(buffer) : inflateRawSync(buffer);
  } catch {
    throw new Error(`${label} blockmap compression is invalid`);
  }
  let blockmap;
  try {
    blockmap = JSON.parse(decompressed.toString('utf8'));
  } catch {
    throw new Error(`${label} blockmap JSON is invalid`);
  }
  if (
    !blockmap ||
    typeof blockmap !== 'object' ||
    Array.isArray(blockmap) ||
    blockmap.version !== '2' ||
    !Array.isArray(blockmap.files) ||
    blockmap.files.length !== 1
  ) {
    throw new Error(`${label} blockmap contract is invalid`);
  }

  let coveredSize = 0;
  for (const file of blockmap.files) {
    if (
      !file ||
      typeof file !== 'object' ||
      Array.isArray(file) ||
      file.name !== 'file' ||
      file.offset !== 0 ||
      !Array.isArray(file.checksums) ||
      !Array.isArray(file.sizes) ||
      file.checksums.length === 0 ||
      file.checksums.length !== file.sizes.length
    ) {
      throw new Error(`${label} blockmap file contract is invalid`);
    }
    let fileSize = 0;
    for (let index = 0; index < file.sizes.length; index += 1) {
      const size = file.sizes[index];
      const checksum = file.checksums[index];
      const checksumBytes = typeof checksum === 'string' ? Buffer.from(checksum, 'base64') : null;
      if (
        !Number.isSafeInteger(size) ||
        size <= 0 ||
        !checksumBytes ||
        checksumBytes.byteLength !== 18 ||
        checksumBytes.toString('base64') !== checksum
      ) {
        throw new Error(`${label} blockmap chunk contract is invalid`);
      }
      fileSize += size;
      if (!Number.isSafeInteger(fileSize)) {
        throw new Error(`${label} blockmap size is invalid`);
      }
    }
    coveredSize = Math.max(coveredSize, file.offset + fileSize);
  }
  return coveredSize;
}

async function verifyExternalBlockmap(installerPath, blockmapPath, label) {
  const blockmap = await readFile(blockmapPath);
  const coveredSize = parseBlockMap(blockmap, label, 'gzip');
  const installerSize = (await stat(installerPath)).size;
  if (coveredSize !== installerSize) {
    throw new Error(
      `${label} blockmap covers ${coveredSize} bytes; installer has ${installerSize}`,
    );
  }
  return {
    kind: 'external',
    verification_scope: BLOCKMAP_VERIFICATION_SCOPE,
    name: basename(blockmapPath),
    size: blockmap.byteLength,
    sha512: createHash('sha512').update(blockmap).digest('base64'),
  };
}

async function verifyEmbeddedBlockmap(installerPath, declaredSize, label) {
  if (!Number.isSafeInteger(declaredSize) || declaredSize <= 0) {
    throw new Error(`${label} embedded blockmap size must be a positive integer`);
  }
  const installer = await readFile(installerPath);
  if (installer.byteLength <= declaredSize + 4) {
    throw new Error(`${label} embedded blockmap exceeds the installer`);
  }
  const trailerSize = installer.readUInt32BE(installer.byteLength - 4);
  if (trailerSize !== declaredSize) {
    throw new Error(`${label} embedded blockmap trailer does not match metadata`);
  }
  const compressedStart = installer.byteLength - declaredSize - 4;
  const coveredSize = parseBlockMap(
    installer.subarray(compressedStart, installer.byteLength - 4),
    label,
    'deflate',
  );
  if (coveredSize !== compressedStart) {
    throw new Error(
      `${label} embedded blockmap covers ${coveredSize} bytes; payload has ${compressedStart}`,
    );
  }
  return {
    kind: 'embedded',
    verification_scope: BLOCKMAP_VERIFICATION_SCOPE,
    size: declaredSize,
  };
}

async function verifyMetadataEntry(
  entry,
  releaseRoot,
  allowedInstallers,
  rootFiles,
  policy,
  metadataName,
) {
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
    throw new Error(`${metadataName} files entries must be mappings`);
  }
  const url = assertSafeRootFilename(entry.url, `${metadataName} files[].url`);
  if (!allowedInstallers.has(url)) {
    throw new Error(`${metadataName} contains an unknown update target: ${url}`);
  }
  if (!Number.isSafeInteger(entry.size) || entry.size <= 0) {
    throw new Error(`${metadataName} files[${url}].size must be a positive integer`);
  }
  const expectedSha512 = canonicalSha512(entry.sha512, `${metadataName} files[${url}].sha512`);
  const path = resolve(releaseRoot, url);
  if (dirname(path) !== releaseRoot) {
    throw new Error(`${metadataName} update target escapes the release root: ${url}`);
  }
  await access(path, constants.R_OK);
  const fileStats = await stat(path);
  if (!fileStats.isFile()) {
    throw new Error(`${metadataName} update target is not a regular file: ${url}`);
  }
  if (fileStats.size !== entry.size) {
    throw new Error(
      `${metadataName} size mismatch for ${url}: expected ${entry.size}, found ${fileStats.size}`,
    );
  }
  if ((await fileSha512(path)) !== expectedSha512) {
    throw new Error(`${metadataName} SHA-512 mismatch for ${url}`);
  }

  const externalBlockmapName = `${url}.blockmap`;
  const hasExternalBlockmap = rootFiles.has(externalBlockmapName);
  const requiresExternalBlockmap = policy.externalBlockmapSuffixes.some((suffix) =>
    url.endsWith(suffix),
  );
  const requiresEmbeddedBlockmap = policy.embeddedBlockmapSuffixes.some((suffix) =>
    url.endsWith(suffix),
  );
  if (requiresExternalBlockmap && !hasExternalBlockmap) {
    throw new Error(`${metadataName} is missing required ${externalBlockmapName}`);
  }
  if (!requiresExternalBlockmap && hasExternalBlockmap) {
    throw new Error(`${metadataName} contains unexpected blockmap ${externalBlockmapName}`);
  }
  if (requiresEmbeddedBlockmap && hasExternalBlockmap) {
    throw new Error(`${metadataName} must use the embedded blockmap for ${url}`);
  }
  let blockmap = null;
  if (hasExternalBlockmap) {
    blockmap = await verifyExternalBlockmap(
      path,
      resolve(releaseRoot, externalBlockmapName),
      `${metadataName} ${url}`,
    );
  } else if (requiresEmbeddedBlockmap) {
    blockmap = await verifyEmbeddedBlockmap(path, entry.blockMapSize, `${metadataName} ${url}`);
  } else if (entry.blockMapSize !== undefined) {
    throw new Error(`${metadataName} contains unexpected blockMapSize for ${url}`);
  }
  return {
    url,
    sha512: expectedSha512,
    size: entry.size,
    blockmap,
  };
}

export async function verifyReleaseRootMetadata({
  releaseRoot,
  platform,
  version,
  expectedTag,
  expectedVersion,
}) {
  const root = resolve(releaseRoot);
  const policy = platformPolicy(platform);
  if (typeof version !== 'string' || version.length === 0) {
    throw new Error('desktop package version is missing');
  }
  if (expectedTag !== undefined && expectedTag !== `v${version}`) {
    throw new Error(`release tag must exactly match v${version}`);
  }
  if (expectedVersion !== undefined && version !== expectedVersion) {
    throw new Error(`desktop package version must remain ${expectedVersion}; found ${version}`);
  }

  const entries = await readdir(root, { withFileTypes: true });
  const rootFiles = entries.filter((entry) => entry.isFile()).map((entry) => entry.name);
  const symbolicLinks = entries.filter((entry) => entry.isSymbolicLink());
  if (symbolicLinks.length > 0) {
    throw new Error(
      `release root must not contain symbolic links: ${symbolicLinks
        .map((entry) => entry.name)
        .join(', ')}`,
    );
  }

  const installers = [];
  for (const suffix of policy.installerSuffixes) {
    const pattern = artifactPattern(version, policy.os, suffix, policy.architectures);
    const matches = rootFiles.filter((name) => pattern.test(name));
    if (matches.length !== 1) {
      throw new Error(
        `release root must contain exactly one ${policy.os} ${policy.architectures.join(
          '/',
        )} *${suffix} installer; found ${matches.length}`,
      );
    }
    installers.push(matches[0]);
  }
  const installerArchitectures = installers.map((name, index) =>
    artifactArchitecture(name, version, policy.os, policy.installerSuffixes[index]),
  );
  if (
    installerArchitectures.some((architecture) => !architecture) ||
    new Set(installerArchitectures).size !== 1
  ) {
    throw new Error(`release installers must use one ${policy.os} architecture`);
  }
  const [architecture] = installerArchitectures;
  if (!policy.architectures.includes(architecture)) {
    throw new Error(
      `release ${policy.os} architecture must be ${policy.architectures.join(' or ')}`,
    );
  }
  const allowedInstallers = new Set(installers);
  for (const suffix of policy.externalBlockmapSuffixes) {
    const installer = installers.find((name) => name.endsWith(suffix));
    if (!installer || !rootFiles.includes(`${installer}.blockmap`)) {
      throw new Error(`release root is missing required ${installer ?? `*${suffix}`}.blockmap`);
    }
  }
  const allowedRootFiles = new Set([
    ...DIAGNOSTIC_ROOT_FILES,
    ...installers,
    ...installers
      .filter((name) => policy.externalBlockmapSuffixes.some((suffix) => name.endsWith(suffix)))
      .map((name) => `${name}.blockmap`),
    policy.metadata,
  ]);
  const unknownRootFiles = rootFiles.filter((name) => !allowedRootFiles.has(name));
  if (unknownRootFiles.length > 0) {
    throw new Error(
      `release root contains files outside the publish allow-list: ${unknownRootFiles.join(', ')}`,
    );
  }
  for (const blockmap of rootFiles.filter((name) => name.endsWith('.blockmap'))) {
    if (!allowedInstallers.has(blockmap.slice(0, -'.blockmap'.length))) {
      throw new Error(`orphaned or unknown blockmap: ${blockmap}`);
    }
  }

  const metadataPath = resolve(root, policy.metadata);
  await access(metadataPath, constants.R_OK);
  const metadata = parseMetadata(await readFile(metadataPath, 'utf8'), policy.metadata);
  if (metadata.version !== version) {
    throw new Error(
      `${policy.metadata} version must equal package version ${version}; found ${String(
        metadata.version,
      )}`,
    );
  }
  if (!Array.isArray(metadata.files)) {
    throw new Error(`${policy.metadata} files must be an array`);
  }
  if (metadata.files.length !== installers.length) {
    throw new Error(`${policy.metadata} must contain exactly ${installers.length} update targets`);
  }

  const verifiedEntries = [];
  const seenUrls = new Set();
  const rootFileSet = new Set(rootFiles);
  for (const entry of metadata.files) {
    const verified = await verifyMetadataEntry(
      entry,
      root,
      allowedInstallers,
      rootFileSet,
      policy,
      policy.metadata,
    );
    if (seenUrls.has(verified.url)) {
      throw new Error(`${policy.metadata} contains a duplicate update target: ${verified.url}`);
    }
    seenUrls.add(verified.url);
    verifiedEntries.push(verified);
  }
  for (const installer of installers) {
    if (!seenUrls.has(installer)) {
      throw new Error(`${policy.metadata} does not describe required update target: ${installer}`);
    }
  }

  const legacyPath = assertSafeRootFilename(metadata.path, `${policy.metadata} path`);
  const legacyEntry = verifiedEntries.find((entry) => entry.url === legacyPath);
  if (!legacyEntry) {
    throw new Error(`${policy.metadata} legacy path must match a files[] update target`);
  }
  const legacySha512 = canonicalSha512(metadata.sha512, `${policy.metadata} legacy sha512`);
  if (legacySha512 !== legacyEntry.sha512) {
    throw new Error(`${policy.metadata} legacy path/sha512 must match the same files[] entry`);
  }

  return {
    architecture,
    blockmapVerificationScope: BLOCKMAP_VERIFICATION_SCOPE,
    metadataPath,
    installers: installers.map((name) => resolve(root, name)),
    publishableArtifacts: rootFiles
      .filter((name) => !DIAGNOSTIC_ROOT_FILES.has(name))
      .map((name) => resolve(root, name))
      .sort(),
  };
}

function assertEvidenceText(value, label, pattern) {
  if (typeof value !== 'string' || !pattern.test(value)) {
    throw new Error(`${label} is invalid`);
  }
  return value;
}

export function buildReleaseEvidence({
  platform,
  version,
  expectedVersion,
  tag,
  commitSha,
  runId,
  runAttempt,
  runUrl,
  assets,
  packageVerification,
}) {
  if (!['macos', 'windows', 'linux'].includes(platform)) {
    throw new Error('release evidence platform is invalid');
  }
  if (version !== expectedVersion) {
    throw new Error(`desktop package version must remain ${expectedVersion}; found ${version}`);
  }
  if (tag !== `v${version}`) {
    throw new Error(`release evidence tag must exactly match v${version}`);
  }
  assertEvidenceText(commitSha, 'release evidence commit SHA', /^[a-f0-9]{40}$/u);
  assertEvidenceText(runId, 'release evidence run id', /^[1-9][0-9]*$/u);
  assertEvidenceText(runAttempt, 'release evidence run attempt', /^[1-9][0-9]*$/u);
  let parsedRunUrl;
  try {
    parsedRunUrl = new URL(runUrl);
  } catch {
    throw new Error('release evidence run URL is invalid');
  }
  const runUrlSegments = parsedRunUrl.pathname.split('/').filter(Boolean);
  if (
    parsedRunUrl.protocol !== 'https:' ||
    parsedRunUrl.hostname !== 'github.com' ||
    parsedRunUrl.port !== '' ||
    parsedRunUrl.username !== '' ||
    parsedRunUrl.password !== '' ||
    parsedRunUrl.search !== '' ||
    parsedRunUrl.hash !== '' ||
    runUrlSegments.length !== 5 ||
    !runUrlSegments.slice(0, 2).every((segment) => /^[A-Za-z0-9_.-]+$/u.test(segment)) ||
    runUrlSegments[2] !== 'actions' ||
    runUrlSegments[3] !== 'runs' ||
    runUrlSegments[4] !== runId
  ) {
    throw new Error('release evidence run URL is invalid');
  }
  if (!Array.isArray(assets) || assets.length === 0) {
    throw new Error('release evidence assets must not be empty');
  }
  const normalizedAssets = assets
    .map((asset) => {
      if (!asset || typeof asset !== 'object' || Array.isArray(asset)) {
        throw new Error('release evidence asset contract is invalid');
      }
      const name = assertSafeRootFilename(asset.name, 'release evidence asset name');
      if (!Number.isSafeInteger(asset.size) || asset.size <= 0) {
        throw new Error(`release evidence asset size is invalid: ${name}`);
      }
      return {
        name,
        size: asset.size,
        sha512: canonicalSha512(asset.sha512, `release evidence asset SHA-512 for ${name}`),
      };
    })
    .sort((left, right) => left.name.localeCompare(right.name));
  if (new Set(normalizedAssets.map((asset) => asset.name)).size !== normalizedAssets.length) {
    throw new Error('release evidence assets contain duplicate names');
  }
  if (
    !packageVerification ||
    typeof packageVerification !== 'object' ||
    Array.isArray(packageVerification) ||
    Object.keys(packageVerification).length === 0
  ) {
    throw new Error('release evidence package verification is invalid');
  }

  return {
    contract_version: RELEASE_EVIDENCE_CONTRACT,
    evidence_scope: 'package_artifacts_and_promotion_requirements',
    blockmap_verification_scope: BLOCKMAP_VERIFICATION_SCOPE,
    artifact_verification_status: 'verified_by_tag_ci',
    release_disposition: 'prerelease_only',
    release_blocker_reason_code: 'stable_promotion_native_evidence_required',
    required_native_checks: ['install', 'launch', 'updater_apply', 'updater_failure_rollback'],
    verification_checks: [
      { id: 'package_artifacts', status: 'passed', reason_code: null },
      { id: 'install', status: 'blocked', reason_code: 'native_install_evidence_missing' },
      { id: 'launch', status: 'blocked', reason_code: 'native_launch_evidence_missing' },
      { id: 'updater_apply', status: 'blocked', reason_code: 'updater_apply_evidence_missing' },
      {
        id: 'updater_failure_rollback',
        status: 'blocked',
        reason_code: 'updater_failure_rollback_evidence_missing',
      },
    ],
    platform,
    version,
    tag,
    commit_sha: commitSha,
    workflow_run: {
      id: runId,
      attempt: runAttempt,
      url: parsedRunUrl.toString(),
    },
    package_verification: packageVerification,
    assets: normalizedAssets,
  };
}

async function releaseAssetEvidence(paths) {
  return Promise.all(
    paths.map(async (path) => {
      const fileStats = await stat(path);
      if (!fileStats.isFile() || fileStats.size <= 0) {
        throw new Error(`release evidence asset is not a non-empty file: ${path}`);
      }
      return {
        name: basename(path),
        size: fileStats.size,
        sha512: await fileSha512(path),
      };
    }),
  );
}

export async function writeReleaseEvidence({
  releaseRoot,
  policy,
  version,
  expectedVersion,
  tag,
  commitSha,
  runId,
  runAttempt,
  runUrl,
  artifactPaths,
  packageVerification,
}) {
  const evidence = buildReleaseEvidence({
    platform: policy.evidencePlatform,
    version,
    expectedVersion,
    tag,
    commitSha,
    runId,
    runAttempt,
    runUrl,
    assets: await releaseAssetEvidence(artifactPaths),
    packageVerification,
  });
  const evidencePath = resolve(releaseRoot, `release-evidence-${policy.evidencePlatform}.json`);
  await writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, {
    encoding: 'utf8',
    flag: 'wx',
    mode: 0o444,
  });
  await chmod(evidencePath, 0o444);
  return evidencePath;
}
