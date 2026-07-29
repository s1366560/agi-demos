import { execFileSync } from 'node:child_process';
import { mkdtemp, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, join, relative, sep } from 'node:path';

function requireUniquePath(paths, label) {
  if (paths.length !== 1) {
    throw new Error(
      `${label} must have exactly one match; found ${paths.length}`,
    );
  }
  return paths[0];
}

async function collectEntries(root) {
  const files = [];
  const directories = [];
  const visit = async (directory) => {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        directories.push(path);
        await visit(path);
      } else if (entry.isFile()) {
        files.push(path);
      }
    }
  };
  await visit(root);
  return { files, directories };
}

async function requireTopLevelMacApp(root, label) {
  const { directories } = await collectEntries(root);
  return requireUniquePath(
    directories.filter((path) => {
      const relativePath = relative(root, path);
      return (
        relativePath.split(sep).length === 1 && relativePath.endsWith('.app')
      );
    }),
    label,
  );
}

async function extractMacZip(zipPath, destination) {
  execFileSync('/usr/bin/ditto', ['-x', '-k', zipPath, destination], {
    stdio: 'inherit',
  });
}

async function withMountedMacDmg(dmgPath, inspect) {
  const mountRoot = await mkdtemp(join(tmpdir(), 'agistack.dmg-mounted-'));
  let attached = false;
  try {
    execFileSync(
      '/usr/bin/hdiutil',
      [
        'attach',
        dmgPath,
        '-readonly',
        '-nobrowse',
        '-noautoopen',
        '-mountpoint',
        mountRoot,
      ],
      { stdio: 'inherit' },
    );
    attached = true;
    return await inspect(mountRoot);
  } finally {
    if (attached) {
      execFileSync('/usr/bin/hdiutil', ['detach', mountRoot], {
        stdio: 'inherit',
      });
    }
    await rm(mountRoot, { recursive: true, force: true });
  }
}

function assertMatchingMacPackageResults(zipResult, dmgResult) {
  if (zipResult.sidecar_sha256 !== dmgResult.sidecar_sha256) {
    throw new Error('zip and dmg sidecar digests do not match');
  }
  for (const field of [
    'developer_id_authority',
    'team_identifier',
    'signing_certificate_sha256',
  ]) {
    if (zipResult[field] !== dmgResult[field]) {
      throw new Error(`zip and dmg ${field} values do not match`);
    }
  }
  for (const field of ['app_architectures', 'sidecar_architectures']) {
    if (JSON.stringify(zipResult[field]) !== JSON.stringify(dmgResult[field])) {
      throw new Error(`zip and dmg ${field} values do not match`);
    }
  }
}

export async function verifyMacPackageArtifacts({
  zipPath,
  dmgPath,
  inspectAppBundle,
  extractZip = extractMacZip,
  withMountedDmg = withMountedMacDmg,
}) {
  if (typeof inspectAppBundle !== 'function') {
    throw new Error('inspectAppBundle dependency is required');
  }
  const zipRoot = await mkdtemp(join(tmpdir(), 'agistack.zip-extracted-'));
  try {
    await extractZip(zipPath, zipRoot);
    const zipAppPath = await requireTopLevelMacApp(
      zipRoot,
      'uploaded zip macOS application',
    );
    const zipResult = await inspectAppBundle(zipAppPath, 'zip');
    const dmgResult = await withMountedDmg(dmgPath, async (dmgRoot) => {
      const dmgAppPath = await requireTopLevelMacApp(
        dmgRoot,
        'uploaded dmg macOS application',
      );
      return inspectAppBundle(dmgAppPath, 'dmg');
    });
    assertMatchingMacPackageResults(zipResult, dmgResult);
    return {
      ...zipResult,
      architecture: 'universal',
      sidecar_sha256: zipResult.sidecar_sha256,
      zip_sidecar_sha256: zipResult.sidecar_sha256,
      dmg_sidecar_sha256: dmgResult.sidecar_sha256,
      package_sidecars_identical: true,
      zip_app_verified: true,
      dmg_app_verified: true,
    };
  } finally {
    await rm(zipRoot, { recursive: true, force: true });
  }
}

