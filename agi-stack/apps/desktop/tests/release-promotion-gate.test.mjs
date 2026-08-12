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

const browserBridgeReleaseAssets = Object.freeze([
  ['memstack-browser-bridge.crx', 'immutable browser bridge CRX3 bytes'],
  ['qa.xml', 'immutable browser bridge QA update manifest'],
  [
    'browser-bridge-enterprise-policy-bundle.json',
    'immutable browser bridge enterprise policy bundle',
  ],
  [
    'browser-bridge-enterprise-policy-member-manifest.json',
    'immutable browser bridge enterprise policy member manifest',
  ],
  ['stable.xml.candidate', 'immutable Browser Bridge stable update manifest candidate'],
]);

const requiredPlatformChecks = Object.freeze({
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

const supplementalProducerContracts = Object.freeze({
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

function sha256(source) {
  return createHash('sha256').update(source).digest('hex');
}

function sha512(source) {
  return createHash('sha512').update(source).digest('base64');
}

function outcome(id, status = 'passed', artifactRefs = null) {
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
    artifact_refs: artifactRefs ?? [evidenceRef],
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
      ['macos', 'agi-stack-desktop-0.2.0-mac-universal.zip', 'arm64', 'zip'],
      ['windows', 'agi-stack-desktop-0.2.0-win-x64.exe', 'x64', 'nsis'],
      ['linux', 'agi-stack-desktop-0.2.0-linux-x64.AppImage', 'x64', 'appimage'],
      ['linux', 'agi-stack-desktop-0.2.0-linux-x64.deb', 'x64', 'deb'],
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
    for (const [name, source] of browserBridgeReleaseAssets) {
      const bytes = Buffer.from(source);
      writeFileSync(join(root, name), bytes);
      assets.push({
        github_asset_id: String(2000 + assets.length),
        name,
        size: bytes.byteLength,
        sha256: sha256(bytes),
        sha512: sha512(bytes),
      });
    }
    const platformEvidence = Object.keys(requiredPlatformChecks).map((platform, index) => {
      const packages = packageFixtures.filter((entry) => entry.platform === platform);
      const evidence = {
        contract_version: 'desktop-release-evidence-v3',
        release_identity: releaseIdentity(),
        artifact_identities: packages.map(({ name, packageType }) => ({
          ...assets.find((asset) => asset.name === name),
          package_type: packageType,
          signature: outcome(`${packageType}_signature`),
          attestation: outcome(`${packageType}_attestation`),
        })),
        platform: {
          os: platform,
          os_version: 'fixture-os-version',
          os_build: 'fixture-os-build',
          architecture: packages[0].architecture,
          environment: 'physical',
          anonymous_host_id: `sha256:${String(index + 1).repeat(64)}`,
        },
        checks: requiredPlatformChecks[platform].map((id, checkIndex, checks) =>
          checkIndex === checks.length - 1
            ? outcome(id, 'passed', [
                {
                  name: `${platform}-judgment-ledger.jsonl`,
                  sha256: String(index + 4).repeat(64),
                  url: `${identity.workflowRun.url}#artifacts`,
                },
              ])
            : outcome(id),
        ),
        judgment_revision: identity.commitSha,
        judgment_ledger: {
          name: `${platform}-judgment-ledger.jsonl`,
          sha256: String(index + 4).repeat(64),
          url: `${identity.workflowRun.url}#artifacts`,
        },
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
    });
    const browserBridgeArtifactRefs = browserBridgeReleaseAssets.map(([name]) => ({
      name,
      sha256: assets.find((asset) => asset.name === name).sha256,
      url: `${identity.workflowRun.url}#artifacts`,
    }));
    const producerRuns = [];
    const supplementalEvidence = ['neo4j_runtime', 'wcag_aa', 'browser_bridge'].map((id, index) => {
      const contract = supplementalProducerContracts[id];
      const runId = String(50000 + index);
      const attempt = String(index + 1);
      const artifactBytes = Buffer.from(`trusted ${id} producer artifact bytes`);
      const producerAssetName = `${id}-producer-artifact.zip`;
      writeFileSync(join(root, producerAssetName), artifactBytes);
      assets.push({
        github_asset_id: String(3000 + index),
        name: producerAssetName,
        size: artifactBytes.byteLength,
        sha256: sha256(artifactBytes),
        sha512: sha512(artifactBytes),
      });
      const producerRun = {
        workflow_path: '.github/workflows/desktop-release-supplemental-evidence.yml',
        id: runId,
        attempt,
        url: `https://github.com/example/repository/actions/runs/${runId}/attempts/${attempt}`,
        head_sha: identity.commitSha,
        conclusion: 'success',
        artifact: {
          github_artifact_id: String(9000 + index),
          name: contract.artifactName,
          size: artifactBytes.byteLength,
          sha256: sha256(artifactBytes),
          release_asset_name: producerAssetName,
        },
      };
      producerRuns.push({ supplemental_id: id, ...producerRun });
      const requiredRefs = contract.requiredRefs.map((name) => ({
        name,
        sha256: 'd'.repeat(64),
        url: `${producerRun.url}#artifacts`,
      }));
      const evidence = {
        contract_version: 'desktop-release-supplemental-evidence-v1',
        release_identity: releaseIdentity(),
        id,
        producer_run: producerRun,
        judgment_revision: identity.commitSha,
        judgment_ledger: {
          name: `${id.replaceAll('_', '-')}-judgment-ledger.jsonl`,
          sha256: String(index + 7).repeat(64),
          url: `${producerRun.url}#artifacts`,
        },
        check: outcome(id, 'passed', [
          ...(id === 'browser_bridge' ? browserBridgeArtifactRefs : []),
          ...requiredRefs,
          {
            name: `${id.replaceAll('_', '-')}-judgment-ledger.jsonl`,
            sha256: String(index + 7).repeat(64),
            url: `${producerRun.url}#artifacts`,
          },
        ]),
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
    const producerManifestPath = join(manifestDirectory, 'github-workflow-producers.json');
    writeFileSync(
      producerManifestPath,
      `${JSON.stringify({
        contract_version: 'github-workflow-producers-v1',
        repository: 'example/repository',
        runs: producerRuns,
      })}\n`,
    );
    const refreshLiveManifest = () => writeLiveGithubAssetManifest({ index, manifestPath, root });
    refreshLiveManifest();
    const validate = () =>
      validatePromotionBundle({
        releaseRoot: root,
        env: {
          AGISTACK_GITHUB_RELEASE_ASSET_MANIFEST: manifestPath,
          AGISTACK_GITHUB_WORKFLOW_PRODUCER_MANIFEST: producerManifestPath,
        },
      });
    return run({
      index,
      nativeQa,
      platformEvidence,
      producerManifestPath,
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
  assert.equal(platformEvidenceSchema.properties.artifact_identities.type, 'array');
  assert.equal(platformEvidenceSchema.properties.artifact_identities.minItems, 1);
  assert.equal(platformEvidenceSchema.properties.artifact_identity, undefined);
  assert.ok(platformEvidenceSchema.required.includes('judgment_ledger'));
  assert.ok(supplementalEvidenceSchema.required.includes('judgment_ledger'));
  assert.equal(platformEvidenceSchema.$defs.platform.properties.package_type, undefined);
  assert.deepEqual(platformEvidenceSchema.$defs.artifactIdentity.properties.package_type.enum, [
    'dmg',
    'zip',
    'nsis',
    'appimage',
    'deb',
  ]);
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

test('promotion requires a live trusted producer manifest', () => {
  withPromotionBundle(({ root }) => {
    assert.throws(
      () =>
        validatePromotionBundle({
          releaseRoot: root,
          env: {
            AGISTACK_GITHUB_RELEASE_ASSET_MANIFEST: join(
              root,
              '.promotion-control',
              'github-release-assets.json',
            ),
          },
        }),
      /promotion_status=blocked reason=producer_manifest_missing/u,
    );
  });
});

test('promotion rejects producer workflow, head, attempt, conclusion, and digest drift', () => {
  for (const mutate of [
    (run) => {
      run.workflow_path = '.github/workflows/untrusted.yml';
    },
    (run) => {
      run.head_sha = 'b'.repeat(40);
    },
    (run) => {
      run.attempt = '99';
    },
    (run) => {
      run.conclusion = 'failure';
    },
    (run) => {
      run.artifact.sha256 = 'f'.repeat(64);
    },
  ]) {
    withPromotionBundle(({ producerManifestPath, validate }) => {
      const manifest = JSON.parse(readFileSync(producerManifestPath, 'utf8'));
      mutate(manifest.runs.find(({ supplemental_id }) => supplemental_id === 'wcag_aa'));
      writeFileSync(producerManifestPath, `${JSON.stringify(manifest)}\n`);
      assert.throws(
        validate,
        /promotion_status=blocked reason=supplemental_producer_(?:workflow_untrusted|identity_mismatch|artifact_mismatch)/u,
      );
    });
  }
});

test('native QA v1 is optional, but must be valid and index-bound when present', () => {
  withPromotionBundle(({ platformEvidence, refreshLiveManifest, root, validate }) => {
    rmSync(join(root, 'release-native-qa-evidence-v1.json'));
    refreshLiveManifest();
    assert.equal(validate().promotion_status, 'passed');

    writeFileSync(join(root, 'release-native-qa-evidence-v1.json'), '{}');
    refreshLiveManifest();
    assert.throws(validate, /promotion_status=blocked reason=native_qa_evidence_invalid/u);

    const indexBytes = readFileSync(join(root, 'release-evidence-index-v3.json'));
    const nativeQa = nativeQaEvidence(sha256(indexBytes));
    nativeQa.source_index_sha256 = 'f'.repeat(64);
    writeFileSync(
      join(root, 'release-native-qa-evidence-v1.json'),
      `${JSON.stringify(nativeQa)}\n`,
    );
    refreshLiveManifest();
    assert.throws(
      validate,
      /promotion_status=blocked reason=native_qa_evidence_identity_mismatch/u,
    );

    nativeQa.source_index_sha256 = sha256(indexBytes);
    writeFileSync(
      join(root, 'release-native-qa-evidence-v1.json'),
      `${JSON.stringify(nativeQa)}\n`,
    );
    rmSync(join(root, platformEvidence[0].name));
    refreshLiveManifest();
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

test('promotion rejects a judgment ledger not bound by the evidence checks', () => {
  withPromotionBundle(({ platformEvidence, root, validate }) => {
    const binding = platformEvidence.find(({ platform }) => platform === 'linux');
    const path = join(root, binding.name);
    const evidence = JSON.parse(readFileSync(path, 'utf8'));
    evidence.judgment_ledger.sha256 = 'f'.repeat(64);
    const bytes = Buffer.from(`${JSON.stringify(evidence)}\n`);
    writeFileSync(path, bytes);
    const indexPath = join(root, 'release-evidence-index-v3.json');
    const index = JSON.parse(readFileSync(indexPath, 'utf8'));
    index.platform_evidence = index.platform_evidence.map((entry) =>
      entry.platform === 'linux' ? { ...entry, sha256: sha256(bytes) } : entry,
    );
    writeFileSync(indexPath, `${JSON.stringify(index)}\n`);
    assert.throws(validate, /promotion_status=blocked reason=judgment_ledger_identity_mismatch/u);
  });
});

test('promotion fails closed when any required platform outcome is not passed', () => {
  withPromotionBundle(({ platformEvidence, root, validate }) => {
    const binding = platformEvidence.find(({ platform }) => platform === 'windows');
    const path = join(root, binding.name);
    const evidence = JSON.parse(readFileSync(path, 'utf8'));
    evidence.checks = evidence.checks.map((check) =>
      check.id === 'nsis_updater_apply' ? outcome('nsis_updater_apply', 'failed') : check,
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

test('promotion rejects missing platform package types and required checks', () => {
  withPromotionBundle(({ platformEvidence, root, validate }) => {
    const binding = platformEvidence.find(({ platform }) => platform === 'macos');
    const path = join(root, binding.name);
    const evidence = JSON.parse(readFileSync(path, 'utf8'));
    evidence.artifact_identities = evidence.artifact_identities.filter(
      ({ package_type: packageType }) => packageType !== 'zip',
    );
    const bytes = Buffer.from(`${JSON.stringify(evidence)}\n`);
    writeFileSync(path, bytes);
    const indexPath = join(root, 'release-evidence-index-v3.json');
    const index = JSON.parse(readFileSync(indexPath, 'utf8'));
    index.platform_evidence = index.platform_evidence.map((entry) =>
      entry.platform === 'macos' ? { ...entry, sha256: sha256(bytes) } : entry,
    );
    writeFileSync(indexPath, `${JSON.stringify(index)}\n`);
    assert.throws(validate, /promotion_status=blocked reason=platform_artifact_set_invalid/u);
  });

  withPromotionBundle(({ platformEvidence, root, validate }) => {
    const binding = platformEvidence.find(({ platform }) => platform === 'windows');
    const path = join(root, binding.name);
    const evidence = JSON.parse(readFileSync(path, 'utf8'));
    evidence.checks = evidence.checks.filter(({ id }) => id !== 'vault_acl');
    const bytes = Buffer.from(`${JSON.stringify(evidence)}\n`);
    writeFileSync(path, bytes);
    const indexPath = join(root, 'release-evidence-index-v3.json');
    const index = JSON.parse(readFileSync(indexPath, 'utf8'));
    index.platform_evidence = index.platform_evidence.map((entry) =>
      entry.platform === 'windows' ? { ...entry, sha256: sha256(bytes) } : entry,
    );
    writeFileSync(indexPath, `${JSON.stringify(index)}\n`);
    assert.throws(validate, /promotion_status=blocked reason=platform_evidence_check_set_invalid/u);
  });
});

test('promotion requires Browser Bridge CRX, update candidates, and policy assets', () => {
  withPromotionBundle(({ index, refreshLiveManifest, root, supplementalEvidence, validate }) => {
    const binding = supplementalEvidence.find(({ id }) => id === 'browser_bridge');
    const path = join(root, binding.name);
    const evidence = JSON.parse(readFileSync(path, 'utf8'));
    evidence.check.artifact_refs = evidence.check.artifact_refs.filter(
      ({ name }) => name !== 'browser-bridge-enterprise-policy-bundle.json',
    );
    const bytes = Buffer.from(`${JSON.stringify(evidence)}\n`);
    writeFileSync(path, bytes);
    index.supplemental_evidence = index.supplemental_evidence.map((entry) =>
      entry.id === 'browser_bridge' ? { ...entry, sha256: sha256(bytes) } : entry,
    );
    writeFileSync(join(root, 'release-evidence-index-v3.json'), `${JSON.stringify(index)}\n`);
    refreshLiveManifest();

    assert.throws(
      validate,
      /promotion_status=blocked reason=browser_bridge_release_asset_evidence_incomplete/u,
    );
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
  const evidenceWorkflow = readFileSync(
    new URL('.github/workflows/desktop-release-evidence.yml', repositoryRoot),
    'utf8',
  );
  const supplementalWorkflow = readFileSync(
    new URL('.github/workflows/desktop-release-supplemental-evidence.yml', repositoryRoot),
    'utf8',
  );
  const supplementalResolver = readFileSync(
    new URL('agi-stack/apps/desktop/scripts/resolve-supplemental-producers.sh', repositoryRoot),
    'utf8',
  );
  const parsedRelease = parse(releaseWorkflow);
  const parsedPromotion = parse(promotionWorkflow);
  const parsedEvidence = parse(evidenceWorkflow);

  assert.doesNotMatch(releaseWorkflow, /AGISTACK_RELEASE_VERSION:\s*['"]0\.1\.0['"]/u);
  assert.match(releaseWorkflow, /needs\.authorize\.outputs\.version/u);
  assert.match(releaseWorkflow, /--prerelease/u);
  assert.match(releaseWorkflow, /release-draft-validation\.mjs validate-combined/u);
  assert.equal(parsedPromotion.jobs.promote.environment, 'desktop-release-production');
  assert.deepEqual(parsedPromotion.jobs.promote.permissions, {
    actions: 'read',
    contents: 'write',
  });
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
  const prePromotionAssetLockIndex = promotionWorkflow.indexOf(
    'Revalidate immutable assets before stable promotion',
  );
  const promotionIndex = promotionWorkflow.indexOf('Promote the exact prerelease to stable');
  const postPromotionAssetLockIndex = promotionWorkflow.indexOf(
    'Verify immutable assets after stable promotion',
  );
  assert.ok(identityIndex >= 0 && identityIndex < checkoutIndex);
  assert.ok(checkoutIndex < validationIndex);
  assert.ok(validationIndex < prePromotionAssetLockIndex);
  assert.ok(prePromotionAssetLockIndex < promotionIndex);
  assert.ok(promotionIndex < postPromotionAssetLockIndex);
  assert.match(promotionWorkflow, /github_asset_set_changed_before_promotion/u);
  assert.match(promotionWorkflow, /github_asset_set_changed_after_promotion/u);
  assert.match(promotionWorkflow, /ref:\s*\$\{\{\s*steps\.identity\.outputs\.commit_sha\s*\}\}/u);
  assert.ok(parsedRelease.jobs.authorize.outputs.version);
  assert.deepEqual(parsedEvidence.on.workflow_dispatch.inputs.tag, {
    description: 'Exact protected desktop prerelease tag to assemble',
    required: true,
    type: 'string',
  });
  assert.equal(parsedEvidence.jobs.assemble.environment, 'desktop-release-qa');
  assert.deepEqual(parsedEvidence.jobs.assemble.permissions, {
    actions: 'read',
    contents: 'write',
  });
  assert.match(evidenceWorkflow, /source_release_not_prerelease/u);
  assert.match(evidenceWorkflow, /release-evidence-assembly\.mjs/u);
  assert.match(evidenceWorkflow, /resolve-supplemental-producers\.sh/u);
  assert.match(evidenceWorkflow, /producer_manifest/u);
  assert.match(evidenceWorkflow, /github_asset_set_changed_during_evidence_assembly/u);
  assert.match(evidenceWorkflow, /release-evidence-index-v3\.json/u);
  assert.doesNotMatch(evidenceWorkflow, /--clobber/u);
  assert.doesNotMatch(evidenceWorkflow, /gh release create/u);
  assert.match(promotionWorkflow, /resolve-supplemental-producers\.sh/u);
  assert.match(supplementalResolver, /actions\/artifacts\/.*\/zip/u);
  assert.match(supplementalResolver, /github-workflow-producers-v1/u);
  assert.match(supplementalResolver, /desktop-release-supplemental-evidence\.yml/u);
  assert.match(supplementalResolver, /producer-status\.json/u);
  assert.match(supplementalResolver, /producer_candidate_set_invalid/u);
  assert.match(supplementalResolver, /supplemental_id/u);
  assert.match(supplementalResolver, /release_identity/u);
  assert.match(supplementalResolver, /producer_run/u);
  assert.match(supplementalResolver, /\.path == \$workflow_path/u);
  assert.match(supplementalResolver, /\.event == "workflow_dispatch"/u);
  assert.match(supplementalResolver, /\.repository\.full_name == \$repository/u);
  assert.match(supplementalResolver, /status == "passed"/u);
  assert.match(supplementalResolver, /reason_code == null/u);
  assert.match(supplementalResolver, /retryable == false/u);
  assert.match(supplementalWorkflow, /rulesets\/rule-suites/u);
  assert.match(supplementalWorkflow, /refs\/tags\//u);
  assert.match(supplementalWorkflow, /all\(\$matching\[\]; \.result == "pass"\)/u);
  assert.match(supplementalWorkflow, /source_release_not_prerelease|release_untrusted/u);
  assert.match(supplementalWorkflow, /process\.env\.RELEASE_COMMIT_SHA/u);
  assert.doesNotMatch(supplementalWorkflow, /GITHUB_REF_PROTECTED/u);
  assert.doesNotMatch(supplementalWorkflow, /commit_sha.*!=.*GITHUB_SHA/u);
});
