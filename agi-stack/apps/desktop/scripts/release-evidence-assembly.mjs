import { createHash } from 'node:crypto';
import {
  chmodSync,
  closeSync,
  existsSync,
  lstatSync,
  openSync,
  readFileSync,
  readSync,
  writeFileSync,
} from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { validateJsonSchema } from '../contracts/desktop-web-parity/schema-validator.mjs';
import {
  RELEASE_EVIDENCE_INDEX_NAME,
  REQUIRED_PROMOTION_CHECKS,
} from './release-evidence-index.mjs';

const MAX_EVIDENCE_BYTES = 1024 * 1024;
const NATIVE_QA_EVIDENCE_NAME = 'release-native-qa-evidence-v1.json';
const PLATFORM_EVIDENCE_NAMES = Object.freeze({
  linux: 'release-platform-evidence-linux-v3.json',
  macos: 'release-platform-evidence-macos-v3.json',
  windows: 'release-platform-evidence-windows-v3.json',
});
const SUPPLEMENTAL_EVIDENCE_NAMES = Object.freeze({
  browser_bridge: 'browser-bridge-evidence.json',
  neo4j_runtime: 'neo4j-runtime-evidence.json',
  wcag_aa: 'wcag-aa-evidence.json',
});
const SUPPLEMENTAL_PRODUCER_CONTRACTS = Object.freeze({
  browser_bridge: Object.freeze({
    artifactName: 'desktop-browser-bridge-release-evidence',
    requiredRefs: Object.freeze([
      'browser-bridge-macos-chrome-edge.log',
      'browser-bridge-windows-chrome-edge.log',
      'browser-bridge-linux-chrome-edge.log',
    ]),
    workflowPath: '.github/workflows/desktop-release-supplemental-evidence.yml',
  }),
  neo4j_runtime: Object.freeze({
    artifactName: 'desktop-neo4j-runtime-evidence',
    requiredRefs: Object.freeze(['neo4j-electron-matched-state.log']),
    workflowPath: '.github/workflows/desktop-release-supplemental-evidence.yml',
  }),
  wcag_aa: Object.freeze({
    artifactName: 'desktop-wcag-aa-evidence',
    requiredRefs: Object.freeze([
      'voiceover-at-ledger.jsonl',
      'nvda-at-ledger.jsonl',
      'orca-at-ledger.jsonl',
    ]),
    workflowPath: '.github/workflows/desktop-release-supplemental-evidence.yml',
  }),
});
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
const REQUIRED_BROWSER_BRIDGE_RELEASE_ASSETS = Object.freeze([
  'memstack-browser-bridge.crx',
  'qa.xml',
  'browser-bridge-enterprise-policy-bundle.json',
  'browser-bridge-enterprise-policy-member-manifest.json',
  'stable.xml.candidate',
]);

const schemaRoot = new URL('.', import.meta.url);
const indexSchema = JSON.parse(
  readFileSync(new URL('desktop-release-evidence-index.v3.schema.json', schemaRoot), 'utf8'),
);
const platformEvidenceSchema = JSON.parse(
  readFileSync(new URL('desktop-release-evidence.v3.schema.json', schemaRoot), 'utf8'),
);
const supplementalEvidenceSchema = JSON.parse(
  readFileSync(new URL('desktop-release-supplemental-evidence.v1.schema.json', schemaRoot), 'utf8'),
);
const githubAssetManifestSchema = JSON.parse(
  readFileSync(new URL('github-release-assets.v1.schema.json', schemaRoot), 'utf8'),
);
const producerManifestSchema = JSON.parse(
  readFileSync(new URL('github-workflow-producers.v1.schema.json', schemaRoot), 'utf8'),
);

function assertSafeName(value, label) {
  if (typeof value !== 'string' || basename(value) !== value || value.length > 240) {
    throw new Error(`${label} is invalid`);
  }
  return value;
}

function readRegularFile(path, label, maxBytes = Number.MAX_SAFE_INTEGER) {
  const stats = lstatSync(path);
  if (!stats.isFile() || stats.isSymbolicLink()) {
    throw new Error(`${label} is not a regular file`);
  }
  if (stats.size <= 0 || stats.size > maxBytes) throw new Error(`${label} size is invalid`);
  return stats;
}

