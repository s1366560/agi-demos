import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { constants, mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { access, mkdtemp, readdir, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  buildReleaseEvidence,
  platformPolicy,
  verifyReleaseRootMetadata,
  writeReleaseEvidence,
} from './release-artifact-contract.mjs';
import {
  inspectPortableExecutableArchitecture,
  verifyMacPackageArtifacts,
  verifyWindowsInstallerArtifact,
} from './release-package-verification.mjs';

export { buildReleaseEvidence, verifyReleaseRootMetadata };

const scriptPath = fileURLToPath(import.meta.url);
const desktopRoot = resolve(dirname(scriptPath), '..');
const defaultReleaseRoot = resolve(desktopRoot, 'release');
const packageJsonPath = resolve(desktopRoot, 'package.json');
const MAC_AUDIO_INPUT_ENTITLEMENT = 'com.apple.security.device.audio-input';

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&');
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

function requireFile(files, expectedName) {
  return requireUniquePath(
    files.filter((candidate) => basename(candidate) === expectedName),
    `release file ${expectedName}`,
  );
}

async function verifyRuntimeDigest(runtimePath, runtimeName, label) {
  const checksumPath = join(dirname(runtimePath), 'SHA256SUMS');
  await access(checksumPath, constants.R_OK);
  const expectedLine = (await readFile(checksumPath, 'utf8')).trim();
  const expectedDigest = createHash('sha256')
    .update(await readFile(runtimePath))
    .digest('hex');
  if (expectedLine !== `${expectedDigest}  ${runtimeName}`) {
    throw new Error(`packaged ${label} digest does not match SHA256SUMS`);
  }
  if (process.platform !== 'win32') {
    const mode = (await stat(runtimePath)).mode;
    if ((mode & 0o111) === 0) throw new Error(`packaged ${label} is not executable`);
  }
  return expectedDigest;
}

async function verifySidecarDigest(sidecarPath, sidecarName) {
  return verifyRuntimeDigest(sidecarPath, sidecarName, 'sidecar');
}

async function verifyWorkspaceCoreDigest(workspaceCorePath, workspaceCoreName) {
  return verifyRuntimeDigest(workspaceCorePath, workspaceCoreName, 'Workspace Core');
}

function inspectMacSignature(path) {
  const result = spawnSync('/usr/bin/codesign', ['--display', '--verbose=4', path], {
    encoding: 'utf8',
  });
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
  const certificateDirectory = mkdtempSync(join(tmpdir(), 'agistack-codesign-certificate-'));
  const certificatePrefix = join(certificateDirectory, 'certificate-');
  let signingCertificateSha256;
  try {
    execFileSync(
      '/usr/bin/codesign',
      ['--display', `--extract-certificates=${certificatePrefix}`, path],
      { stdio: 'ignore' },
    );
    signingCertificateSha256 = createHash('sha256')
      .update(readFileSync(`${certificatePrefix}0`))
      .digest('hex');
  } finally {
    rmSync(certificateDirectory, { recursive: true, force: true });
  }
  return {
    developerIdAuthority,
    teamIdentifier,
    signingCertificateSha256,
  };
}

function expectedMacTeamIdentifier() {
  const expected = process.env.AGISTACK_EXPECTED_MAC_TEAM_ID ?? process.env.APPLE_TEAM_ID;
  if (!expected || !/^[A-Z0-9]{10}$/u.test(expected)) {
    throw new Error(
      'AGISTACK_EXPECTED_MAC_TEAM_ID or APPLE_TEAM_ID must be a 10-character team identifier',
    );
  }
  return expected;
}

export function assertMacAudioInputEntitlement(path, entitlements) {
  const enabledAudioInputPattern = new RegExp(
    `<key>\\s*${escapeRegExp(MAC_AUDIO_INPUT_ENTITLEMENT)}\\s*<\\/key>\\s*<true\\s*\\/>`,
    'u',
  );
  if (!enabledAudioInputPattern.test(entitlements)) {
    throw new Error(`microphone audio-input entitlement is missing for ${path}`);
  }
}

function inspectMacAudioInputEntitlement(path) {
  const result = spawnSync('/usr/bin/codesign', ['--display', '--entitlements', ':-', path], {
    encoding: 'utf8',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`codesign entitlement inspection failed for ${path}: ${result.stderr}`);
  }
  assertMacAudioInputEntitlement(path, `${result.stdout}\n${result.stderr}`);
}

function requireMacRendererHelper(appPath) {
  const frameworksPath = join(appPath, 'Contents', 'Frameworks');
  const rendererHelpers = readdirSync(frameworksPath, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.endsWith(' Helper (Renderer).app'))
    .map((entry) => join(frameworksPath, entry.name));
  return requireUniquePath(rendererHelpers, 'packaged macOS Renderer Helper');
}

function inspectUniversalMacBinary(path) {
  const architectures = execFileSync('/usr/bin/lipo', ['-archs', path], {
    encoding: 'utf8',
  })
    .trim()
    .split(/\s+/u)
    .sort();
  if (architectures.length !== 2 || architectures[0] !== 'arm64' || architectures[1] !== 'x86_64') {
    throw new Error(`macOS binary must contain exactly arm64 and x86_64: ${path}`);
  }
  return architectures;
}

function requireMacMainExecutable(appPath) {
  const infoPath = join(appPath, 'Contents', 'Info.plist');
  const executable = execFileSync(
    '/usr/libexec/PlistBuddy',
    ['-c', 'Print :CFBundleExecutable', infoPath],
    { encoding: 'utf8' },
  ).trim();
  if (!executable || basename(executable) !== executable) {
    throw new Error('packaged macOS CFBundleExecutable is invalid');
  }
  return join(appPath, 'Contents', 'MacOS', executable);
}

function verifyMacSignatures(appPath, sidecarPath, workspaceCorePath, dmgPath) {
  execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', appPath], {
    stdio: 'inherit',
  });
  execFileSync('/usr/bin/codesign', ['--verify', '--strict', sidecarPath], {
    stdio: 'inherit',
  });
  execFileSync('/usr/bin/codesign', ['--verify', '--strict', workspaceCorePath], {
    stdio: 'inherit',
  });
  const appSignature = inspectMacSignature(appPath);
  const sidecarSignature = inspectMacSignature(sidecarPath);
  const workspaceCoreSignature = inspectMacSignature(workspaceCorePath);
  for (const [label, signature] of [
    ['sidecar', sidecarSignature],
    ['Workspace Core', workspaceCoreSignature],
  ]) {
    if (appSignature.developerIdAuthority !== signature.developerIdAuthority) {
      throw new Error(`app and ${label} Developer ID Authority values do not match`);
    }
    if (appSignature.teamIdentifier !== signature.teamIdentifier) {
      throw new Error(`app and ${label} TeamIdentifier values do not match`);
    }
    if (appSignature.signingCertificateSha256 !== signature.signingCertificateSha256) {
      throw new Error(`app and ${label} signing certificate fingerprints do not match`);
    }
  }
  const expectedTeamIdentifier = expectedMacTeamIdentifier();
  if (
    appSignature.teamIdentifier !== expectedTeamIdentifier ||
    sidecarSignature.teamIdentifier !== expectedTeamIdentifier ||
    workspaceCoreSignature.teamIdentifier !== expectedTeamIdentifier
  ) {
    throw new Error(
      'app, sidecar, and Workspace Core TeamIdentifier values do not match the configured release team',
    );
  }
  inspectMacAudioInputEntitlement(appPath);
  inspectMacAudioInputEntitlement(requireMacRendererHelper(appPath));
  const appArchitectures = inspectUniversalMacBinary(requireMacMainExecutable(appPath));
  const sidecarArchitectures = inspectUniversalMacBinary(sidecarPath);
  const workspaceCoreArchitectures = inspectUniversalMacBinary(workspaceCorePath);
  if (process.env.AGISTACK_REQUIRE_NOTARIZATION === '1') {
    execFileSync('/usr/sbin/spctl', ['--assess', '--type', 'execute', '--verbose=4', appPath], {
      stdio: 'inherit',
    });
    execFileSync('/usr/bin/xcrun', ['stapler', 'validate', appPath], {
      stdio: 'inherit',
    });
    execFileSync('/usr/bin/xcrun', ['stapler', 'validate', dmgPath], {
      stdio: 'inherit',
    });
    execFileSync(
      '/usr/sbin/spctl',
      [
        '--assess',
        '--type',
        'open',
        '--context',
        'context:primary-signature',
        '--verbose=4',
        dmgPath,
      ],
      { stdio: 'inherit' },
    );
  } else {
    throw new Error('macOS tag release requires notarization verification');
  }
  return {
    architecture: 'universal',
    app_architectures: appArchitectures,
    sidecar_architectures: sidecarArchitectures,
    workspace_core_architectures: workspaceCoreArchitectures,
    developer_id_authority: appSignature.developerIdAuthority,
    team_identifier: appSignature.teamIdentifier,
    signing_certificate_sha256: appSignature.signingCertificateSha256,
    same_signature_identity: true,
    app_signature_valid: true,
    sidecar_signature_valid: true,
    workspace_core_signature_valid: true,
    notarization_verified: true,
    app_stapler_valid: true,
    dmg_stapler_valid: true,
    app_spctl_valid: true,
    dmg_spctl_valid: true,
  };
}

