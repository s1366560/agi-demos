import { chmod, mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { verifyReleaseRootMetadata } from './release-artifact-contract.mjs';

export const RELEASE_EVIDENCE_SCHEMA = 'desktop-release-evidence-v3';
export const RELEASE_EVIDENCE_SUPERSEDES = 'desktop-release-evidence-v2';
export const INSTALL_LAUNCH_SMOKE_SCHEMA = 'install-launch-smoke-v1';
export const UPDATE_DRILL_SCHEMA = 'update-transaction-drill-v1';
export const BLOCKMAP_VERIFICATION_SCOPE = 'blockmap_structure_and_coverage_only';

// v3 keeps the v2 package-artifact gate and adds the Wave 8 native gates.
// Older tags remain described by desktop-release-evidence-v2 with
// evidence_scope `package_artifacts_only`; that scope string is not reused
// here because v3 evidence covers more than static package artifacts.
export const EVIDENCE_SCOPE = Object.freeze([
  'package_artifact_verification',
  'install_launch_smoke',
  'update_transaction_drill',
]);
export const RELEASE_DISPOSITION = 'draft_until_wave8_native_gates_pass';

const EVIDENCE_NOT_COVERED = Object.freeze([
  'electron_updater_hosted_feed_apply',
  'differential_blockmap_apply',
  'genuine_two_signed_build_chain',
  'installed_app_self_update_restart',
  'renderer_interactive_flows_and_signin',
]);

const EXPECTED_GATE_PLATFORMS = Object.freeze(['darwin', 'win32', 'linux']);

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export function releaseEvidenceDir(env = process.env) {
  const configured = env.AGISTACK_RELEASE_EVIDENCE_DIR;
  return resolve(configured ?? join(desktopRoot, 'build', 'release-evidence'));
}

function assertRecord(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value;
}

export async function writeEvidenceFragment(
  name,
  value,
  { evidenceDir = releaseEvidenceDir() } = {},
) {
  assertRecord(value, `evidence fragment ${name}`);
  if (typeof value.schema !== 'string' || value.schema.length === 0) {
    throw new Error(`evidence fragment ${name} must declare a schema`);
  }
  await mkdir(evidenceDir, { recursive: true, mode: 0o700 });
  await chmod(evidenceDir, 0o700).catch(() => {});
  const path = join(evidenceDir, name);
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
  return path;
}

export async function readEvidenceFragment(evidenceDir, name, expectedSchema) {
  const path = join(resolve(evidenceDir), name);
  const fragment = assertRecord(
    JSON.parse(await readFile(path, 'utf8')),
    `evidence fragment ${name}`,
  );
  if (fragment.schema !== expectedSchema) {
    throw new Error(`evidence fragment ${name} must use schema ${expectedSchema}`);
  }
  return fragment;
}

function assertFragmentIdentity(fragment, { platform, version, tag }, label) {
  if (
    fragment.platform !== platform ||
    fragment.version !== version ||
    fragment.tag !== tag
  ) {
    throw new Error(`${label} does not match this release platform, version, and tag`);
  }
}

export function assertInstallLaunchEvidence(fragment) {
  if (!Array.isArray(fragment.legs) || fragment.legs.length === 0) {
    throw new Error('install-launch smoke evidence must record at least one install leg');
  }
  for (const leg of fragment.legs) {
    assertRecord(leg, 'install-launch smoke leg');
    if (
      leg.launched !== true ||
      leg.sidecar_spawned !== true ||
      leg.exit_observed !== true
    ) {
      throw new Error(`install-launch smoke leg did not pass: ${String(leg.kind)}`);
    }
    const probe = assertRecord(leg.sidecar_probe, 'install-launch sidecar probe');
    if (probe.handshake !== 'initialize_hmac_proof_verified' || probe.clean_exit !== true) {
      throw new Error(`install-launch sidecar probe did not pass: ${String(leg.kind)}`);
    }
  }
  return true;
}

export function assertUpdateDrillEvidence(fragment) {
  const apply = assertRecord(fragment.apply, 'update drill apply evidence');
  if (
    apply.applied !== true ||
    apply.version_reported !== fragment.candidate_version ||
    apply.sidecar_probe !== 'passed'
  ) {
    throw new Error('update drill apply evidence did not pass');
  }
  if (!Array.isArray(fragment.rollback_drills) || fragment.rollback_drills.length === 0) {
    throw new Error('update drill must record at least one rollback drill');
  }
  for (const drill of fragment.rollback_drills) {
    assertRecord(drill, 'update rollback drill');
    if (
      drill.update_rejected !== true ||
      drill.restored_version !== fragment.candidate_version ||
      drill.sidecar_probe_after_restore !== 'passed'
    ) {
      throw new Error(`update rollback drill did not pass: ${String(drill.mode)}`);
    }
  }
  const coverage = assertRecord(fragment.coverage, 'update drill coverage');
  if (coverage.electron_updater_feed_apply !== false) {
    throw new Error('update drill evidence must record that no hosted updater feed ran');
  }
  return true;
}

export async function composeReleaseEvidence({
  platform = process.platform,
  releaseRoot = resolve(desktopRoot, 'release'),
  evidenceDir = releaseEvidenceDir(),
  env = process.env,
  now = () => new Date().toISOString(),
} = {}) {
  const version = env.AGISTACK_EXPECTED_VERSION;
  const tag = env.AGISTACK_EXPECTED_TAG;
  if (!version || !tag) {
    throw new Error('AGISTACK_EXPECTED_VERSION and AGISTACK_EXPECTED_TAG are required');
  }
  const metadataResult = await verifyReleaseRootMetadata({
    releaseRoot,
    platform,
    version,
    expectedTag: tag,
    expectedVersion: version,
  });

  const identity = { platform, version, tag };
  const installLaunch = await readEvidenceFragment(
    evidenceDir,
    'install-launch-smoke.json',
    INSTALL_LAUNCH_SMOKE_SCHEMA,
  );
  assertFragmentIdentity(installLaunch, identity, 'install-launch smoke evidence');
  assertInstallLaunchEvidence(installLaunch);
  const updateDrill = await readEvidenceFragment(
    evidenceDir,
    'update-drill.json',
    UPDATE_DRILL_SCHEMA,
  );
  assertFragmentIdentity(updateDrill, identity, 'update drill evidence');
  assertUpdateDrillEvidence(updateDrill);

  const evidence = Object.freeze({
    schema: RELEASE_EVIDENCE_SCHEMA,
    supersedes: RELEASE_EVIDENCE_SUPERSEDES,
    version,
    tag,
    platform,
    generated_at: now(),
    evidence_scope: [...EVIDENCE_SCOPE],
    blockmap_verification_scope: BLOCKMAP_VERIFICATION_SCOPE,
    installers: metadataResult.installers.map((path) => basename(path)).sort(),
    install_launch_smoke: installLaunch,
    update_drill: updateDrill,
    not_covered: [...EVIDENCE_NOT_COVERED],
    release_disposition: RELEASE_DISPOSITION,
  });
  await writeEvidenceFragment('desktop-release-evidence-v3.json', evidence, { evidenceDir });
  return evidence;
}

/**
 * Bind staged promotion to the Wave 8 gate evidence: every expected platform
 * must have produced a passing v3 evidence document for this exact tag.
 */
export async function verifyTagEvidence({ evidenceRoot, expectedTag }) {
  if (typeof expectedTag !== 'string' || expectedTag.length === 0) {
    throw new Error('expected release tag is required');
  }
  const root = resolve(evidenceRoot);
  const platforms = new Map();
  for (const entry of await readdir(root, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    let evidence;
    try {
      evidence = JSON.parse(
        await readFile(join(root, entry.name, 'desktop-release-evidence-v3.json'), 'utf8'),
      );
    } catch {
      continue;
    }
    assertRecord(evidence, `gate evidence ${entry.name}`);
    if (evidence.schema !== RELEASE_EVIDENCE_SCHEMA) {
      throw new Error(`gate evidence ${entry.name} must use ${RELEASE_EVIDENCE_SCHEMA}`);
    }
    if (evidence.tag !== expectedTag) {
      throw new Error(`gate evidence ${entry.name} does not match tag ${expectedTag}`);
    }
    assertInstallLaunchEvidence(assertRecord(evidence.install_launch_smoke, 'install smoke'));
    assertUpdateDrillEvidence(assertRecord(evidence.update_drill, 'update drill'));
    if (platforms.has(evidence.platform)) {
      throw new Error(`duplicate gate evidence for platform ${evidence.platform}`);
    }
    platforms.set(evidence.platform, entry.name);
  }
  const missing = EXPECTED_GATE_PLATFORMS.filter((platform) => !platforms.has(platform));
  if (missing.length > 0) {
    throw new Error(`missing Wave 8 gate evidence for platforms: ${missing.join(', ')}`);
  }
  return [...platforms.keys()].sort();
}

async function main() {
  const command = process.argv[2];
  if (command === 'compose') {
    const evidence = await composeReleaseEvidence();
    process.stdout.write(
      `DESKTOP_RELEASE_EVIDENCE_COMPOSED schema=${evidence.schema} ` +
        `platform=${evidence.platform} tag=${evidence.tag}\n`,
    );
    return;
  }
  if (command === 'verify-tag') {
    const evidenceRoot = process.argv[3];
    if (!evidenceRoot) {
      throw new Error('usage: node scripts/release-evidence.mjs verify-tag <evidence-root>');
    }
    const platforms = await verifyTagEvidence({
      evidenceRoot,
      expectedTag: process.env.GITHUB_REF_NAME,
    });
    process.stdout.write(
      `DESKTOP_RELEASE_GATE_EVIDENCE_VERIFIED tag=${process.env.GITHUB_REF_NAME} ` +
        `platforms=${platforms.join(',')}\n`,
    );
    return;
  }
  throw new Error(`unknown release evidence command: ${command}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