async function extractWithSevenZip(archivePath, destination) {
  execFileSync('7z', ['x', '-y', '-bd', `-o${destination}`, archivePath], {
    stdio: 'inherit',
  });
}

function expectedWindowsPayloadArchive(architecture) {
  if (architecture === 'x64') return 'app-64.7z';
  if (architecture === 'arm64') return 'app-arm64.7z';
  throw new Error(`unsupported Windows release architecture: ${architecture}`);
}

function pathContainsSidecarDirectory(path, root) {
  const segments = relative(root, path).split(sep);
  return segments.some(
    (segment, index) =>
      segment === 'resources' && segments[index + 1] === 'sidecar',
  );
}

export async function verifyWindowsInstallerArtifact({
  installerPath,
  expectedArchitecture,
  sidecarName,
  inspectInstallerPayload,
  extractArchive = extractWithSevenZip,
}) {
  if (typeof inspectInstallerPayload !== 'function') {
    throw new Error('inspectInstallerPayload dependency is required');
  }
  const installerRoot = await mkdtemp(
    join(tmpdir(), 'agistack.nsis-extracted-'),
  );
  const payloadRoot = await mkdtemp(join(tmpdir(), 'agistack.nsis-payload-'));
  const payloadArchiveName =
    expectedWindowsPayloadArchive(expectedArchitecture);
  try {
    await extractArchive(installerPath, installerRoot);
    const installerEntries = await collectEntries(installerRoot);
    const payloadArchivePath = requireUniquePath(
      installerEntries.files.filter(
        (path) => basename(path) === payloadArchiveName,
      ),
      `NSIS embedded ${payloadArchiveName}`,
    );
    await extractArchive(payloadArchivePath, payloadRoot);
    const payloadEntries = await collectEntries(payloadRoot);
    const packagedSidecarPath = requireUniquePath(
      payloadEntries.files.filter(
        (path) =>
          basename(path) === sidecarName &&
          pathContainsSidecarDirectory(path, payloadRoot),
      ),
      'NSIS packaged sidecar',
    );
    const inspection = await inspectInstallerPayload({
      installerPath,
      packagedSidecarPath,
      expectedArchitecture,
    });
    if (!/^[a-f0-9]{64}$/u.test(inspection.sidecar_sha256 ?? '')) {
      throw new Error('NSIS packaged sidecar SHA-256 is invalid');
    }
    if (inspection.sidecar_architecture !== expectedArchitecture) {
      throw new Error(
        `NSIS packaged sidecar architecture must be ${expectedArchitecture}; ` +
          `found ${inspection.sidecar_architecture}`,
      );
    }
    return {
      ...inspection,
      installer_payload_extracted: true,
      installer_payload_archive: payloadArchiveName,
    };
  } finally {
    await rm(installerRoot, { recursive: true, force: true });
    await rm(payloadRoot, { recursive: true, force: true });
  }
}

export function inspectPortableExecutableArchitecture(buffer) {
  if (
    !Buffer.isBuffer(buffer) ||
    buffer.byteLength < 64 ||
    buffer.readUInt16LE(0) !== 0x5a4d
  ) {
    throw new Error('portable executable header is invalid');
  }
  const headerOffset = buffer.readUInt32LE(0x3c);
  if (
    headerOffset > buffer.byteLength - 6 ||
    buffer.readUInt32LE(headerOffset) !== 0x00004550
  ) {
    throw new Error('portable executable header is invalid');
  }
  const machine = buffer.readUInt16LE(headerOffset + 4);
  if (machine === 0x8664) return 'x64';
  if (machine === 0xaa64) return 'arm64';
  throw new Error(
    `portable executable machine is unsupported: 0x${machine.toString(16)}`,
  );
}
