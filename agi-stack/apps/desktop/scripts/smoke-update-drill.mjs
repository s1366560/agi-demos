import { spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { chmodSync, copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  UPDATE_DRILL_SCHEMA,
  releaseEvidenceDir,
  writeEvidenceFragment,
} from './release-evidence.mjs';
import { probeSidecarHealth, sidecarProbeEnvironment } from './sidecar-health-probe.mjs';
import { applyUpdateWithRollback } from './updater-transaction.mjs';

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function sidecarNameFor(platform) {
  return platform === 'win32' ? 'agistack-desktop-sidecar.exe' : 'agistack-desktop-sidecar';
}

function workspaceCoreNameFor(platform) {
  return platform === 'win32' ? 'memstack-workspace-core.exe' : 'memstack-workspace-core';
}

/** Synthetic N/N+1 markers derived from the package version: patch bump. */
export function drillVersions(version) {
  const match = /^(\d+)\.(\d+)\.(\d+)$/u.exec(version);
  if (!match) {
    throw new Error(`drill versions require a semver package version; found ${version}`);
  }
  return {
    base: version,
    candidate: `${match[1]}.${match[2]}.${Number(match[3]) + 1}`,
    rollbackProbe: `${match[1]}.${match[2]}.${Number(match[3]) + 2}`,
  };
}

function privateJson(path, value) {
  writeFileSync(path, `${JSON.stringify(value)}\n`, { encoding: 'utf8', mode: 0o600 });
  chmodSync(path, 0o600);
}

/**
 * Snapshot the installed tree through the real sidecar recovery helper, the
 * same `--update-recovery-prepare` operation the production recovery path
 * uses before an update is staged.
 */
export function defaultPrepareSnapshot({
  sidecarPath,
  targetPath,
  ownedRoot,
  snapshotRoot,
  manifestPath,
  requestDirectory,
}) {
  mkdirSync(ownedRoot, { recursive: true, mode: 0o700 });
  chmodSync(ownedRoot, 0o700);
  const requestPath = join(requestDirectory, 'prepare.json');
  privateJson(requestPath, {
    operation: 'prepare',
    schemaVersion: 1,
    targetPath,
    ownedRoot,
    snapshotRoot,
    manifestPath,
  });
  const prepared = spawnSync(sidecarPath, ['--update-recovery-prepare'], {
    encoding: 'utf8',
    env: {
      ...sidecarProbeEnvironment(),
      AGISTACK_UPDATE_RECOVERY_REQUEST: requestPath,
    },
    timeout: 120_000,
    windowsHide: true,
  });
  if (prepared.error) throw prepared.error;
  if (prepared.status !== 0) {
    throw new Error('recovery snapshot preparation failed');
  }
  const snapshot = JSON.parse(prepared.stdout);
  if (
    typeof snapshot.manifestSha512 !== 'string' ||
    !Number.isSafeInteger(snapshot.manifestSize)
  ) {
    throw new Error('recovery snapshot manifest is invalid');
  }
  return Object.freeze({
    manifest_sha512_bytes: Buffer.from(snapshot.manifestSha512, 'base64').byteLength,
    manifest_size: snapshot.manifestSize,
    prepared: true,
  });
}

/**
 * Run the synthetic N -> N+1 update drill against the real staged sidecar:
 * transactional apply with a real sidecar health probe as the post-apply
 * validation, version-marker assertion, then two genuine failed-update
 * rollback drills (version-marker mismatch and corrupt sidecar binary).
 */
export async function runUpdateDrill({
  platform = process.platform,
  version,
  tag,
  evidenceDir = releaseEvidenceDir(),
  sidecarSourcePath = resolve(
    desktopRoot,
    'build',
    'sidecar',
    sidecarNameFor(platform),
  ),
  workspaceCoreSourcePath = resolve(
    desktopRoot,
    'build',
    'workspace-core',
    workspaceCoreNameFor(platform),
  ),
  probe = probeSidecarHealth,
  prepareSnapshot = defaultPrepareSnapshot,
  applyUpdate = applyUpdateWithRollback,
  rootDirectory,
} = {}) {
  if (!version || !tag) {
    throw new Error('update drill requires version and tag');
  }
  const { base, candidate, rollbackProbe } = drillVersions(version);
  const sidecarName = sidecarNameFor(platform);
  const workspaceCoreName = workspaceCoreNameFor(platform);

  const ownedRoot = rootDirectory === undefined;
  const root = rootDirectory ?? mkdtempSync(join(tmpdir(), 'agistack-update-drill-'));
  const installed = join(root, 'installed');

  const seed = async (directory, marker) => {
    mkdirSync(directory, { recursive: true });
    copyFileSync(sidecarSourcePath, join(directory, sidecarName));
    copyFileSync(workspaceCoreSourcePath, join(directory, workspaceCoreName));
    if (platform !== 'win32') {
      chmodSync(join(directory, sidecarName), 0o700);
      chmodSync(join(directory, workspaceCoreName), 0o700);
    }
    writeFileSync(join(directory, 'version.txt'), marker, 'utf8');
  };
  const markerAt = async (directory) =>
    readFile(join(directory, 'version.txt'), 'utf8');
  const probeInstallation = async (directory) => {
    await probe({
      sidecarPath: join(directory, sidecarName),
      workspaceCorePath: join(directory, workspaceCoreName),
      handshakeTimeoutMs: 60_000,
    });
  };
  const validateCandidate = (expectedMarker) => async (directory) => {
    if ((await markerAt(directory)) !== expectedMarker) return false;
    await probeInstallation(directory);
    return true;
  };

  try {
    await seed(installed, base);
    const snapshot = prepareSnapshot({
      sidecarPath: join(installed, sidecarName),
      targetPath: installed,
      ownedRoot: join(root, 'owned'),
      snapshotRoot: join(root, 'owned', 'snapshot'),
      manifestPath: join(root, 'owned', 'snapshot', 'manifest.json'),
      requestDirectory: root,
    });

    // Apply N -> N+1: transaction rename plus real sidecar health validation.
    const candidateDirectory = join(root, 'candidate');
    await seed(candidateDirectory, candidate);
    const applied = await applyUpdate({
      installedPath: installed,
      stagedPath: candidateDirectory,
      validate: validateCandidate(candidate),
    });
    if (!applied.applied) {
      throw new Error('update drill apply did not report success');
    }
    const reportedVersion = await markerAt(installed);
    if (reportedVersion !== candidate) {
      throw new Error('updated installation does not report the candidate version');
    }
    await probeInstallation(installed);

    // Failed-update rollback drill A: post-apply validation rejects the
    // candidate because its version marker is corrupt.
    const rollbackDrills = [];
    const markerMismatchDirectory = join(root, 'candidate-marker-mismatch');
    await seed(markerMismatchDirectory, '0.0.0-corrupt-marker');
    let markerRejected = false;
    try {
      await applyUpdate({
        installedPath: installed,
        stagedPath: markerMismatchDirectory,
        validate: validateCandidate(rollbackProbe),
      });
    } catch {
      markerRejected = true;
    }
    if (!markerRejected) {
      throw new Error('corrupt-marker candidate must be rejected');
    }
    const restoredAfterMarker = await markerAt(installed);
    if (restoredAfterMarker !== candidate) {
      throw new Error('marker-mismatch rollback did not restore the previous installation');
    }
    await probeInstallation(installed);
    rollbackDrills.push({
      mode: 'version_marker_mismatch',
      update_rejected: true,
      restored_version: restoredAfterMarker,
      sidecar_probe_after_restore: 'passed',
    });

    // Failed-update rollback drill B: the candidate sidecar binary is corrupt,
    // so the real health probe fails after the transactional rename.
    const corruptBinaryDirectory = join(root, 'candidate-corrupt-binary');
    await seed(corruptBinaryDirectory, rollbackProbe);
    await writeFile(join(corruptBinaryDirectory, sidecarName), randomBytes(256));
    if (platform !== 'win32') {
      chmodSync(join(corruptBinaryDirectory, sidecarName), 0o700);
    }
    let binaryRejected = false;
    try {
      await applyUpdate({
        installedPath: installed,
        stagedPath: corruptBinaryDirectory,
        validate: validateCandidate(rollbackProbe),
      });
    } catch {
      binaryRejected = true;
    }
    if (!binaryRejected) {
      throw new Error('corrupt-binary candidate must be rejected');
    }
    const restoredAfterBinary = await markerAt(installed);
    if (restoredAfterBinary !== candidate) {
      throw new Error('corrupt-binary rollback did not restore the previous installation');
    }
    await probeInstallation(installed);
    rollbackDrills.push({
      mode: 'corrupt_sidecar_binary',
      update_rejected: true,
      restored_version: restoredAfterBinary,
      sidecar_probe_after_restore: 'passed',
    });

    const fragment = {
      schema: UPDATE_DRILL_SCHEMA,
      platform,
      version,
      tag,
      generated_at: new Date().toISOString(),
      base_version: base,
      candidate_version: candidate,
      rollback_probe_version: rollbackProbe,
      snapshot,
      apply: {
        applied: true,
        version_reported: reportedVersion,
        sidecar_probe: 'passed',
      },
      rollback_drills: rollbackDrills,
      coverage: {
        synthetic_versions_from_single_build: true,
        binaries_identical_across_versions: true,
        transaction_rename_apply: true,
        recovery_snapshot_prepare: true,
        post_apply_version_assertion: true,
        failed_update_rollback: true,
        journal_assisted_recovery_helper: 'covered_by_smoke_update_recovery_step',
        electron_updater_feed_apply: false,
        differential_blockmap_apply: false,
        installed_app_self_update_restart: false,
      },
      not_covered: [
        'electron_updater_hosted_feed_apply',
        'differential_blockmap_apply',
        'genuine_two_signed_build_chain',
        'installed_app_self_update_restart',
      ],
    };
    const path = await writeEvidenceFragment('update-drill.json', fragment, { evidenceDir });
    process.stdout.write(
      `UPDATE_DRILL_OK platform=${platform} applied=${candidate} ` +
        `rollback_drills=${rollbackDrills.length} evidence=${path}\n`,
    );
    return fragment;
  } finally {
    if (ownedRoot) rmSync(root, { recursive: true, force: true });
  }
}

async function main() {
  await runUpdateDrill({
    version: process.env.AGISTACK_EXPECTED_VERSION,
    tag: process.env.AGISTACK_EXPECTED_TAG,
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
