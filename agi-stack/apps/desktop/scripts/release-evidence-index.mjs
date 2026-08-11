import { createHash } from 'node:crypto';
import { chmodSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';

import { validateJsonSchema } from '../contracts/desktop-web-parity/schema-validator.mjs';

const scriptRoot = new URL('.', import.meta.url);
const schema = JSON.parse(
  readFileSync(
    new URL('desktop-release-package-evidence-index.v1.schema.json', scriptRoot),
    'utf8',
  ),
);
export const RELEASE_EVIDENCE_INDEX_NAME = 'release-evidence-index-v3.json';
export const RELEASE_PACKAGE_EVIDENCE_INDEX_NAME = 'release-package-evidence-index-v1.json';
export const REQUIRED_PROMOTION_CHECKS = Object.freeze([
  'macos_install_launch',
  'windows_install_launch',
  'linux_install_launch',
  'updater_apply',
  'updater_failure_rollback',
  'neo4j_runtime',
  'wcag_aa',
  'browser_bridge',
]);
export const PROMOTION_BLOCKERS = Object.freeze([
  'macos_native_qa_evidence_missing',
  'windows_native_qa_evidence_missing',
  'linux_native_qa_evidence_missing',
  'updater_apply_evidence_missing',
  'updater_failure_rollback_evidence_missing',
  'neo4j_runtime_evidence_missing',
  'wcag_aa_evidence_missing',
  'browser_bridge_evidence_missing',
]);

function assertSafeName(value, label) {
  if (typeof value !== 'string' || basename(value) !== value || value.length > 240) {
    throw new Error(`${label} is invalid`);
  }
  return value;
}

function canonicalAsset(asset) {
  const name = assertSafeName(asset?.name, 'release index asset name');
  if (
    !Number.isSafeInteger(asset?.size) ||
    asset.size <= 0 ||
    !/^[a-f0-9]{64}$/u.test(asset?.sha256 ?? '')
  ) {
    throw new Error(`release index asset is invalid: ${name}`);
  }
  return Object.freeze({ name, size: asset.size, sha256: asset.sha256 });
}

export function buildReleasePackageEvidenceIndex({
  version,
  tag,
  commitSha,
  workflowRun,
  platformEvidence,
  assets,
}) {
  const normalizedAssets = assets
    .map(canonicalAsset)
    .sort((left, right) => left.name.localeCompare(right.name));
  if (new Set(normalizedAssets.map(({ name }) => name)).size !== normalizedAssets.length) {
    throw new Error('release index assets contain duplicate names');
  }
  const normalizedPlatformEvidence = platformEvidence
    .map((entry) => ({
      platform: entry.platform,
      name: assertSafeName(entry.name, 'platform evidence name'),
      sha256: entry.sha256,
      package_status: 'passed',
      promotion_status: 'blocked',
    }))
    .sort((left, right) => left.platform.localeCompare(right.platform));
  const index = Object.freeze({
    contract_version: 'desktop-release-package-evidence-index-v1',
    version,
    tag,
    commit_sha: commitSha,
    workflow_run: workflowRun,
    release_channel: 'prerelease',
    promotion_status: 'blocked',
    promotion_blockers: [...PROMOTION_BLOCKERS],
    required_promotion_checks: [...REQUIRED_PROMOTION_CHECKS],
    platform_evidence: normalizedPlatformEvidence,
    assets: normalizedAssets,
  });
  const errors = validateJsonSchema(schema, index);
  if (errors.length > 0)
    throw new Error(`release evidence index is invalid:\n${errors.join('\n')}`);
  if (tag !== `v${version}`) throw new Error('release evidence index tag does not match version');
  const platforms = normalizedPlatformEvidence.map(({ platform }) => platform).sort();
  if (JSON.stringify(platforms) !== JSON.stringify(['linux', 'macos', 'windows'])) {
    throw new Error('release evidence index must contain each platform exactly once');
  }
  for (const evidence of normalizedPlatformEvidence) {
    const asset = normalizedAssets.find(({ name }) => name === evidence.name);
    if (!asset || asset.sha256 !== evidence.sha256) {
      throw new Error(
        `release evidence index platform digest is not asset-bound: ${evidence.platform}`,
      );
    }
  }
  return index;
}

export function writeReleasePackageEvidenceIndex({ releaseRoot, index }) {
  const path = resolve(releaseRoot, RELEASE_PACKAGE_EVIDENCE_INDEX_NAME);
  const source = `${JSON.stringify(index, null, 2)}\n`;
  if (existsSync(path)) {
    if (readFileSync(path, 'utf8') !== source) {
      throw new Error('release evidence index already exists with different bytes');
    }
    return path;
  }
  writeFileSync(path, source, { encoding: 'utf8', flag: 'wx', mode: 0o444 });
  chmodSync(path, 0o444);
  return path;
}

export function sha256File(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}