function normalizedWindowsThumbprint() {
  const normalized = (process.env.WIN_CSC_SHA1 ?? '').replace(/\s/gu, '').toUpperCase();
  if (!/^[A-F0-9]{40}$/u.test(normalized)) {
    throw new Error('WIN_CSC_SHA1 must be a 40-character certificate thumbprint');
  }
  return normalized;
}

function verifyWindowsSignatures(installerPath, sidecarPath, workspaceCorePath) {
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
      workspaceCorePath,
    ],
    { stdio: 'inherit' },
  );
  return {
    signer_thumbprint: expectedThumbprint,
    installer_authenticode_valid: true,
    sidecar_authenticode_valid: true,
    workspace_core_authenticode_valid: true,
  };
}

function verifyLinuxBinaryArchitecture(path, expectedArchitecture, label) {
  const description = execFileSync('file', ['-b', path], {
    encoding: 'utf8',
  }).trim();
  const matches =
    expectedArchitecture === 'x64'
      ? /(?:x86-64|x86_64)/u.test(description)
      : expectedArchitecture === 'arm64'
        ? /(?:ARM aarch64|aarch64)/iu.test(description)
        : false;
  if (!matches) {
    throw new Error(`${label} architecture does not match ${expectedArchitecture}: ${description}`);
  }
}