function readJson(path, label, schema) {
  readRegularFile(path, label, MAX_EVIDENCE_BYTES);
  let value;
  try {
    value = JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    throw new Error(`${label} is invalid JSON`);
  }
  const errors = validateJsonSchema(schema, value);
  if (errors.length > 0) throw new Error(`${label} contract is invalid:\n${errors.join('\n')}`);
  return value;
}

function digestFile(path, algorithm, encoding) {
  const descriptor = openSync(path, 'r');
  const hash = createHash(algorithm);
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    for (;;) {
      const length = readSync(descriptor, buffer, 0, buffer.length, null);
      if (length === 0) break;
      hash.update(buffer.subarray(0, length));
    }
  } finally {
    closeSync(descriptor);
  }
  return hash.digest(encoding);
}

function sha256File(path) {
  return digestFile(path, 'sha256', 'hex');
}

function sha512File(path) {
  return digestFile(path, 'sha512', 'base64');
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

function expectedProducerUrl(repository, run) {
  return `https://github.com/${repository}/actions/runs/${run.id}/attempts/${run.attempt}`;
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
    throw new Error(`required evidence is not passed: ${check?.id ?? 'unknown'}`);
  }
}

function assertJudgmentLedger(evidence, label) {
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
    throw new Error(`${label} judgment ledger identity mismatch`);
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
    throw new Error('Browser Bridge release asset evidence is incomplete');
  }
  for (const name of REQUIRED_BROWSER_BRIDGE_RELEASE_ASSETS) {
    const reference = references.get(name);
    const asset = assetsByName.get(name);
    if (!asset || reference.sha256 !== asset.sha256) {
      throw new Error(`Browser Bridge release asset identity mismatch: ${name}`);
    }
  }
}

function assertSupplementalProducer({ evidence, id, liveProducer, repository, assetsByName }) {
  const contract = SUPPLEMENTAL_PRODUCER_CONTRACTS[id];
  if (evidence.producer_run.workflow_path !== contract.workflowPath) {
    throw new Error(`supplemental evidence producer workflow is not trusted: ${id}`);
  }
  assertJudgmentLedger(evidence, `supplemental evidence ${id}`);
  if (
    !liveProducer ||
    !sameProducerRun(evidence.producer_run, liveProducer) ||
    liveProducer.head_sha !== evidence.release_identity.commit_sha ||
    liveProducer.conclusion !== 'success' ||
    liveProducer.url !== expectedProducerUrl(repository, liveProducer) ||
    liveProducer.artifact.name !== contract.artifactName
  ) {
    throw new Error(`supplemental evidence producer identity mismatch: ${id}`);
  }
  const producerAsset = assetsByName.get(liveProducer.artifact.release_asset_name);
  if (
    !producerAsset ||
    producerAsset.size !== liveProducer.artifact.size ||
    producerAsset.sha256 !== liveProducer.artifact.sha256
  ) {
    throw new Error(`supplemental evidence producer artifact mismatch: ${id}`);
  }
  const references = new Set(evidence.check.artifact_refs.map(({ name }) => name));
  if (contract.requiredRefs.some((name) => !references.has(name))) {
    throw new Error(`supplemental evidence required refs are incomplete: ${id}`);
  }
}

function canonicalLiveAssets({ releaseRoot, manifest }) {
  const seenNames = new Set();
  const seenIds = new Set();
  const controlNames = new Set([
    ...Object.values(PLATFORM_EVIDENCE_NAMES),
    ...Object.values(SUPPLEMENTAL_EVIDENCE_NAMES),
    RELEASE_EVIDENCE_INDEX_NAME,
    NATIVE_QA_EVIDENCE_NAME,
  ]);
  const assets = [];
  for (const liveAsset of manifest.assets) {
    const name = assertSafeName(liveAsset.name, 'GitHub release asset name');
    if (seenNames.has(name) || seenIds.has(liveAsset.github_asset_id)) {
      throw new Error('GitHub release asset identity is duplicated');
    }
    seenNames.add(name);
    seenIds.add(liveAsset.github_asset_id);
    const path = join(releaseRoot, name);
    const stats = readRegularFile(path, `GitHub release asset ${name}`);
    const sha256 = sha256File(path);
    if (stats.size !== liveAsset.size || liveAsset.digest !== `sha256:${sha256}`) {
      throw new Error(`GitHub release asset digest mismatch: ${name}`);
    }
    if (!controlNames.has(name)) {
      assets.push({
        github_asset_id: liveAsset.github_asset_id,
        name,
        size: stats.size,
        sha256,
        sha512: sha512File(path),
      });
    }
  }
  return assets.sort((left, right) => left.name.localeCompare(right.name));
}

