import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { access, readdir, readFile, stat } from 'node:fs/promises';
import { constants } from 'node:fs';
import { basename, dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseDocument } from 'yaml';

const scriptPath = fileURLToPath(import.meta.url);
const desktopRoot = resolve(dirname(scriptPath), '..');
const defaultReleaseRoot = resolve(desktopRoot, 'release');
const packageJsonPath = resolve(desktopRoot, 'package.json');
const DIAGNOSTIC_ROOT_FILES = new Set([
  'builder-debug.yml',
  'builder-effective-config.yaml',
]);
const PLATFORM_POLICIES = Object.freeze({
  darwin: Object.freeze({
    metadata: 'latest-mac.yml',
    os: 'mac',
    installerSuffixes: Object.freeze(['.dmg', '.zip']),
    requiredBlockmapSuffixes: Object.freeze([]),
  }),
  win32: Object.freeze({
    metadata: 'latest.yml',
    os: 'win',
    installerSuffixes: Object.freeze(['.exe']),
    requiredBlockmapSuffixes: Object.freeze(['.exe']),
  }),
  linux: Object.freeze({
    metadata: 'latest-linux.yml',
    os: 'linux',
    installerSuffixes: Object.freeze(['.AppImage', '.deb']),
    requiredBlockmapSuffixes: Object.freeze([]),
  }),
});

function platformPolicy(platform) {
  const policy = PLATFORM_POLICIES[platform];
  if (!policy) {
    throw new Error(`unsupported release verification platform: ${platform}`);
  }
  return policy;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&');
}

function artifactPattern(version, os, suffix) {
  return new RegExp(
    `^agi-stack-desktop-${escapeRegExp(version)}-${os}-(?:x64|arm64|universal)${escapeRegExp(
      suffix,
    )}$`,
    'u',
  );
}

async function collectEntries(root) {
  const files = [];
  const directories = [];
  const visit = async (directory) => {
    directories.push(directory);
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        await visit(path);
      } else if (entry.isFile()) {
        files.push(path);
      }
    }
  };
  await visit(root);
  return { files, directories };
}

function requireUniquePath(paths, label) {
  if (paths.length !== 1) {
    throw new Error(`${label} must have exactly one match; found ${paths.length}`);
  }
  return paths[0];
}

function requireRootArtifact(files, releaseRoot, suffix) {
  return requireUniquePath(
    files.filter(
      (path) =>
        !relative(releaseRoot, path).includes(sep) &&
        basename(path).endsWith(suffix),
    ),
    `release artifact *${suffix}`,
  );
}