async function inspectDesktopEntry(path, label) {
  const source = await readFile(path, 'utf8');
  const lines = source.split(/\r?\n/u).map((line) => line.trim());
  if (!lines.includes('[Desktop Entry]')) {
    throw new Error(`${label} is missing [Desktop Entry]`);
  }
  const fields = new Map(
    lines
      .filter((line) => line && !line.startsWith('#') && line.includes('='))
      .map((line) => {
        const separator = line.indexOf('=');
        return [line.slice(0, separator), line.slice(separator + 1)];
      }),
  );
  if (
    fields.get('Type') !== 'Application' ||
    !fields.get('Name')?.trim() ||
    !fields.get('Exec')?.trim()
  ) {
    throw new Error(`${label} desktop entry contract is invalid`);
  }
  return basename(path);
}

async function verifyLinuxPackages({
  metadataResult,
  sidecarPath,
  sidecarName,
  expectedSidecarSha256,
  workspaceCorePath,
  workspaceCoreName,
  expectedWorkspaceCoreSha256,
}) {
  const architecture = metadataResult.architecture;
  const appImagePath = requireUniquePath(
    metadataResult.installers.filter((path) => path.endsWith('.AppImage')),
    'Linux AppImage',
  );
  const debPath = requireUniquePath(
    metadataResult.installers.filter((path) => path.endsWith('.deb')),
    'Linux deb',
  );
  const appImageMode = (await stat(appImagePath)).mode;
  if ((appImageMode & 0o111) === 0) {
    throw new Error('Linux AppImage is not executable');
  }
  verifyLinuxBinaryArchitecture(appImagePath, architecture, 'Linux AppImage');
  verifyLinuxBinaryArchitecture(sidecarPath, architecture, 'Linux sidecar');
  verifyLinuxBinaryArchitecture(workspaceCorePath, architecture, 'Linux Workspace Core');

  const debArchitecture = execFileSync('dpkg-deb', ['--field', debPath, 'Architecture'], {
    encoding: 'utf8',
  }).trim();
  const expectedDebArchitecture = architecture === 'x64' ? 'amd64' : architecture;
  if (debArchitecture !== expectedDebArchitecture) {
    throw new Error(
      `Linux deb architecture must be ${expectedDebArchitecture}; found ${debArchitecture}`,
    );
  }

  const appImageTemp = await mkdtemp(join(tmpdir(), 'agistack-appimage-extract-'));
  const debTemp = await mkdtemp(join(tmpdir(), 'agistack-deb-extract-'));
  try {
    const extraction = spawnSync(appImagePath, ['--appimage-extract'], {
      cwd: appImageTemp,
      encoding: 'utf8',
    });
    if (extraction.error) throw extraction.error;
    if (extraction.status !== 0) {
      throw new Error(`AppImage extract smoke failed: ${extraction.stderr || extraction.stdout}`);
    }
    const appImageRoot = join(appImageTemp, 'squashfs-root');
    const appRunPath = join(appImageRoot, 'AppRun');
    const appRunMode = (await stat(appRunPath)).mode;
    if ((appRunMode & 0o111) === 0) {
      throw new Error('extracted AppImage AppRun is not executable');
    }
    const appImageEntries = await collectEntries(appImageRoot);
    const appImageDesktopEntry = requireUniquePath(
      appImageEntries.files.filter(
        (path) => relative(appImageRoot, path).split(sep).length === 1 && path.endsWith('.desktop'),
      ),
      'AppImage desktop entry',
    );
    const appImageSidecar = requireFile(
      appImageEntries.files.filter((path) => path.includes(`${sep}resources${sep}sidecar${sep}`)),
      sidecarName,
    );
    const appImageSidecarSha256 = await verifySidecarDigest(appImageSidecar, sidecarName);
    if (appImageSidecarSha256 !== expectedSidecarSha256) {
      throw new Error('AppImage sidecar does not match the verified unpacked sidecar');
    }
    verifyLinuxBinaryArchitecture(appImageSidecar, architecture, 'AppImage sidecar');
    const appImageWorkspaceCore = requireFile(
      appImageEntries.files.filter((path) =>
        path.includes(`${sep}resources${sep}workspace-core${sep}`),
      ),
      workspaceCoreName,
    );
    const appImageWorkspaceCoreSha256 = await verifyWorkspaceCoreDigest(
      appImageWorkspaceCore,
      workspaceCoreName,
    );
    if (appImageWorkspaceCoreSha256 !== expectedWorkspaceCoreSha256) {
      throw new Error('AppImage Workspace Core does not match the verified unpacked helper');
    }
    verifyLinuxBinaryArchitecture(appImageWorkspaceCore, architecture, 'AppImage Workspace Core');

    execFileSync('dpkg-deb', ['--extract', debPath, debTemp], {
      stdio: 'inherit',
    });
    const debEntries = await collectEntries(debTemp);
    const debDesktopEntry = requireUniquePath(
      debEntries.files.filter(
        (path) =>
          path.includes(`${sep}usr${sep}share${sep}applications${sep}`) &&
          path.endsWith('.desktop'),
      ),
      'deb desktop entry',
    );
    const debSidecar = requireFile(
      debEntries.files.filter((path) => path.includes(`${sep}resources${sep}sidecar${sep}`)),
      sidecarName,
    );
    const debSidecarSha256 = await verifySidecarDigest(debSidecar, sidecarName);
    if (debSidecarSha256 !== expectedSidecarSha256) {
      throw new Error('deb sidecar does not match the verified unpacked sidecar');
    }
    verifyLinuxBinaryArchitecture(debSidecar, architecture, 'deb sidecar');
    const debWorkspaceCore = requireFile(
      debEntries.files.filter((path) => path.includes(`${sep}resources${sep}workspace-core${sep}`)),
      workspaceCoreName,
    );
    const debWorkspaceCoreSha256 = await verifyWorkspaceCoreDigest(
      debWorkspaceCore,
      workspaceCoreName,
    );
    if (debWorkspaceCoreSha256 !== expectedWorkspaceCoreSha256) {
      throw new Error('deb Workspace Core does not match the verified unpacked helper');
    }
    verifyLinuxBinaryArchitecture(debWorkspaceCore, architecture, 'deb Workspace Core');

    return {
      architecture,
      deb_architecture: debArchitecture,
      sidecar_executable: true,
      workspace_core_executable: true,
      package_sidecars_identical: true,
      package_workspace_cores_identical: true,
      appimage_executable: true,
      appimage_extract_smoke: true,
      deb_extract_smoke: true,
      appimage_desktop_entry: await inspectDesktopEntry(appImageDesktopEntry, 'AppImage'),
      deb_desktop_entry: await inspectDesktopEntry(debDesktopEntry, 'deb'),
    };
  } finally {
    await rm(appImageTemp, { recursive: true, force: true });
    await rm(debTemp, { recursive: true, force: true });
  }
}