function loadPlatformEvidence(releaseRoot) {
  return Object.entries(PLATFORM_EVIDENCE_NAMES)
    .map(([platform, name]) => {
      const path = join(releaseRoot, name);
      const evidence = readJson(path, 'platform evidence', platformEvidenceSchema);
      if (evidence.platform.os !== platform) {
        throw new Error(`platform evidence identity mismatch: ${platform}`);
      }
      assertJudgmentLedger(evidence, `platform evidence ${platform}`);
      const packageTypes = evidence.artifact_identities.map(
        ({ package_type: packageType }) => packageType,
      );
      if (
        new Set(packageTypes).size !== packageTypes.length ||
        REQUIRED_PLATFORM_PACKAGE_TYPES[platform].some(
          (packageType) => !packageTypes.includes(packageType),
        )
      ) {
        throw new Error(`platform artifact set is invalid: ${platform}`);
      }
      for (const artifact of evidence.artifact_identities) {
        assertPassedOutcome(artifact.signature);
        assertPassedOutcome(artifact.attestation);
      }
      const checks = new Map(evidence.checks.map((check) => [check.id, check]));
      if (
        checks.size !== evidence.checks.length ||
        REQUIRED_PLATFORM_CHECKS[platform].some((id) => !checks.has(id))
      ) {
        throw new Error(`platform evidence check set is invalid: ${platform}`);
      }
      for (const id of REQUIRED_PLATFORM_CHECKS[platform]) assertPassedOutcome(checks.get(id));
      return { evidence, name, path, platform };
    })
    .sort((left, right) => left.platform.localeCompare(right.platform));
}

function loadSupplementalEvidence(releaseRoot) {
  return Object.entries(SUPPLEMENTAL_EVIDENCE_NAMES)
    .map(([id, name]) => {
      const path = join(releaseRoot, name);
      const evidence = readJson(path, 'supplemental evidence', supplementalEvidenceSchema);
      if (evidence.id !== id || evidence.check.id !== id) {
        throw new Error(`supplemental evidence identity mismatch: ${id}`);
      }
      assertPassedOutcome(evidence.check);
      return { evidence, id, name, path };
    })
    .sort((left, right) => left.id.localeCompare(right.id));
}

