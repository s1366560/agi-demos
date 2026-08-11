import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { parse } from 'yaml';

import { validatePromotionBundle } from '../scripts/release-promotion-validation.mjs';
import { validateJsonSchema } from '../contracts/desktop-web-parity/schema-validator.mjs';

const repositoryRoot = new URL('../../../../', import.meta.url);
const evidenceSchema = JSON.parse(
  readFileSync(new URL('../scripts/desktop-release-evidence.v3.schema.json', import.meta.url)),
);
const indexSchema = JSON.parse(
  readFileSync(
    new URL('../scripts/desktop-release-evidence-index.v3.schema.json', import.meta.url),
  ),
);
const nativeQaSchema = JSON.parse(
  readFileSync(new URL('../scripts/desktop-native-qa-evidence.v1.schema.json', import.meta.url)),
);
const platformEvidenceSchema = JSON.parse(
  readFileSync(new URL('../scripts/desktop-release-evidence.v3.schema.json', import.meta.url)),
);
const supplementalEvidenceSchema = JSON.parse(
  readFileSync(
    new URL('../scripts/desktop-release-supplemental-evidence.v1.schema.json', import.meta.url),
  ),
);

const identity = Object.freeze({
  version: '0.2.0',
  tag: 'v0.2.0',
  commitSha: 'a'.repeat(40),
  workflowRun: Object.freeze({
    id: '12345',
    attempt: '2',
    url: 'https://github.com/example/repository/actions/runs/12345',
  }),
});

function sha256(source) {
  return createHash('sha256').update(source).digest('hex');
}

function sha512(source) {
  return createHash('sha512').update(source).digest('base64');
}

function outcome(id, status = 'passed') {
  const evidenceRef = {
    name: `${id}.log`,
    sha256: 'e'.repeat(64),
    url: `${identity.workflowRun.url}#artifacts`,
  };
  return {
    id,
    status,
    reason_code: status === 'passed' ? null : `${id}_${status}`,
    timestamp: '2026-08-11T01:02:03.000Z',
    retryable: status !== 'passed',
    log_refs: [evidenceRef],
    artifact_refs: [evidenceRef],
  };
}

function releaseIdentity() {
  return {
    version: identity.version,
    tag: identity.tag,
    commit_sha: identity.commitSha,
    channel: 'prerelease',
    workflow_run: identity.workflowRun,
  };
}

function nativeQaEvidence(sourceIndexSha256) {
  return {
    contract_version: 'desktop-native-qa-evidence-v1',
    version: identity.version,
    tag: identity.tag,
    commit_sha: identity.commitSha,
    source_index_sha256: sourceIndexSha256,
    workflow_run: identity.workflowRun,
    checks: [
      'macos_install_launch',
      'windows_install_launch',
      'linux_install_launch',
      'updater_apply',
      'updater_failure_rollback',
      'neo4j_runtime',
      'wcag_aa',
      'browser_bridge',
    ].map((id) => ({
      id,
      status: 'passed',
      evidence_sha256: 'e'.repeat(64),
      evidence_url: `${identity.workflowRun.url}#artifacts`,
    })),
    promotion_status: 'passed',
  };
}

function writeLiveGithubAssetManifest({ index, manifestPath, root }) {
  const indexedAssets = new Map(index.assets.map((asset) => [asset.name, asset]));
  const assets = readdirSync(root)
    .filter((name) => statSync(join(root, name)).isFile())
    .sort()
    .map((name, position) => {
      const bytes = readFileSync(join(root, name));
      return {
        github_asset_id: indexedAssets.get(name)?.github_asset_id ?? String(9000 + position),
        name,
        size: bytes.byteLength,
        digest: `sha256:${sha256(bytes)}`,
      };
    });
  writeFileSync(
    manifestPath,
    `${JSON.stringify({
      contract_version: 'github-release-assets-v1',
      tag: identity.tag,
      assets,
    })}\n`,
  );
}

