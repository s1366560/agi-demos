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
const nativeQaSchema = JSON.parse(
  readFileSync(new URL('desktop-native-qa-evidence.v1.schema.json', import.meta.url), 'utf8'),
);
const githubReleaseAssetsSchema = JSON.parse(
  readFileSync(new URL('github-release-assets.v1.schema.json', import.meta.url), 'utf8'),
);
const producerManifestSchema = JSON.parse(
  readFileSync(new URL('github-workflow-producers.v1.schema.json', import.meta.url), 'utf8'),
);
const REQUIRED_PLATFORM_CHECKS = Object.freeze({
  linux: Object.freeze([
    'appimage_install',
    'appimage_launch',
    'appimage_updater_apply',
    'appimage_failure_rollback',
    'deb_install',
    'deb_upgrade',
    'deb_downgrade',
    'data_compatibility',
    'uninstall',
    'provenance',
    'file_permissions',
    'browser_bridge_registration',
  ]),
  macos: Object.freeze([
    'dmg_install',
    'dmg_launch',
    'zip_updater_apply',
    'zip_failure_rollback',
    'data_compatibility',
    'uninstall',
    'notarization',
    'gatekeeper',
    'nested_signatures',
    'browser_bridge_registration',
  ]),
  windows: Object.freeze([
    'nsis_install',
    'nsis_launch',
    'nsis_updater_apply',
    'nsis_failure_rollback',
    'data_compatibility',
    'uninstall',
    'authenticode',
    'vault_acl',
    'browser_bridge_registration',
  ]),
});
const REQUIRED_PLATFORM_PACKAGE_TYPES = Object.freeze({
  linux: Object.freeze(['appimage', 'deb']),
  macos: Object.freeze(['dmg', 'zip']),
  windows: Object.freeze(['nsis']),
});
const REQUIRED_PLATFORMS = Object.freeze(['linux', 'macos', 'windows']);
const REQUIRED_SUPPLEMENTAL_EVIDENCE = Object.freeze([
  'browser_bridge',
  'neo4j_runtime',
  'wcag_aa',
]);
const REQUIRED_BROWSER_BRIDGE_RELEASE_ASSETS = Object.freeze([
  'memstack-browser-bridge.crx',
  'qa.xml',
  'browser-bridge-enterprise-policy-bundle.json',
  'browser-bridge-enterprise-policy-member-manifest.json',
  'stable.xml.candidate',
]);
const SUPPLEMENTAL_PRODUCER_CONTRACTS = Object.freeze({
  browser_bridge: Object.freeze({
    artifactName: 'desktop-browser-bridge-release-evidence',
    requiredRefs: Object.freeze([
      'browser-bridge-macos-chrome-edge.log',
      'browser-bridge-windows-chrome-edge.log',
      'browser-bridge-linux-chrome-edge.log',
    ]),
  }),
  neo4j_runtime: Object.freeze({
    artifactName: 'desktop-neo4j-runtime-evidence',
    requiredRefs: Object.freeze(['neo4j-electron-matched-state.log']),
  }),
  wcag_aa: Object.freeze({
    artifactName: 'desktop-wcag-aa-evidence',
    requiredRefs: Object.freeze([
      'voiceover-at-ledger.jsonl',
      'nvda-at-ledger.jsonl',
      'orca-at-ledger.jsonl',
    ]),
  }),
});
const TRUSTED_SUPPLEMENTAL_WORKFLOW = '.github/workflows/desktop-release-supplemental-evidence.yml';

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

function sameProducerRun(left, right) {
  return (
    left?.workflow_path === right?.workflow_path &&
    left?.id === right?.id &&
    left?.attempt === right?.attempt &&
    left?.url === right?.url &&
    left?.head_sha === right?.head_sha &&
    left?.conclusion === right?.conclusion &&
    left?.artifact?.github_artifact_id === right?.artifact?.github_artifact_id &&
    left?.artifact?.name === right?.artifact?.name &&
    left?.artifact?.size === right?.artifact?.size &&
    left?.artifact?.sha256 === right?.artifact?.sha256 &&
    left?.artifact?.release_asset_name === right?.artifact?.release_asset_name
  );
}

