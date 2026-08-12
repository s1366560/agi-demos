import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { validateJsonSchema } from '../contracts/desktop-web-parity/schema-validator.mjs';

const platformSchemaV3 = JSON.parse(
  readFileSync(new URL('../scripts/desktop-release-evidence.v3.schema.json', import.meta.url)),
);
const platformSchemaV2 = JSON.parse(
  readFileSync(new URL('../scripts/desktop-release-evidence.v2.schema.json', import.meta.url)),
);
const indexSchemaV3 = JSON.parse(
  readFileSync(
    new URL('../scripts/desktop-release-evidence-index.v3.schema.json', import.meta.url),
  ),
);

const workflowRun = Object.freeze({
  id: '12345',
  attempt: '2',
  url: 'https://github.com/example/repository/actions/runs/12345',
});
const releaseIdentity = Object.freeze({
  version: '0.2.0',
  tag: 'v0.2.0',
  commit_sha: 'a'.repeat(40),
  channel: 'prerelease',
  workflow_run: workflowRun,
});
const artifactRef = Object.freeze({
  name: 'native-launch.log',
  sha256: 'b'.repeat(64),
  url: `${workflowRun.url}#artifacts`,
});
const judgmentLedger = Object.freeze({
  name: 'macos-judgment-ledger.jsonl',
  sha256: 'e'.repeat(64),
  url: `${workflowRun.url}#artifacts`,
});

function outcome(id, status = 'passed') {
  return {
    id,
    status,
    reason_code: status === 'passed' ? null : `${id}_${status}`,
    timestamp: '2026-08-11T01:02:03.000Z',
    retryable: status !== 'passed',
    log_refs: [artifactRef],
    artifact_refs: [artifactRef],
  };
}

function platformEvidenceV3() {
  return {
    contract_version: 'desktop-release-evidence-v3',
    release_identity: releaseIdentity,
    artifact_identities: ['dmg', 'zip'].map((packageType, index) => ({
      github_asset_id: String(987654321 + index),
      name: `agi-stack-desktop-0.2.0-mac-universal.${packageType}`,
      size: 4096 + index,
      sha256: String(index + 3).repeat(64),
      sha512: Buffer.alloc(64, index + 7).toString('base64'),
      package_type: packageType,
      signature: outcome(`${packageType}_signature`),
      attestation: outcome(`${packageType}_attestation`),
    })),
    platform: {
      os: 'macos',
      os_version: '15.6',
      os_build: '24G84',
      architecture: 'arm64',
      environment: 'physical',
      anonymous_host_id: `sha256:${'d'.repeat(64)}`,
    },
    checks: [
      outcome('dmg_install'),
      outcome('dmg_launch'),
      outcome('zip_updater_apply'),
      outcome('zip_failure_rollback'),
      outcome('data_compatibility'),
      outcome('uninstall'),
      outcome('notarization'),
      outcome('gatekeeper'),
      outcome('nested_signatures'),
      {
        ...outcome('browser_bridge_registration'),
        artifact_refs: [artifactRef, judgmentLedger],
      },
    ],
    judgment_revision: releaseIdentity.commit_sha,
    judgment_ledger: judgmentLedger,
  };
}

function indexV3() {
  return {
    contract_version: 'desktop-release-evidence-index-v3',
    release_identity: releaseIdentity,
    promotion_status: 'blocked',
    required_promotion_checks: [
      'macos_install_launch',
      'windows_install_launch',
      'linux_install_launch',
      'updater_apply',
      'updater_failure_rollback',
      'neo4j_runtime',
      'wcag_aa',
      'browser_bridge',
    ],
    platform_evidence: ['macos', 'windows', 'linux'].map((platform, index) => ({
      platform,
      name: `release-platform-evidence-${platform}-v3.json`,
      sha256: String(index + 1).repeat(64),
      judgment_revision: String(index + 4).repeat(40),
    })),
    supplemental_evidence: ['neo4j_runtime', 'wcag_aa', 'browser_bridge'].map((id, index) => ({
      id,
      name: `${id.replaceAll('_', '-')}-evidence.json`,
      sha256: String(index + 7).repeat(64),
      judgment_revision: String(index + 7).repeat(40),
    })),
    assets: ['mac-universal.dmg', 'win-x64.exe', 'linux-x64.AppImage'].map((suffix, index) => ({
      github_asset_id: String(987654321 + index),
      name: `agi-stack-desktop-0.2.0-${suffix}`,
      size: 4096 + index,
      sha256: String(index + 3).repeat(64),
      sha512: Buffer.alloc(64, index + 7).toString('base64'),
    })),
  };
}

