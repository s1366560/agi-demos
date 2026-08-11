import { createHash } from 'node:crypto';
import { existsSync, lstatSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { validateJsonSchema } from '../contracts/desktop-web-parity/schema-validator.mjs';
import {
  RELEASE_EVIDENCE_INDEX_NAME,
  REQUIRED_PROMOTION_CHECKS,
} from './release-evidence-index.mjs';

const NATIVE_QA_EVIDENCE_NAME = 'release-native-qa-evidence-v1.json';
const indexSchema = JSON.parse(
  readFileSync(new URL('desktop-release-evidence-index.v3.schema.json', import.meta.url), 'utf8'),
);
const platformEvidenceSchema = JSON.parse(
  readFileSync(new URL('desktop-release-evidence.v3.schema.json', import.meta.url), 'utf8'),
);
const supplementalEvidenceSchema = JSON.parse(
  readFileSync(
    new URL('desktop-release-supplemental-evidence.v1.schema.json', import.meta.url),
    'utf8',
  ),
);
const githubReleaseAssetsSchema = JSON.parse(
  readFileSync(new URL('github-release-assets.v1.schema.json', import.meta.url), 'utf8'),
);
const REQUIRED_PLATFORM_CHECKS = Object.freeze([
  'install',
  'launch',
  'updater_apply',
  'updater_failure_rollback',
]);
const REQUIRED_PLATFORMS = Object.freeze(['linux', 'macos', 'windows']);
const REQUIRED_SUPPLEMENTAL_EVIDENCE = Object.freeze([
  'browser_bridge',
  'neo4j_runtime',
  'wcag_aa',
]);

function blocked(reason) {
  throw new Error(`promotion_status=blocked reason=${reason}`);
}

function readJson(path, missingReason, invalidReason, schema) {
  if (!existsSync(path)) blocked(missingReason);
  const stats = lstatSync(path);
  if (!stats.isFile() || stats.isSymbolicLink() || stats.size <= 0 || stats.size > 1024 * 1024) {
    blocked(invalidReason);
  }
  let value;
  try {
    value = JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    blocked(invalidReason);
  }
  if (validateJsonSchema(schema, value).length > 0) blocked(invalidReason);
  return value;
}

function sha256(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

function sha512(path) {
  return createHash('sha512').update(readFileSync(path)).digest('base64');
}

function sameReleaseIdentity(left, right) {
  return (
    left?.version === right?.version &&
    left?.tag === right?.tag &&
    left?.commit_sha === right?.commit_sha &&
    left?.channel === right?.channel &&
    left?.workflow_run?.id === right?.workflow_run?.id &&
    left?.workflow_run?.attempt === right?.workflow_run?.attempt &&
    left?.workflow_run?.url === right?.workflow_run?.url
  );
}

function assertPassedOutcome(check) {
  if (
    check?.status !== 'passed' ||
    check.reason_code !== null ||
    check.retryable !== false ||
    !Array.isArray(check.log_refs) ||
    !Array.isArray(check.artifact_refs) ||
    check.log_refs.length + check.artifact_refs.length === 0
  ) {
    blocked('required_evidence_not_passed');
  }
}

function readBoundEvidence({ root, binding, schema, missingReason, digestReason, invalidReason }) {
  const path = join(root, binding.name);
  const evidence = readJson(path, missingReason, invalidReason, schema);
  if (sha256(path) !== binding.sha256) blocked(digestReason);
  return evidence;
}

export function validatePromotionBundle({ releaseRoot = process.cwd(), env = process.env } = {}) {
  const root = resolve(releaseRoot);
  const indexPath = join(root, RELEASE_EVIDENCE_INDEX_NAME);
  const nativeQaPath = join(root, NATIVE_QA_EVIDENCE_NAME);
  const index = readJson(
    indexPath,
    'release_evidence_index_missing',
    'release_evidence_index_invalid',
    indexSchema,
  );
  const releaseIdentity = index.release_identity;
  if (
    releaseIdentity.channel !== 'prerelease' ||
    releaseIdentity.tag !== `v${releaseIdentity.version}` ||
    index.promotion_status !== 'passed'
  ) {
    blocked('release_index_state_invalid');
  }
  if (env.AGISTACK_EXPECTED_TAG && releaseIdentity.tag !== env.AGISTACK_EXPECTED_TAG) {
    blocked('requested_tag_identity_mismatch');
  }
  if (
    env.AGISTACK_EXPECTED_COMMIT_SHA &&
    releaseIdentity.commit_sha !== env.AGISTACK_EXPECTED_COMMIT_SHA
  ) {
    blocked('requested_commit_identity_mismatch');
  }
  if (
    index.required_promotion_checks.length !== REQUIRED_PROMOTION_CHECKS.length ||
    REQUIRED_PROMOTION_CHECKS.some((id) => !index.required_promotion_checks.includes(id))
  ) {
    blocked('required_promotion_checks_invalid');
  }

  const platformIds = index.platform_evidence.map(({ platform }) => platform).sort();
  if (
    JSON.stringify(platformIds) !== JSON.stringify(REQUIRED_PLATFORMS) ||
    new Set(index.platform_evidence.map(({ name }) => name)).size !== REQUIRED_PLATFORMS.length
  ) {
    blocked('platform_evidence_set_invalid');
  }
  const assetsByName = new Map(index.assets.map((asset) => [asset.name, asset]));
  if (assetsByName.size !== index.assets.length) blocked('release_asset_set_mismatch');
  for (const binding of index.platform_evidence) {
    const evidence = readBoundEvidence({
      root,
      binding,
      schema: platformEvidenceSchema,
      missingReason: 'platform_evidence_missing',
      digestReason: 'platform_evidence_digest_mismatch',
      invalidReason: 'platform_evidence_invalid',
    });
    if (
      !sameReleaseIdentity(evidence.release_identity, releaseIdentity) ||
      evidence.platform.os !== binding.platform ||
      evidence.platform.environment !== 'physical' ||
      evidence.judgment_revision !== binding.judgment_revision
    ) {
      blocked('platform_evidence_identity_mismatch');
    }
    const artifact = assetsByName.get(evidence.artifact_identity.name);
    if (
      !artifact ||
      artifact.github_asset_id !== evidence.artifact_identity.github_asset_id ||
      artifact.size !== evidence.artifact_identity.size ||
      artifact.sha256 !== evidence.artifact_identity.sha256 ||
      artifact.sha512 !== evidence.artifact_identity.sha512
    ) {
      blocked('platform_artifact_identity_mismatch');
    }
    const checks = new Map(evidence.checks.map((check) => [check.id, check]));
    if (
      checks.size !== evidence.checks.length ||
      REQUIRED_PLATFORM_CHECKS.some((id) => !checks.has(id))
    ) {
      blocked('platform_evidence_check_set_invalid');
    }
    assertPassedOutcome(evidence.artifact_identity.signature);
    assertPassedOutcome(evidence.artifact_identity.attestation);
    for (const id of REQUIRED_PLATFORM_CHECKS) assertPassedOutcome(checks.get(id));
  }

  const supplementalIds = index.supplemental_evidence.map(({ id }) => id).sort();
  if (
    JSON.stringify(supplementalIds) !== JSON.stringify(REQUIRED_SUPPLEMENTAL_EVIDENCE) ||
    new Set(index.supplemental_evidence.map(({ name }) => name)).size !==
      REQUIRED_SUPPLEMENTAL_EVIDENCE.length
  ) {
    blocked('supplemental_evidence_set_invalid');
  }
  for (const binding of index.supplemental_evidence) {
    const evidence = readBoundEvidence({
      root,
      binding,
      schema: supplementalEvidenceSchema,
      missingReason: 'supplemental_evidence_missing',
      digestReason: 'supplemental_evidence_digest_mismatch',
      invalidReason: 'supplemental_evidence_invalid',
    });
    if (
      evidence.id !== binding.id ||
      evidence.check.id !== binding.id ||
      evidence.judgment_revision !== binding.judgment_revision ||
      !sameReleaseIdentity(evidence.release_identity, releaseIdentity)
    ) {
      blocked('supplemental_evidence_identity_mismatch');
    }
    assertPassedOutcome(evidence.check);
  }

  const expectedNames = new Set([
    ...index.assets.map(({ name }) => name),
    ...index.platform_evidence.map(({ name }) => name),
    ...index.supplemental_evidence.map(({ name }) => name),
    RELEASE_EVIDENCE_INDEX_NAME,
  ]);
  if (existsSync(nativeQaPath)) expectedNames.add(NATIVE_QA_EVIDENCE_NAME);
  const actualNames = readdirSync(root)
    .filter((name) => statSync(join(root, name)).isFile())
    .sort();
  if (
    actualNames.length !== expectedNames.size ||
    actualNames.some((name) => basename(name) !== name || !expectedNames.has(name))
  ) {
    blocked('release_asset_set_mismatch');
  }
  for (const asset of index.assets) {
    const path = join(root, asset.name);
    const stats = lstatSync(path);
    if (
      !stats.isFile() ||
      stats.isSymbolicLink() ||
      stats.size !== asset.size ||
      sha256(path) !== asset.sha256 ||
      sha512(path) !== asset.sha512
    ) {
      blocked('release_asset_digest_mismatch');
    }
  }
  if (!env.AGISTACK_GITHUB_RELEASE_ASSET_MANIFEST) {
    blocked('github_asset_manifest_missing');
  }
  const githubAssetManifest = readJson(
    resolve(env.AGISTACK_GITHUB_RELEASE_ASSET_MANIFEST),
    'github_asset_manifest_missing',
    'github_asset_manifest_invalid',
    githubReleaseAssetsSchema,
  );
  if (githubAssetManifest.tag !== releaseIdentity.tag) {
    blocked('github_asset_manifest_identity_mismatch');
  }
  const liveAssetsByName = new Map(githubAssetManifest.assets.map((asset) => [asset.name, asset]));
  if (
    liveAssetsByName.size !== githubAssetManifest.assets.length ||
    new Set(githubAssetManifest.assets.map(({ github_asset_id: id }) => id)).size !==
      githubAssetManifest.assets.length ||
    liveAssetsByName.size !== expectedNames.size ||
    [...expectedNames].some((name) => !liveAssetsByName.has(name))
  ) {
    blocked('github_asset_set_mismatch');
  }
  for (const name of expectedNames) {
    const path = join(root, name);
    const liveAsset = liveAssetsByName.get(name);
    const stats = lstatSync(path);
    if (
      !stats.isFile() ||
      stats.isSymbolicLink() ||
      stats.size !== liveAsset.size ||
      `sha256:${sha256(path)}` !== liveAsset.digest
    ) {
      blocked('github_asset_digest_mismatch');
    }
  }
  for (const asset of index.assets) {
    const liveAsset = liveAssetsByName.get(asset.name);
    if (
      liveAsset.github_asset_id !== asset.github_asset_id ||
      liveAsset.name !== asset.name ||
      liveAsset.size !== asset.size ||
      liveAsset.digest !== `sha256:${asset.sha256}`
    ) {
      blocked('github_asset_identity_mismatch');
    }
  }
  return Object.freeze({
    promotion_status: 'passed',
    version: releaseIdentity.version,
    tag: releaseIdentity.tag,
    commit_sha: releaseIdentity.commit_sha,
  });
}

function main() {
  if (process.argv[2] !== 'validate-promotion') {
    throw new Error(`unknown promotion validation command: ${process.argv[2]}`);
  }
  const result = validatePromotionBundle({
    releaseRoot: resolve(process.argv[3]),
  });
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