function withPromotionBundle(run) {
  const root = mkdtempSync(join(tmpdir(), 'agistack-promotion-gate-'));
  try {
    mkdirSync(root, { recursive: true });
    const packageFixtures = [
      ['macos', 'agi-stack-desktop-0.2.0-mac-universal.dmg', 'arm64', 'dmg'],
      ['windows', 'agi-stack-desktop-0.2.0-win-x64.exe', 'x64', 'nsis'],
      ['linux', 'agi-stack-desktop-0.2.0-linux-x64.AppImage', 'x64', 'appimage'],
    ].map(([platform, name, architecture, packageType], index) => {
      const bytes = Buffer.from(`immutable ${platform} package bytes`);
      writeFileSync(join(root, name), bytes);
      return {
        platform,
        name,
        architecture,
        packageType,
        bytes,
        githubAssetId: String(1000 + index),
      };
    });
    const assets = packageFixtures.map(({ bytes, githubAssetId, name }) => ({
      github_asset_id: githubAssetId,
      name,
      size: bytes.byteLength,
      sha256: sha256(bytes),
      sha512: sha512(bytes),
    }));
    const platformEvidence = packageFixtures.map(
      ({ architecture, githubAssetId, name: assetName, packageType, platform }, index) => {
        const asset = assets.find(({ name }) => name === assetName);
        const evidence = {
          contract_version: 'desktop-release-evidence-v3',
          release_identity: releaseIdentity(),
          artifact_identity: {
            ...asset,
            signature: outcome('artifact_signature'),
            attestation: outcome('artifact_attestation'),
          },
          platform: {
            os: platform,
            os_version: 'fixture-os-version',
            os_build: 'fixture-os-build',
            architecture,
            environment: 'physical',
            package_type: packageType,
            anonymous_host_id: `sha256:${String(index + 1).repeat(64)}`,
          },
          checks: [
            outcome('install'),
            outcome('launch'),
            outcome('updater_apply'),
            outcome('updater_failure_rollback'),
          ],
          judgment_revision: String(index + 4).repeat(40),
        };
        const evidenceName = `release-platform-evidence-${platform}-v3.json`;
        const bytes = Buffer.from(`${JSON.stringify(evidence)}\n`);
        writeFileSync(join(root, evidenceName), bytes);
        return {
          platform,
          name: evidenceName,
          sha256: sha256(bytes),
          judgment_revision: evidence.judgment_revision,
        };
      },
    );
    const supplementalEvidence = ['neo4j_runtime', 'wcag_aa', 'browser_bridge'].map((id, index) => {
      const evidence = {
        contract_version: 'desktop-release-supplemental-evidence-v1',
        release_identity: releaseIdentity(),
        id,
        judgment_revision: String(index + 7).repeat(40),
        check: outcome(id),
      };
      const name = `${id.replaceAll('_', '-')}-evidence.json`;
      const bytes = Buffer.from(`${JSON.stringify(evidence)}\n`);
      writeFileSync(join(root, name), bytes);
      return {
        id,
        name,
        sha256: sha256(bytes),
        judgment_revision: evidence.judgment_revision,
      };
    });
    const index = {
      contract_version: 'desktop-release-evidence-index-v3',
      release_identity: releaseIdentity(),
      promotion_status: 'passed',
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
      platform_evidence: platformEvidence,
      supplemental_evidence: supplementalEvidence,
      assets,
    };
    writeFileSync(join(root, 'release-evidence-index-v3.json'), `${JSON.stringify(index)}\n`);
    const indexBytes = readFileSync(join(root, 'release-evidence-index-v3.json'));
    const nativeQa = nativeQaEvidence(sha256(indexBytes));
    writeFileSync(
      join(root, 'release-native-qa-evidence-v1.json'),
      `${JSON.stringify(nativeQa)}\n`,
    );
    const manifestDirectory = join(root, '.promotion-control');
    mkdirSync(manifestDirectory);
    const manifestPath = join(manifestDirectory, 'github-release-assets.json');
    const refreshLiveManifest = () => writeLiveGithubAssetManifest({ index, manifestPath, root });
    refreshLiveManifest();
    const validate = () =>
      validatePromotionBundle({
        releaseRoot: root,
        env: { AGISTACK_GITHUB_RELEASE_ASSET_MANIFEST: manifestPath },
      });
    return run({
      index,
      nativeQa,
      platformEvidence,
      refreshLiveManifest,
      root,
      supplementalEvidence,
      validate,
    });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test('external v3, release index, and native QA schemas are explicit and closed', () => {
  assert.equal(evidenceSchema.properties.contract_version.const, 'desktop-release-evidence-v3');
  assert.equal(indexSchema.properties.contract_version.const, 'desktop-release-evidence-index-v3');
  assert.equal(nativeQaSchema.properties.contract_version.const, 'desktop-native-qa-evidence-v1');
  assert.equal(
    supplementalEvidenceSchema.properties.contract_version.const,
    'desktop-release-supplemental-evidence-v1',
  );
  assert.equal(evidenceSchema.additionalProperties, false);
  assert.equal(indexSchema.additionalProperties, false);
  assert.equal(nativeQaSchema.additionalProperties, false);
  assert.equal(supplementalEvidenceSchema.additionalProperties, false);
});

test('promotion requires independently bound v3 platform and supplemental evidence', () => {
  withPromotionBundle(({ index, nativeQa, validate }) => {
    assert.deepEqual(validateJsonSchema(indexSchema, index), []);
    assert.deepEqual(validateJsonSchema(nativeQaSchema, nativeQa), []);
    assert.equal(index.release_identity.channel, 'prerelease');
    assert.equal(index.promotion_status, 'passed');
    assert.equal(validate().promotion_status, 'passed');
  });
});

test('promotion requires a live GitHub API asset manifest', () => {
  withPromotionBundle(({ root }) => {
    assert.throws(
      () => validatePromotionBundle({ releaseRoot: root, env: {} }),
      /promotion_status=blocked reason=github_asset_manifest_missing/u,
    );
  });
});

test('native QA v1 remains readable but cannot substitute for missing v3 evidence', () => {
  withPromotionBundle(({ platformEvidence, refreshLiveManifest, root, validate }) => {
    rmSync(join(root, 'release-native-qa-evidence-v1.json'));
    refreshLiveManifest();
    assert.equal(validate().promotion_status, 'passed');

    writeFileSync(join(root, 'release-native-qa-evidence-v1.json'), '{}');
    rmSync(join(root, platformEvidence[0].name));
    assert.throws(validate, /promotion_status=blocked reason=platform_evidence_missing/u);
  });
});

test('promotion fails closed when a required supplemental judgment is not passed', () => {
  withPromotionBundle(({ root, supplementalEvidence, validate }) => {
    const binding = supplementalEvidence.find(({ id }) => id === 'neo4j_runtime');
    const path = join(root, binding.name);
    const evidence = JSON.parse(readFileSync(path, 'utf8'));
    evidence.check = outcome('neo4j_runtime', 'blocked');
    const bytes = Buffer.from(`${JSON.stringify(evidence)}\n`);
    writeFileSync(path, bytes);
    const indexPath = join(root, 'release-evidence-index-v3.json');
    const index = JSON.parse(readFileSync(indexPath, 'utf8'));
    index.supplemental_evidence = index.supplemental_evidence.map((entry) =>
      entry.id === 'neo4j_runtime' ? { ...entry, sha256: sha256(bytes) } : entry,
    );
    writeFileSync(indexPath, `${JSON.stringify(index)}\n`);
    assert.throws(validate, /promotion_status=blocked reason=required_evidence_not_passed/u);
  });
});

test('promotion fails closed when any required platform outcome is not passed', () => {
  withPromotionBundle(({ platformEvidence, root, validate }) => {
    const binding = platformEvidence.find(({ platform }) => platform === 'windows');
    const path = join(root, binding.name);
    const evidence = JSON.parse(readFileSync(path, 'utf8'));
    evidence.checks = evidence.checks.map((check) =>
      check.id === 'updater_apply' ? outcome('updater_apply', 'failed') : check,
    );
    const bytes = Buffer.from(`${JSON.stringify(evidence)}\n`);
    writeFileSync(path, bytes);
    const indexPath = join(root, 'release-evidence-index-v3.json');
    const index = JSON.parse(readFileSync(indexPath, 'utf8'));
    index.platform_evidence = index.platform_evidence.map((entry) =>
      entry.platform === 'windows' ? { ...entry, sha256: sha256(bytes) } : entry,
    );
    writeFileSync(indexPath, `${JSON.stringify(index)}\n`);
    assert.throws(validate, /promotion_status=blocked reason=required_evidence_not_passed/u);
  });
});

test('promotion fails closed when a v3 evidence digest is not bound to the index', () => {
  withPromotionBundle(({ platformEvidence, root, validate }) => {
    const path = join(root, platformEvidence[0].name);
    const evidence = JSON.parse(readFileSync(path, 'utf8'));
    evidence.checks[0].timestamp = '2026-08-11T01:02:04.000Z';
    writeFileSync(path, `${JSON.stringify(evidence)}\n`);
    assert.throws(validate, /promotion_status=blocked reason=platform_evidence_digest_mismatch/u);
  });
});

test('promotion fails closed when GitHub API asset identity differs from v3', () => {
  withPromotionBundle(({ index, refreshLiveManifest, root, validate }) => {
    const manifestPath = join(root, '.promotion-control', 'github-release-assets.json');
    refreshLiveManifest();
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
    manifest.assets = manifest.assets.map((asset) =>
      asset.name === index.assets[0].name ? { ...asset, github_asset_id: '999999999' } : asset,
    );
    writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`);
    assert.throws(validate, /promotion_status=blocked reason=github_asset_identity_mismatch/u);
  });
});

test('release workflow derives tag identity dynamically and stages a prerelease only', () => {
  const releaseWorkflow = readFileSync(
    new URL('.github/workflows/desktop-release.yml', repositoryRoot),
    'utf8',
  );
  const promotionWorkflow = readFileSync(
    new URL('.github/workflows/desktop-release-promotion.yml', repositoryRoot),
    'utf8',
  );
  const parsedRelease = parse(releaseWorkflow);
  const parsedPromotion = parse(promotionWorkflow);

  assert.doesNotMatch(releaseWorkflow, /AGISTACK_RELEASE_VERSION:\s*['"]0\.1\.0['"]/u);
  assert.match(releaseWorkflow, /needs\.authorize\.outputs\.version/u);
  assert.match(releaseWorkflow, /--prerelease/u);
  assert.match(releaseWorkflow, /release-draft-validation\.mjs validate-combined/u);
  assert.equal(parsedPromotion.jobs.promote.environment, 'desktop-release-production');
  assert.match(promotionWorkflow, /validate-promotion/u);
  assert.match(promotionWorkflow, /--prerelease=false/u);
  assert.doesNotMatch(promotionWorkflow, /gh release upload/u);
  assert.match(promotionWorkflow, /v3_promotion_evidence_incomplete/u);
  assert.match(promotionWorkflow, /github-release-assets-v1/u);
  assert.match(promotionWorkflow, /github_asset_id/u);
  assert.match(promotionWorkflow, /cmp -s/u);
  assert.match(promotionWorkflow, /AGISTACK_GITHUB_RELEASE_ASSET_MANIFEST/u);
  const identityIndex = promotionWorkflow.indexOf('Authorize protected promotion identity');
  const checkoutIndex = promotionWorkflow.indexOf('Checkout immutable promotion validator');
  const validationIndex = promotionWorkflow.indexOf('Validate external v3 promotion evidence');
  assert.ok(identityIndex >= 0 && identityIndex < checkoutIndex);
  assert.ok(checkoutIndex < validationIndex);
  assert.match(promotionWorkflow, /ref:\s*\$\{\{\s*steps\.identity\.outputs\.commit_sha\s*\}\}/u);
  assert.ok(parsedRelease.jobs.authorize.outputs.version);
});