test('v3 platform evidence binds release, GitHub artifact, physical host, and complete checks', () => {
  assert.ok(platformSchemaV3.required.includes('judgment_ledger'));
  const evidence = platformEvidenceV3();
  assert.deepEqual(validateJsonSchema(platformSchemaV3, evidence), []);

  for (const field of ['release_identity', 'artifact_identities', 'platform', 'checks']) {
    const missing = structuredClone(evidence);
    delete missing[field];
    assert.notDeepEqual(validateJsonSchema(platformSchemaV3, missing), [], field);
  }
  assert.equal(evidence.platform.environment, 'physical');
  assert.match(evidence.platform.anonymous_host_id, /^sha256:[a-f0-9]{64}$/u);
  assert.deepEqual(new Set(evidence.checks.map(({ status }) => status)), new Set(['passed']));
});

test('v3 check outcomes use one closed status and traceable log and artifact references', () => {
  const evidence = platformEvidenceV3();
  const allowedStatuses = ['passed', 'failed', 'blocked', 'not_run'];
  for (const status of allowedStatuses) {
    const candidate = structuredClone(evidence);
    candidate.checks[0] = outcome('install', status);
    assert.deepEqual(validateJsonSchema(platformSchemaV3, candidate), [], status);
  }

  const unknown = structuredClone(evidence);
  unknown.checks[0].status = 'skipped';
  assert.notDeepEqual(validateJsonSchema(platformSchemaV3, unknown), []);

  for (const field of ['reason_code', 'timestamp', 'retryable', 'log_refs', 'artifact_refs']) {
    const missing = structuredClone(evidence);
    delete missing.checks[0][field];
    assert.notDeepEqual(validateJsonSchema(platformSchemaV3, missing), [], field);
  }
});

test('v3 index binds each platform plus Neo4j, WCAG, and Browser Bridge judgments', () => {
  const index = indexV3();
  assert.deepEqual(validateJsonSchema(indexSchemaV3, index), []);
  assert.deepEqual(index.supplemental_evidence.map(({ id }) => id).sort(), [
    'browser_bridge',
    'neo4j_runtime',
    'wcag_aa',
  ]);
  for (const evidence of [...index.platform_evidence, ...index.supplemental_evidence]) {
    assert.match(evidence.name, /^[A-Za-z0-9_.-]+$/u);
    assert.match(evidence.sha256, /^[a-f0-9]{64}$/u);
    assert.match(evidence.judgment_revision, /^[a-f0-9]{40}$/u);
  }

  const missingSupplement = structuredClone(index);
  missingSupplement.supplemental_evidence.pop();
  assert.notDeepEqual(validateJsonSchema(indexSchemaV3, missingSupplement), []);
});

test('v2 package evidence remains readable but cannot satisfy the v3 platform schema', () => {
  const legacy = {
    contract_version: 'desktop-release-evidence-v2',
    evidence_scope: 'package_artifacts_only',
    blockmap_verification_scope: 'blockmap_structure_and_coverage_only',
    artifact_verification_status: 'verified_by_tag_ci',
    release_disposition: 'draft_only',
    release_blocker_reason_code: 'native_release_evidence_required',
    required_native_checks: ['install', 'launch', 'updater_apply', 'updater_failure_rollback'],
    platform: 'macos',
    version: releaseIdentity.version,
    tag: releaseIdentity.tag,
    commit_sha: releaseIdentity.commit_sha,
    workflow_run: workflowRun,
    package_verification: { fixture: true },
    assets: [
      {
        name: 'agi-stack-desktop-0.2.0-mac-universal.dmg',
        size: 4096,
        sha512: Buffer.alloc(64, 7).toString('base64'),
      },
    ],
  };
  assert.deepEqual(validateJsonSchema(platformSchemaV2, legacy), []);
  assert.notDeepEqual(validateJsonSchema(platformSchemaV3, legacy), []);
});