function requireFile(files, expectedName) {
  return requireUniquePath(
    files.filter((candidate) => basename(candidate) === expectedName),
    `release file ${expectedName}`,
  );
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
  return createHash('sha512').update(await readFile(path)).digest('base64');
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

async function verifyMetadataEntry(entry, releaseRoot, allowedInstallers, metadataName) {
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
  const expectedSha512 = canonicalSha512(
    entry.sha512,
    `${metadataName} files[${url}].sha512`,
  );
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
  const actualSha512 = await fileSha512(path);
  if (actualSha512 !== expectedSha512) {
    throw new Error(`${metadataName} SHA-512 mismatch for ${url}`);
  }
  return { url, sha512: expectedSha512 };
}

/**
 * Verifies the release-root allow-list plus electron-updater metadata.
 * Exported for deterministic fixture tests; signature checks remain native.
 */
export async function verifyReleaseRootMetadata({
  releaseRoot,
  platform,
  version,
  expectedTag,
}) {
  const root = resolve(releaseRoot);
  const policy = platformPolicy(platform);
  if (typeof version !== 'string' || version.length === 0) {
    throw new Error('desktop package version is missing');
  }
  if (expectedTag !== undefined && expectedTag !== `v${version}`) {
    throw new Error(`release tag must exactly match v${version}`);
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
    const pattern = artifactPattern(version, policy.os, suffix);
    const matches = rootFiles.filter((name) => pattern.test(name));
    if (matches.length !== 1) {
      throw new Error(
        `release root must contain exactly one ${policy.os} *${suffix} installer; found ${matches.length}`,
      );
    }
    installers.push(matches[0]);
  }
  const allowedInstallers = new Set(installers);
  for (const suffix of policy.requiredBlockmapSuffixes) {
    const installer = installers.find((name) => name.endsWith(suffix));
    if (!installer || !rootFiles.includes(`${installer}.blockmap`)) {
      throw new Error(`release root is missing required *${suffix}.blockmap`);
    }
  }
  const allowedRootFiles = new Set([
    ...DIAGNOSTIC_ROOT_FILES,
    ...installers,
    ...installers.map((name) => `${name}.blockmap`),
    policy.metadata,
  ]);
  const unknownRootFiles = rootFiles.filter((name) => !allowedRootFiles.has(name));
  if (unknownRootFiles.length > 0) {
    throw new Error(
      `release root contains files outside the publish allow-list: ${unknownRootFiles.join(
        ', ',
      )}`,
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
    throw new Error(
      `${policy.metadata} must contain exactly ${installers.length} update targets`,
    );
  }

  const verifiedEntries = [];
  const seenUrls = new Set();
  for (const entry of metadata.files) {
    const verified = await verifyMetadataEntry(
      entry,
      root,
      allowedInstallers,
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
  const legacySha512 = canonicalSha512(
    metadata.sha512,
    `${policy.metadata} legacy sha512`,
  );
  if (legacySha512 !== legacyEntry.sha512) {
    throw new Error(`${policy.metadata} legacy path/sha512 must match the same files[] entry`);
  }

  return {
    metadataPath,
    installers: installers.map((name) => resolve(root, name)),
  };
}

async function verifySidecarDigest(sidecarPath, sidecarName) {
  const checksumPath = join(dirname(sidecarPath), 'SHA256SUMS');
  await access(checksumPath, constants.R_OK);
  const expectedLine = (await readFile(checksumPath, 'utf8')).trim();
  const expectedDigest = createHash('sha256')
    .update(await readFile(sidecarPath))
    .digest('hex');
  if (expectedLine !== `${expectedDigest}  ${sidecarName}`) {
    throw new Error('packaged sidecar digest does not match SHA256SUMS');
  }
  if (process.platform !== 'win32') {
    const mode = (await stat(sidecarPath)).mode;
    if ((mode & 0o111) === 0) throw new Error('packaged sidecar is not executable');
  }
}

function inspectMacSignature(path) {
  const result = spawnSync(
    '/usr/bin/codesign',
    ['--display', '--verbose=4', path],
    { encoding: 'utf8' },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`codesign inspection failed for ${path}: ${result.stderr}`);
  }
  const details = `${result.stdout}\n${result.stderr}`;
  const developerIdAuthority = [...details.matchAll(/^Authority=(.+)$/gmu)]
    .map((match) => match[1].trim())
    .find((authority) => /^Developer ID Application:\s+\S/u.test(authority));
  const teamIdentifier = details.match(/^TeamIdentifier=(.+)$/mu)?.[1].trim();
  if (!developerIdAuthority) {
    throw new Error(`Developer ID Authority is missing for ${path}`);
  }
  if (!teamIdentifier || teamIdentifier === 'not set') {
    throw new Error(`TeamIdentifier is missing for ${path}`);
  }
  return { developerIdAuthority, teamIdentifier };
}

function expectedMacTeamIdentifier() {
  const expected =
    process.env.AGISTACK_EXPECTED_MAC_TEAM_ID ?? process.env.APPLE_TEAM_ID;
  if (!expected || !/^[A-Z0-9]{10}$/u.test(expected)) {
    throw new Error(
      'AGISTACK_EXPECTED_MAC_TEAM_ID or APPLE_TEAM_ID must be a 10-character team identifier',
    );
  }
  return expected;
}

function verifyMacSignatures(appPath, sidecarPath) {
  execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', appPath], {
    stdio: 'inherit',
  });
  execFileSync('/usr/bin/codesign', ['--verify', '--strict', sidecarPath], {
    stdio: 'inherit',
  });
  const appSignature = inspectMacSignature(appPath);
  const sidecarSignature = inspectMacSignature(sidecarPath);
  if (appSignature.developerIdAuthority !== sidecarSignature.developerIdAuthority) {
    throw new Error('app and sidecar Developer ID Authority values do not match');
  }
  if (appSignature.teamIdentifier !== sidecarSignature.teamIdentifier) {
    throw new Error('app and sidecar TeamIdentifier values do not match');
  }
  const expectedTeamIdentifier = expectedMacTeamIdentifier();
  if (
    appSignature.teamIdentifier !== expectedTeamIdentifier ||
    sidecarSignature.teamIdentifier !== expectedTeamIdentifier
  ) {
    throw new Error(
      'app and sidecar TeamIdentifier values do not match the configured release team',
    );
  }
  if (process.env.AGISTACK_REQUIRE_NOTARIZATION === '1') {
    execFileSync(
      '/usr/sbin/spctl',
      ['--assess', '--type', 'execute', '--verbose=4', appPath],
      { stdio: 'inherit' },
    );
    execFileSync('/usr/bin/xcrun', ['stapler', 'validate', appPath], {
      stdio: 'inherit',
    });
  }
}

function normalizedWindowsThumbprint() {
  const normalized = (process.env.WIN_CSC_SHA1 ?? '')
    .replace(/\s/gu, '')
    .toUpperCase();
  if (!/^[A-F0-9]{40}$/u.test(normalized)) {
    throw new Error('WIN_CSC_SHA1 must be a 40-character certificate thumbprint');
  }
  return normalized;
}

function verifyWindowsSignatures(installerPath, sidecarPath) {
  const expectedThumbprint = normalizedWindowsThumbprint();
  const script = [
    "$ErrorActionPreference = 'Stop'",
    "$expected = ($args[0] -replace '\\s', '').ToUpperInvariant()",
    'foreach ($path in $args[1..($args.Length - 1)]) {',
    '  $signature = Get-AuthenticodeSignature -LiteralPath $path',
    "  if ($signature.Status -ne 'Valid') {",
    '    throw "invalid Authenticode signature: $path ($($signature.Status))"',
    '  }',
    '  if ($null -eq $signature.SignerCertificate) {',
    '    throw "Authenticode signer certificate is missing: $path"',
    '  }',
    "  $actual = ($signature.SignerCertificate.Thumbprint -replace '\\s', '').ToUpperInvariant()",
    '  if ($actual -ne $expected) {',
    '    throw "unexpected Authenticode signer certificate: $path"',
    '  }',
    '}',
  ].join('\n');
  execFileSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      script,
      expectedThumbprint,
      installerPath,
      sidecarPath,
    ],
    { stdio: 'inherit' },
  );
}

