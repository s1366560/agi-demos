import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { chmodSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import test from 'node:test';

import {
  assembleReleaseEvidenceIndexV3,
  writeReleaseEvidenceIndexV3,
} from '../scripts/release-evidence-assembly.mjs';

const releaseIdentity = Object.freeze({
  version: '0.2.0',
  tag: 'v0.2.0',
  commit_sha: 'a'.repeat(40),
  channel: 'prerelease',
  workflow_run: {
    id: '12345',
    attempt: '2',
    url: 'https://github.com/example/agi-demos/actions/runs/12345',
  },
});

const supplementalProducerContracts = Object.freeze({
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

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

function sha512(bytes) {
  return createHash('sha512').update(bytes).digest('base64');
}

function outcome(id, status = 'passed', artifactRefs = []) {
  const ref = {
    name: `${id}.log`,
    sha256: 'e'.repeat(64),
    url: `${releaseIdentity.workflow_run.url}#artifacts`,
  };
  return {
    id,
    status,
    reason_code: status === 'passed' ? null : `${id}_${status}`,
    timestamp: '2026-08-12T01:02:03.000Z',
    retryable: status !== 'passed',
    log_refs: [ref],
    artifact_refs: artifactRefs,
  };
}

function withAssemblyFixture(run) {
  const root = mkdtempSync(join(tmpdir(), 'agistack-release-evidence-assembly-'));
  const manifestPath = join(root, '..', `${basename(root)}-assets.json`);
  const producerManifestPath = join(root, '..', `${basename(root)}-producers.json`);
  try {
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
    const liveManifest = {
      contract_version: 'github-release-assets-v1',
      tag: releaseIdentity.tag,
      assets: packageFixtures.map(({ bytes, githubAssetId, name }) => ({
        github_asset_id: githubAssetId,
        name,
        size: bytes.byteLength,
        digest: `sha256:${sha256(bytes)}`,
      })),
    };
    for (const [name, source] of browserBridgeReleaseAssets) {
      const bytes = Buffer.from(source);
      writeFileSync(join(root, name), bytes);
      liveManifest.assets.push({
        github_asset_id: String(2000 + liveManifest.assets.length),
        name,
        size: bytes.byteLength,
        digest: `sha256:${sha256(bytes)}`,
      });
    }
    const platformEvidence = Object.keys(requiredPlatformChecks).map((platform, index) => {
      const packages = packageFixtures.filter((entry) => entry.platform === platform);
      return {
        contract_version: 'desktop-release-evidence-v3',
        release_identity: releaseIdentity,
        artifact_identities: packages.map(({ bytes, githubAssetId, name, packageType }) => ({
          github_asset_id: githubAssetId,
          name,
          size: bytes.byteLength,
          sha256: sha256(bytes),
          sha512: sha512(bytes),
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
                  url: `${releaseIdentity.workflow_run.url}#artifacts`,
                },
              ])
            : outcome(id),
        ),
        judgment_revision: releaseIdentity.commit_sha,
        judgment_ledger: {
          name: `${platform}-judgment-ledger.jsonl`,
          sha256: String(index + 4).repeat(64),
          url: `${releaseIdentity.workflow_run.url}#artifacts`,
        },
      };
    });
    for (const evidence of platformEvidence) {
      writeFileSync(
        join(root, `release-platform-evidence-${evidence.platform.os}-v3.json`),
        `${JSON.stringify(evidence)}\n`,
      );
    }

    const browserBridgeArtifactRefs = browserBridgeReleaseAssets.map(([name]) => ({
      name,
      sha256: sha256(readFileSync(join(root, name))),
      url: `${releaseIdentity.workflow_run.url}#artifacts`,
    }));
    const producerRuns = [];
    const supplementalEvidence = ['neo4j_runtime', 'wcag_aa', 'browser_bridge'].map((id, index) => {
      const contract = supplementalProducerContracts[id];
      const runId = String(50000 + index);
      const attempt = String(index + 1);
      const artifactBytes = Buffer.from(`trusted ${id} producer artifact bytes`);
      const producerArtifactName = `${id}-producer-artifact.zip`;
      writeFileSync(join(root, producerArtifactName), artifactBytes);
      liveManifest.assets.push({
        github_asset_id: String(3000 + index),
        name: producerArtifactName,
        size: artifactBytes.byteLength,
        digest: `sha256:${sha256(artifactBytes)}`,
      });
      const producerRun = {
        workflow_path: contract.workflowPath,
        id: runId,
        attempt,
        url: `https://github.com/example/agi-demos/actions/runs/${runId}/attempts/${attempt}`,
        head_sha: releaseIdentity.commit_sha,
        conclusion: 'success',
        artifact: {
          github_artifact_id: String(9000 + index),
          name: contract.artifactName,
          size: artifactBytes.byteLength,
          sha256: sha256(artifactBytes),
          release_asset_name: producerArtifactName,
        },
      };
      producerRuns.push({ supplemental_id: id, ...producerRun });
      const requiredRefs = contract.requiredRefs.map((name) => ({
        name,
        sha256: 'd'.repeat(64),
        url: `${producerRun.url}#artifacts`,
      }));
      return {
        contract_version: 'desktop-release-supplemental-evidence-v1',
        release_identity: releaseIdentity,
        id,
        producer_run: producerRun,
        judgment_revision: releaseIdentity.commit_sha,
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
    });
    for (const evidence of supplementalEvidence) {
      writeFileSync(
        join(root, `${evidence.id.replaceAll('_', '-')}-evidence.json`),
        `${JSON.stringify(evidence)}\n`,
      );
    }
    writeFileSync(
      producerManifestPath,
      `${JSON.stringify({
        contract_version: 'github-workflow-producers-v1',
        repository: 'example/agi-demos',
        runs: producerRuns,
      })}\n`,
    );
    writeFileSync(manifestPath, `${JSON.stringify(liveManifest)}\n`);

    return run({
      liveManifest,
      manifestPath,
      platformEvidence,
      root,
      supplementalEvidence,
      producerManifestPath,
    });
  } finally {
    rmSync(root, { recursive: true, force: true });
    rmSync(manifestPath, { force: true });
    rmSync(producerManifestPath, { force: true });
  }
}

test('v3 assembly binds exact release assets, platform evidence, and supplemental evidence', () => {
  withAssemblyFixture(({ manifestPath, producerManifestPath, root }) => {
    const index = assembleReleaseEvidenceIndexV3({
      releaseRoot: root,
      githubAssetManifestPath: manifestPath,
      producerManifestPath,
      expectedTag: releaseIdentity.tag,
      expectedCommitSha: releaseIdentity.commit_sha,
    });

    assert.equal(index.contract_version, 'desktop-release-evidence-index-v3');
    assert.equal(index.promotion_status, 'passed');
    assert.deepEqual(
      index.platform_evidence.map(({ platform }) => platform),
      ['linux', 'macos', 'windows'],
    );
    assert.deepEqual(
      index.supplemental_evidence.map(({ id }) => id),
      ['browser_bridge', 'neo4j_runtime', 'wcag_aa'],
    );
    assert.equal(index.assets.length, 13);
    assert.ok(index.assets.every(({ sha512: digest }) => digest.endsWith('==')));
  });
});

test('v3 assembly rejects incomplete or digest-drifted Browser Bridge release assets', () => {
  for (const [missingName] of browserBridgeReleaseAssets) {
    withAssemblyFixture(({ manifestPath, producerManifestPath, root, supplementalEvidence }) => {
      const evidence = supplementalEvidence.find(({ id }) => id === 'browser_bridge');
      evidence.check.artifact_refs = evidence.check.artifact_refs.filter(
        ({ name }) => name !== missingName,
      );
      writeFileSync(join(root, 'browser-bridge-evidence.json'), `${JSON.stringify(evidence)}\n`);

      assert.throws(
        () =>
          assembleReleaseEvidenceIndexV3({
            releaseRoot: root,
            githubAssetManifestPath: manifestPath,
            producerManifestPath,
          }),
        /Browser Bridge release asset evidence is incomplete/u,
      );
    });
  }
  withAssemblyFixture(({ manifestPath, producerManifestPath, root, supplementalEvidence }) => {
    const evidence = supplementalEvidence.find(({ id }) => id === 'browser_bridge');
    evidence.check.artifact_refs[0].sha256 = 'f'.repeat(64);
    writeFileSync(join(root, 'browser-bridge-evidence.json'), `${JSON.stringify(evidence)}\n`);
    assert.throws(
      () =>
        assembleReleaseEvidenceIndexV3({
          releaseRoot: root,
          githubAssetManifestPath: manifestPath,
          producerManifestPath,
        }),
      /Browser Bridge release asset identity mismatch/u,
    );
  });
});

test('v3 assembly accepts distinct release and producer runs but rejects producer trust drift', () => {
  withAssemblyFixture(({ manifestPath, producerManifestPath, root, supplementalEvidence }) => {
    const evidence = supplementalEvidence.find(({ id }) => id === 'wcag_aa');
    assert.notEqual(evidence.release_identity.workflow_run.id, evidence.producer_run.id);
    assert.equal(
      assembleReleaseEvidenceIndexV3({
        releaseRoot: root,
        githubAssetManifestPath: manifestPath,
        producerManifestPath,
      }).promotion_status,
      'passed',
    );

    evidence.producer_run.workflow_path = '.github/workflows/untrusted.yml';
    writeFileSync(join(root, 'wcag-aa-evidence.json'), `${JSON.stringify(evidence)}\n`);
    assert.throws(
      () =>
        assembleReleaseEvidenceIndexV3({
          releaseRoot: root,
          githubAssetManifestPath: manifestPath,
          producerManifestPath,
        }),
      /producer_run\.workflow_path must equal/u,
    );
  });
});

test('v3 assembly rejects producer attempt, head, conclusion, and artifact digest drift', () => {
  for (const mutate of [
    (run) => {
      run.attempt = '99';
    },
    (run) => {
      run.head_sha = 'b'.repeat(40);
    },
    (run) => {
      run.conclusion = 'failure';
    },
    (run) => {
      run.artifact.sha256 = 'f'.repeat(64);
    },
  ]) {
    withAssemblyFixture(({ manifestPath, producerManifestPath, root }) => {
      const manifest = JSON.parse(readFileSync(producerManifestPath, 'utf8'));
      mutate(manifest.runs.find(({ supplemental_id }) => supplemental_id === 'neo4j_runtime'));
      writeFileSync(producerManifestPath, `${JSON.stringify(manifest)}\n`);
      assert.throws(
        () =>
          assembleReleaseEvidenceIndexV3({
            releaseRoot: root,
            githubAssetManifestPath: manifestPath,
            producerManifestPath,
          }),
        /supplemental evidence producer (?:identity|artifact) mismatch: neo4j_runtime/u,
      );
    });
  }
});

test('v3 assembly rejects an arbitrary supplemental judgment revision', () => {
  withAssemblyFixture(({ manifestPath, producerManifestPath, root, supplementalEvidence }) => {
    const evidence = supplementalEvidence.find(({ id }) => id === 'neo4j_runtime');
    evidence.judgment_revision = 'f'.repeat(40);
    writeFileSync(join(root, 'neo4j-runtime-evidence.json'), `${JSON.stringify(evidence)}\n`);
    assert.throws(
      () =>
        assembleReleaseEvidenceIndexV3({
          releaseRoot: root,
          githubAssetManifestPath: manifestPath,
          producerManifestPath,
        }),
      /supplemental evidence neo4j_runtime judgment ledger identity mismatch/u,
    );
  });
});

test('v3 assembly rejects a dangling supplemental judgment ledger reference', () => {
  withAssemblyFixture(({ manifestPath, producerManifestPath, root, supplementalEvidence }) => {
    const evidence = supplementalEvidence.find(({ id }) => id === 'wcag_aa');
    evidence.judgment_ledger.sha256 = 'f'.repeat(64);
    writeFileSync(join(root, 'wcag-aa-evidence.json'), `${JSON.stringify(evidence)}\n`);
    assert.throws(
      () =>
        assembleReleaseEvidenceIndexV3({
          releaseRoot: root,
          githubAssetManifestPath: manifestPath,
          producerManifestPath,
        }),
      /supplemental evidence wcag_aa judgment ledger identity mismatch/u,
    );
  });
});

test('v3 assembly cannot promote without manual AT, physical Bridge, or Electron Neo4j refs', () => {
  for (const [id, requiredName] of [
    ['wcag_aa', 'nvda-at-ledger.jsonl'],
    ['browser_bridge', 'browser-bridge-windows-chrome-edge.log'],
    ['neo4j_runtime', 'neo4j-electron-matched-state.log'],
  ]) {
    withAssemblyFixture(({ manifestPath, producerManifestPath, root, supplementalEvidence }) => {
      const evidence = supplementalEvidence.find((entry) => entry.id === id);
      evidence.check.artifact_refs = evidence.check.artifact_refs.filter(
        ({ name }) => name !== requiredName,
      );
      writeFileSync(
        join(root, `${id.replaceAll('_', '-')}-evidence.json`),
        `${JSON.stringify(evidence)}\n`,
      );
      assert.throws(
        () =>
          assembleReleaseEvidenceIndexV3({
            releaseRoot: root,
            githubAssetManifestPath: manifestPath,
            producerManifestPath,
          }),
        new RegExp(`supplemental evidence required refs are incomplete: ${id}`, 'u'),
      );
    });
  }
});

test('v3 assembly rejects a required outcome that is not passed', () => {
  withAssemblyFixture(({ platformEvidence, manifestPath, producerManifestPath, root }) => {
    const evidence = platformEvidence.find(({ platform }) => platform.os === 'windows');
    evidence.checks = evidence.checks.map((check) =>
      check.id === 'nsis_updater_apply' ? outcome('nsis_updater_apply', 'failed') : check,
    );
    writeFileSync(
      join(root, 'release-platform-evidence-windows-v3.json'),
      `${JSON.stringify(evidence)}\n`,
    );

    assert.throws(
      () =>
        assembleReleaseEvidenceIndexV3({
          releaseRoot: root,
          githubAssetManifestPath: manifestPath,
          producerManifestPath,
        }),
      /required evidence is not passed: nsis_updater_apply/u,
    );
  });
});

test('v3 assembly rejects missing platform package types and required checks', () => {
  withAssemblyFixture(({ platformEvidence, manifestPath, producerManifestPath, root }) => {
    const evidence = platformEvidence.find(({ platform }) => platform.os === 'linux');
    evidence.artifact_identities = evidence.artifact_identities.filter(
      ({ package_type: packageType }) => packageType !== 'deb',
    );
    writeFileSync(
      join(root, 'release-platform-evidence-linux-v3.json'),
      `${JSON.stringify(evidence)}\n`,
    );
    assert.throws(
      () =>
        assembleReleaseEvidenceIndexV3({
          releaseRoot: root,
          githubAssetManifestPath: manifestPath,
          producerManifestPath,
        }),
      /platform artifact set is invalid: linux/u,
    );
  });

  withAssemblyFixture(({ platformEvidence, manifestPath, producerManifestPath, root }) => {
    const evidence = platformEvidence.find(({ platform }) => platform.os === 'macos');
    evidence.checks = evidence.checks.filter(({ id }) => id !== 'notarization');
    writeFileSync(
      join(root, 'release-platform-evidence-macos-v3.json'),
      `${JSON.stringify(evidence)}\n`,
    );
    assert.throws(
      () =>
        assembleReleaseEvidenceIndexV3({
          releaseRoot: root,
          githubAssetManifestPath: manifestPath,
          producerManifestPath,
        }),
      /platform evidence check set is invalid: macos/u,
    );
  });
});

test('v3 assembly rejects artifact identity drift and symlinked evidence', () => {
  withAssemblyFixture(({ manifestPath, platformEvidence, producerManifestPath, root }) => {
    const evidence = platformEvidence.find(({ platform }) => platform.os === 'linux');
    evidence.artifact_identities[0].github_asset_id = '9999';
    const evidencePath = join(root, 'release-platform-evidence-linux-v3.json');
    writeFileSync(evidencePath, `${JSON.stringify(evidence)}\n`);
    assert.throws(
      () =>
        assembleReleaseEvidenceIndexV3({
          releaseRoot: root,
          githubAssetManifestPath: manifestPath,
          producerManifestPath,
        }),
      /platform artifact identity mismatch: linux/u,
    );

    rmSync(evidencePath);
    symlinkSync(join(root, 'release-platform-evidence-macos-v3.json'), evidencePath);
    assert.throws(
      () =>
        assembleReleaseEvidenceIndexV3({
          releaseRoot: root,
          githubAssetManifestPath: manifestPath,
          producerManifestPath,
        }),
      /platform evidence is not a regular file/u,
    );
  });
});

test('v3 assembly writes immutable idempotent bytes and refuses replacement', () => {
  withAssemblyFixture(({ manifestPath, producerManifestPath, root }) => {
    const index = assembleReleaseEvidenceIndexV3({
      releaseRoot: root,
      githubAssetManifestPath: manifestPath,
      producerManifestPath,
    });
    const path = writeReleaseEvidenceIndexV3({ releaseRoot: root, index });
    assert.equal(writeReleaseEvidenceIndexV3({ releaseRoot: root, index }), path);
    assert.equal(JSON.parse(readFileSync(path, 'utf8')).promotion_status, 'passed');

    chmodSync(path, 0o600);
    writeFileSync(path, '{}\n');
    assert.throws(
      () => writeReleaseEvidenceIndexV3({ releaseRoot: root, index }),
      /already exists with different bytes/u,
    );
  });
});