export function assembleReleaseEvidenceIndexV3({
  releaseRoot = process.cwd(),
  githubAssetManifestPath,
  producerManifestPath,
  expectedTag,
  expectedCommitSha,
} = {}) {
  const root = resolve(releaseRoot);
  if (!githubAssetManifestPath) throw new Error('GitHub release asset manifest is required');
  const manifest = readJson(
    resolve(githubAssetManifestPath),
    'GitHub release asset manifest',
    githubAssetManifestSchema,
  );
  if (!producerManifestPath) throw new Error('trusted producer manifest is required');
  const producerManifest = readJson(
    resolve(producerManifestPath),
    'trusted producer manifest',
    producerManifestSchema,
  );
  const producersById = new Map(producerManifest.runs.map((run) => [run.supplemental_id, run]));
  if (
    producersById.size !== Object.keys(SUPPLEMENTAL_PRODUCER_CONTRACTS).length ||
    Object.keys(SUPPLEMENTAL_PRODUCER_CONTRACTS).some((id) => !producersById.has(id))
  ) {
    throw new Error('trusted producer manifest set is invalid');
  }
  const platformEntries = loadPlatformEvidence(root);
  const supplementalEntries = loadSupplementalEvidence(root);
  const releaseIdentity = platformEntries[0].evidence.release_identity;
  if (
    releaseIdentity.channel !== 'prerelease' ||
    releaseIdentity.tag !== `v${releaseIdentity.version}` ||
    manifest.tag !== releaseIdentity.tag ||
    (expectedTag && releaseIdentity.tag !== expectedTag) ||
    (expectedCommitSha && releaseIdentity.commit_sha !== expectedCommitSha)
  ) {
    throw new Error('release evidence identity mismatch');
  }
  for (const { evidence } of [...platformEntries, ...supplementalEntries]) {
    if (!sameReleaseIdentity(evidence.release_identity, releaseIdentity)) {
      throw new Error('release evidence set contains mixed identities');
    }
  }

  const assets = canonicalLiveAssets({ releaseRoot: root, manifest });
  const assetsByName = new Map(assets.map((asset) => [asset.name, asset]));
  for (const { evidence, platform } of platformEntries) {
    for (const identity of evidence.artifact_identities) {
      const asset = assetsByName.get(identity.name);
      if (
        !asset ||
        asset.github_asset_id !== identity.github_asset_id ||
        asset.size !== identity.size ||
        asset.sha256 !== identity.sha256 ||
        asset.sha512 !== identity.sha512
      ) {
        throw new Error(`platform artifact identity mismatch: ${platform}`);
      }
    }
  }
  const browserBridgeEvidence = supplementalEntries.find(({ id }) => id === 'browser_bridge');
  assertBrowserBridgeReleaseAssets(browserBridgeEvidence.evidence, assetsByName);
  for (const { evidence, id } of supplementalEntries) {
    assertSupplementalProducer({
      evidence,
      id,
      liveProducer: producersById.get(id),
      repository: producerManifest.repository,
      assetsByName,
    });
  }

  const index = Object.freeze({
    contract_version: 'desktop-release-evidence-index-v3',
    release_identity: releaseIdentity,
    promotion_status: 'passed',
    required_promotion_checks: [...REQUIRED_PROMOTION_CHECKS],
    platform_evidence: platformEntries.map(({ evidence, name, path, platform }) => ({
      platform,
      name,
      sha256: sha256File(path),
      judgment_revision: evidence.judgment_revision,
    })),
    supplemental_evidence: supplementalEntries.map(({ evidence, id, name, path }) => ({
      id,
      name,
      sha256: sha256File(path),
      judgment_revision: evidence.judgment_revision,
    })),
    assets,
  });
  const errors = validateJsonSchema(indexSchema, index);
  if (errors.length > 0) {
    throw new Error(`release evidence index is invalid:\n${errors.join('\n')}`);
  }
  return index;
}

export function writeReleaseEvidenceIndexV3({ releaseRoot = process.cwd(), index }) {
  const path = resolve(releaseRoot, RELEASE_EVIDENCE_INDEX_NAME);
  const source = `${JSON.stringify(index, null, 2)}\n`;
  if (existsSync(path)) {
    readRegularFile(path, 'release evidence index', MAX_EVIDENCE_BYTES);
    if (readFileSync(path, 'utf8') !== source) {
      throw new Error('release evidence index already exists with different bytes');
    }
    chmodSync(path, 0o444);
    return path;
  }
  writeFileSync(path, source, { encoding: 'utf8', flag: 'wx', mode: 0o444 });
  chmodSync(path, 0o444);
  return path;
}

function main() {
  if (process.argv[2] !== 'assemble') {
    throw new Error(`unknown release evidence assembly command: ${process.argv[2]}`);
  }
  const releaseRoot = resolve(process.argv[3]);
  const githubAssetManifestPath = resolve(process.argv[4]);
  if (!process.argv[5]) throw new Error('trusted producer manifest path is required');
  const index = assembleReleaseEvidenceIndexV3({
    releaseRoot,
    githubAssetManifestPath,
    producerManifestPath: resolve(process.argv[5]),
    expectedTag: process.env.AGISTACK_EXPECTED_TAG,
    expectedCommitSha: process.env.AGISTACK_EXPECTED_COMMIT_SHA,
  });
  const path = writeReleaseEvidenceIndexV3({ releaseRoot, index });
  process.stdout.write(
    `${JSON.stringify({ index: basename(path), promotion_status: 'passed' })}\n`,
  );
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