function assertSupplementalProducer({ evidence, id, liveProducer, repository, assetsByName }) {
  const contract = SUPPLEMENTAL_PRODUCER_CONTRACTS[id];
  if (evidence.producer_run.workflow_path !== TRUSTED_SUPPLEMENTAL_WORKFLOW) {
    blocked('supplemental_producer_workflow_untrusted');
  }
  if (evidence.judgment_revision !== evidence.release_identity.commit_sha) {
    blocked('supplemental_judgment_revision_mismatch');
  }
  const expectedUrl = liveProducer
    ? `https://github.com/${repository}/actions/runs/${liveProducer.id}/attempts/${liveProducer.attempt}`
    : null;
  if (
    !liveProducer ||
    !sameProducerRun(evidence.producer_run, liveProducer) ||
    liveProducer.workflow_path !== TRUSTED_SUPPLEMENTAL_WORKFLOW ||
    liveProducer.head_sha !== evidence.release_identity.commit_sha ||
    liveProducer.conclusion !== 'success' ||
    liveProducer.url !== expectedUrl ||
    liveProducer.artifact.name !== contract.artifactName
  ) {
    blocked('supplemental_producer_identity_mismatch');
  }
  const producerAsset = assetsByName.get(liveProducer.artifact.release_asset_name);
  if (
    !producerAsset ||
    producerAsset.size !== liveProducer.artifact.size ||
    producerAsset.sha256 !== liveProducer.artifact.sha256
  ) {
    blocked('supplemental_producer_artifact_mismatch');
  }
  const references = new Set(evidence.check.artifact_refs.map(({ name }) => name));
  if (contract.requiredRefs.some((name) => !references.has(name))) {
    blocked('supplemental_evidence_required_refs_incomplete');
  }
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

function assertJudgmentLedger(evidence) {
  const checkRefs = evidence.check
    ? [...evidence.check.log_refs, ...evidence.check.artifact_refs]
    : evidence.checks.flatMap((check) => [...check.log_refs, ...check.artifact_refs]);
  if (
    evidence.judgment_revision !== evidence.release_identity.commit_sha ||
    !evidence.judgment_ledger.name.endsWith('.jsonl') ||
    !checkRefs.some(
      (reference) =>
        reference.name === evidence.judgment_ledger.name &&
        reference.sha256 === evidence.judgment_ledger.sha256 &&
        reference.url === evidence.judgment_ledger.url,
    )
  ) {
    blocked('judgment_ledger_identity_mismatch');
  }
}

function assertBrowserBridgeReleaseAssets(evidence, assetsByName) {
  const references = new Map(
    evidence.check.artifact_refs.map((reference) => [reference.name, reference]),
  );
  if (
    references.size !== evidence.check.artifact_refs.length ||
    REQUIRED_BROWSER_BRIDGE_RELEASE_ASSETS.some((name) => !references.has(name))
  ) {
    blocked('browser_bridge_release_asset_evidence_incomplete');
  }
  for (const name of REQUIRED_BROWSER_BRIDGE_RELEASE_ASSETS) {
    const reference = references.get(name);
    const asset = assetsByName.get(name);
    if (!asset || reference.sha256 !== asset.sha256) {
      blocked('browser_bridge_release_asset_identity_mismatch');
    }
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
  const producerManifestPath = env.AGISTACK_GITHUB_WORKFLOW_PRODUCER_MANIFEST;
  const index = readJson(
    indexPath,
    'release_evidence_index_missing',
    'release_evidence_index_invalid',
    indexSchema,
  );
  const releaseIdentity = index.release_identity;
  if (!env.AGISTACK_GITHUB_RELEASE_ASSET_MANIFEST) {
    blocked('github_asset_manifest_missing');
  }
  if (!producerManifestPath) blocked('producer_manifest_missing');
  const producerManifest = readJson(
    resolve(producerManifestPath),
    'producer_manifest_missing',
    'producer_manifest_invalid',
    producerManifestSchema,
  );
  const producersById = new Map(producerManifest.runs.map((run) => [run.supplemental_id, run]));
  if (
    producersById.size !== REQUIRED_SUPPLEMENTAL_EVIDENCE.length ||
    REQUIRED_SUPPLEMENTAL_EVIDENCE.some((id) => !producersById.has(id))
  ) {
    blocked('producer_manifest_set_invalid');
  }
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
    assertJudgmentLedger(evidence);
    const packageTypes = evidence.artifact_identities.map(
      ({ package_type: packageType }) => packageType,
    );
    if (
      new Set(packageTypes).size !== packageTypes.length ||
      REQUIRED_PLATFORM_PACKAGE_TYPES[binding.platform].some(
        (packageType) => !packageTypes.includes(packageType),
      )
    ) {
      blocked('platform_artifact_set_invalid');
    }
    for (const identity of evidence.artifact_identities) {
      const artifact = assetsByName.get(identity.name);
      if (
        !artifact ||
        artifact.github_asset_id !== identity.github_asset_id ||
        artifact.size !== identity.size ||
        artifact.sha256 !== identity.sha256 ||
        artifact.sha512 !== identity.sha512
      ) {
        blocked('platform_artifact_identity_mismatch');
      }
      assertPassedOutcome(identity.signature);
      assertPassedOutcome(identity.attestation);
    }
    const checks = new Map(evidence.checks.map((check) => [check.id, check]));
    if (
      checks.size !== evidence.checks.length ||
      REQUIRED_PLATFORM_CHECKS[binding.platform].some((id) => !checks.has(id))
    ) {
      blocked('platform_evidence_check_set_invalid');
    }
    for (const id of REQUIRED_PLATFORM_CHECKS[binding.platform]) {
      assertPassedOutcome(checks.get(id));
    }
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
    assertJudgmentLedger(evidence);
    assertSupplementalProducer({
      evidence,
      id: binding.id,
      liveProducer: producersById.get(binding.id),
      repository: producerManifest.repository,
      assetsByName,
    });
    if (binding.id === 'browser_bridge') {
      assertBrowserBridgeReleaseAssets(evidence, assetsByName);
    }
  }

  if (existsSync(nativeQaPath)) {
    const nativeQa = readJson(
      nativeQaPath,
      'native_qa_evidence_missing',
      'native_qa_evidence_invalid',
      nativeQaSchema,
    );
    if (
      nativeQa.version !== releaseIdentity.version ||
      nativeQa.tag !== releaseIdentity.tag ||
      nativeQa.commit_sha !== releaseIdentity.commit_sha ||
      nativeQa.workflow_run.id !== releaseIdentity.workflow_run.id ||
      nativeQa.workflow_run.attempt !== releaseIdentity.workflow_run.attempt ||
      nativeQa.workflow_run.url !== releaseIdentity.workflow_run.url ||
      nativeQa.source_index_sha256 !== sha256(indexPath)
    ) {
      blocked('native_qa_evidence_identity_mismatch');
    }
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