async function main() {
  const packageJson = JSON.parse(await readFile(packageJsonPath, 'utf8'));
  const platform = process.platform;
  const releaseRoot = defaultReleaseRoot;
  const sidecarName =
    platform === 'win32'
      ? 'agistack-desktop-sidecar.exe'
      : 'agistack-desktop-sidecar';
  await verifyReleaseRootMetadata({
    releaseRoot,
    platform,
    version: packageJson.version,
    expectedTag: process.env.AGISTACK_EXPECTED_TAG || undefined,
  });

  const { files, directories } = await collectEntries(releaseRoot);
  let sidecarPath;
  if (platform === 'darwin') {
    const appPath = requireUniquePath(
      directories.filter((path) => {
        const relativePath = relative(releaseRoot, path);
        return relativePath.split(sep).length === 2 && path.endsWith('.app');
      }),
      'packaged macOS application',
    );
    sidecarPath = join(appPath, 'Contents', 'Resources', 'sidecar', sidecarName);
    await verifySidecarDigest(sidecarPath, sidecarName);
    verifyMacSignatures(appPath, sidecarPath);
  } else if (platform === 'win32') {
    const installerPath = requireRootArtifact(files, releaseRoot, '.exe');
    sidecarPath = requireFile(
      files.filter((path) => path.includes(`win-unpacked${sep}`)),
      sidecarName,
    );
    await verifySidecarDigest(sidecarPath, sidecarName);
    verifyWindowsSignatures(installerPath, sidecarPath);
  } else if (platform === 'linux') {
    sidecarPath = requireFile(
      files.filter((path) => path.includes(`linux-unpacked${sep}`)),
      sidecarName,
    );
    await verifySidecarDigest(sidecarPath, sidecarName);
  } else {
    platformPolicy(platform);
  }

  process.stdout.write(
    `DESKTOP_RELEASE_VERIFIED platform=${platform} sidecar=${relative(
      releaseRoot,
      sidecarPath,
    )}\n`,
  );
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  await main();
}