async function main() {
  const packageJson = JSON.parse(await readFile(packageJsonPath, 'utf8'));
  const platform = process.platform;
  const policy = platformPolicy(platform);
  const releaseRoot = defaultReleaseRoot;
  const expectedVersion = process.env.AGISTACK_EXPECTED_VERSION;
  const expectedTag = process.env.AGISTACK_EXPECTED_TAG;
  if (!expectedVersion || !expectedTag) {
    throw new Error('AGISTACK_EXPECTED_VERSION and AGISTACK_EXPECTED_TAG are required');
  }
  const sidecarName =
    platform === 'win32' ? 'agistack-desktop-sidecar.exe' : 'agistack-desktop-sidecar';
  const workspaceCoreName =
    platform === 'win32' ? 'memstack-workspace-core.exe' : 'memstack-workspace-core';
  const metadataResult = await verifyReleaseRootMetadata({
    releaseRoot,
    platform,
    version: packageJson.version,
    expectedTag,
    expectedVersion,
  });

  const { files } = await collectEntries(releaseRoot);
  let sidecarPath;
  let workspaceCorePath;
  let verifiedSidecarSource;
  let packageVerification;
  if (platform === 'darwin') {
    const zipPath = requireUniquePath(
      metadataResult.installers.filter((path) => path.endsWith('.zip')),
      'uploaded macOS zip',
    );
    const dmgPath = requireUniquePath(
      metadataResult.installers.filter((path) => path.endsWith('.dmg')),
      'uploaded macOS dmg',
    );
    packageVerification = await verifyMacPackageArtifacts({
      zipPath,
      dmgPath,
      inspectAppBundle: async (appPath) => {
        const packagedSidecarPath = join(appPath, 'Contents', 'Resources', 'sidecar', sidecarName);
        const packagedWorkspaceCorePath = join(
          appPath,
          'Contents',
          'Resources',
          'workspace-core',
          workspaceCoreName,
        );
        const sidecarSha256 = await verifySidecarDigest(packagedSidecarPath, sidecarName);
        const workspaceCoreSha256 = await verifyWorkspaceCoreDigest(
          packagedWorkspaceCorePath,
          workspaceCoreName,
        );
        return {
          ...verifyMacSignatures(appPath, packagedSidecarPath, packagedWorkspaceCorePath, dmgPath),
          sidecar_sha256: sidecarSha256,
          workspace_core_sha256: workspaceCoreSha256,
        };
      },
    });
    verifiedSidecarSource = 'uploaded-macos-zip-and-dmg';
  } else if (platform === 'win32') {
    const installerPath = requireUniquePath(
      metadataResult.installers.filter((path) => path.endsWith('.exe')),
      'uploaded Windows NSIS installer',
    );
    packageVerification = await verifyWindowsInstallerArtifact({
      installerPath,
      expectedArchitecture: metadataResult.architecture,
      sidecarName,
      workspaceCoreName,
      inspectInstallerPayload: async ({ packagedSidecarPath, packagedWorkspaceCorePath }) => {
        const sidecarSha256 = await verifySidecarDigest(packagedSidecarPath, sidecarName);
        const workspaceCoreSha256 = await verifyWorkspaceCoreDigest(
          packagedWorkspaceCorePath,
          workspaceCoreName,
        );
        const sidecarArchitecture = inspectPortableExecutableArchitecture(
          await readFile(packagedSidecarPath),
        );
        const workspaceCoreArchitecture = inspectPortableExecutableArchitecture(
          await readFile(packagedWorkspaceCorePath),
        );
        return {
          ...verifyWindowsSignatures(installerPath, packagedSidecarPath, packagedWorkspaceCorePath),
          sidecar_sha256: sidecarSha256,
          workspace_core_sha256: workspaceCoreSha256,
          sidecar_architecture: sidecarArchitecture,
          workspace_core_architecture: workspaceCoreArchitecture,
        };
      },
    });
    packageVerification = {
      architecture: metadataResult.architecture,
      ...packageVerification,
    };
    verifiedSidecarSource = 'uploaded-windows-nsis-installer';
  } else if (platform === 'linux') {
    sidecarPath = requireFile(
      files.filter((path) => path.includes(`linux-unpacked${sep}`)),
      sidecarName,
    );
    workspaceCorePath = requireFile(
      files.filter(
        (path) =>
          path.includes(`linux-unpacked${sep}`) &&
          path.includes(`${sep}resources${sep}workspace-core${sep}`),
      ),
      workspaceCoreName,
    );
    const sidecarSha256 = await verifySidecarDigest(sidecarPath, sidecarName);
    const workspaceCoreSha256 = await verifyWorkspaceCoreDigest(
      workspaceCorePath,
      workspaceCoreName,
    );
    packageVerification = {
      ...(await verifyLinuxPackages({
        metadataResult,
        sidecarPath,
        sidecarName,
        expectedSidecarSha256: sidecarSha256,
        workspaceCorePath,
        workspaceCoreName,
        expectedWorkspaceCoreSha256: workspaceCoreSha256,
      })),
      sidecar_sha256: sidecarSha256,
      workspace_core_sha256: workspaceCoreSha256,
    };
    verifiedSidecarSource = relative(releaseRoot, sidecarPath);
  } else {
    throw new Error(`unsupported release verification platform: ${platform}`);
  }

  const evidencePath = await writeReleaseEvidence({
    releaseRoot,
    policy,
    version: packageJson.version,
    expectedVersion,
    tag: expectedTag,
    commitSha: process.env.AGISTACK_RELEASE_COMMIT_SHA,
    runId: process.env.AGISTACK_RELEASE_RUN_ID,
    runAttempt: process.env.AGISTACK_RELEASE_RUN_ATTEMPT,
    runUrl: process.env.AGISTACK_RELEASE_RUN_URL,
    artifactPaths: metadataResult.publishableArtifacts,
    packageVerification,
  });
  process.stdout.write(
    `DESKTOP_RELEASE_ARTIFACTS_VERIFIED platform=${platform} ` +
      `sidecar=${verifiedSidecarSource} evidence=${basename(evidencePath)}\n`,
  );
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  await main();
}
