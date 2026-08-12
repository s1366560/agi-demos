import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const desktopRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const resolver = join(desktopRoot, 'scripts', 'resolve-supplemental-producers.sh');
const commitSha = 'a'.repeat(40);
const tag = 'v0.2.0';
const repository = 'example/repository';
const workflowPath = '.github/workflows/desktop-release-supplemental-evidence.yml';
const contracts = Object.freeze({
  browser_bridge: 'desktop-browser-bridge-release-evidence',
  neo4j_runtime: 'desktop-neo4j-runtime-evidence',
  wcag_aa: 'desktop-wcag-aa-evidence',
});

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

function createZip(root, id, runId, attempt, status = 'passed') {
  const source = join(root, `source-${id}-${runId}`);
  mkdirSync(source, { mode: 0o700 });
  const url = `https://github.com/${repository}/actions/runs/${runId}/attempts/${attempt}`;
  writeFileSync(
    join(source, 'producer-status.json'),
    `${JSON.stringify({
      contract_version: 'desktop-release-supplemental-producer-status-v1',
      release_identity: { tag, commit_sha: commitSha },
      supplemental_id: id,
      producer_run: {
        workflow_path: workflowPath,
        id: runId,
        attempt,
        url,
        head_sha: commitSha,
      },
      status,
      reason_code: status === 'passed' ? null : 'required_external_evidence_missing',
      retryable: status !== 'passed',
    })}\n`,
  );
  const zipPath = join(root, `${id}-${runId}.zip`);
  execFileSync('zip', ['-q', '-X', zipPath, 'producer-status.json'], { cwd: source });
  return readFileSync(zipPath);
}

function withResolverFixture(run) {
  const root = mkdtempSync(join(tmpdir(), 'agistack-supplemental-resolver-'));
  try {
    const bin = join(root, 'bin');
    const artifacts = join(root, 'artifacts');
    const runnerTemp = join(root, 'runner');
    mkdirSync(bin);
    mkdirSync(artifacts);
    mkdirSync(runnerTemp);
    const runs = [];
    const releaseAssets = [];
    const addRun = ({
      id,
      runId,
      attempt = '1',
      status = 'passed',
      publishReleaseAsset = true,
    }) => {
      const bytes = createZip(root, id, runId, attempt, status);
      const artifactId = String(900000 + Number(runId));
      writeFileSync(join(artifacts, `${artifactId}.zip`), bytes);
      const archiveDownloadUrl =
        `https://api.github.com/repos/${repository}/actions/artifacts/${artifactId}/zip`;
      runs.push({
        id: Number(runId),
        run_attempt: Number(attempt),
        head_sha: commitSha,
        path: workflowPath,
        event: 'workflow_dispatch',
        status: 'completed',
        conclusion: 'success',
        repository: { full_name: repository },
        artifact: {
          id: Number(artifactId),
          name: contracts[id],
          expired: false,
          archive_download_url: archiveDownloadUrl,
        },
      });
      if (publishReleaseAsset) {
        releaseAssets.push({
          github_asset_id: String(800000 + Number(runId)),
          name: `${id}-producer-artifact.zip`,
          size: bytes.byteLength,
          digest: `sha256:${sha256(bytes)}`,
        });
      }
    };
    for (const [index, id] of Object.keys(contracts).entries()) {
      addRun({ id, runId: String(100 + index) });
    }
    const ghPath = join(bin, 'gh');
    writeFileSync(
      ghPath,
      `#!/usr/bin/env bash
set -euo pipefail
path=''
for arg in "$@"; do
  if [[ "$arg" == repos/* ]]; then path="$arg"; break; fi
done
if [[ "$path" == *'/actions/workflows/'*'/runs?'* ]]; then
  jq -s '.' "$AGISTACK_TEST_RUNS_JSON"
elif [[ "$path" =~ /actions/runs/([0-9]+)/artifacts$ ]]; then
  run_id="\${BASH_REMATCH[1]}"
  jq --argjson run_id "$run_id" '{artifacts: [.workflow_runs[] | select(.id == $run_id) | .artifact]}' "$AGISTACK_TEST_RUNS_JSON"
elif [[ "$path" =~ /actions/artifacts/([0-9]+)/zip$ ]]; then
  artifact_id="\${BASH_REMATCH[1]}"
  command cat "$AGISTACK_TEST_ARTIFACT_ROOT/$artifact_id.zip"
else
  exit 97
fi
`,
      { mode: 0o700 },
    );
    chmodSync(ghPath, 0o700);
    const execute = () => {
      const runsPath = join(root, 'runs.json');
      const assetManifest = join(root, 'release-assets.json');
      const manifest = join(root, 'producers.json');
      const releaseAssetsByName = new Map(releaseAssets.map((asset) => [asset.name, asset]));
      writeFileSync(runsPath, `${JSON.stringify({ workflow_runs: runs })}\n`);
      writeFileSync(
        assetManifest,
        `${JSON.stringify({
          contract_version: 'github-release-assets-v1',
          tag,
          assets: [...releaseAssetsByName.values()],
        })}\n`,
      );
      const result = spawnSync('bash', [resolver, commitSha, tag, assetManifest, manifest], {
        encoding: 'utf8',
        env: {
          ...process.env,
          AGISTACK_TEST_ARTIFACT_ROOT: artifacts,
          AGISTACK_TEST_RUNS_JSON: runsPath,
          GITHUB_REPOSITORY: repository,
          PATH: `${bin}:${process.env.PATH}`,
          RUNNER_TEMP: runnerTemp,
        },
      });
      return { manifest, result };
    };
    return run({ addRun, execute, releaseAssets, runs });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test('supplemental resolver binds one status-verified run to each channel', () => {
  withResolverFixture(({ execute }) => {
    const { manifest, result } = execute();
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
    const value = JSON.parse(readFileSync(manifest, 'utf8'));
    assert.deepEqual(
      value.runs.map(({ supplemental_id }) => supplemental_id),
      ['neo4j_runtime', 'wcag_aa', 'browser_bridge'],
    );
    assert.equal(new Set(value.runs.map(({ id }) => id)).size, 3);
  });
});

test('supplemental resolver rejects a duplicate channel candidate', () => {
  withResolverFixture(({ execute, runs }) => {
    const existingWcag = runs.find(({ artifact }) => artifact.name === contracts.wcag_aa);
    runs.push(structuredClone(existingWcag));
    const { result } = execute();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /reason=producer_candidate_set_invalid/u);
  });
});

test('supplemental resolver rejects a blocked producer status', () => {
  withResolverFixture(({ addRun, execute, runs }) => {
    const wcagIndex = runs.findIndex(({ artifact }) => artifact.name === contracts.wcag_aa);
    runs.splice(wcagIndex, 1);
    addRun({ id: 'wcag_aa', runId: '888', status: 'blocked' });
    const { result } = execute();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /reason=producer_candidate_set_invalid/u);
  });
});

test('supplemental resolver rejects a live run from another commit', () => {
  withResolverFixture(({ execute, runs }) => {
    const wcagRun = runs.find(({ artifact }) => artifact.name === contracts.wcag_aa);
    wcagRun.head_sha = 'b'.repeat(40);
    const { result } = execute();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /reason=producer_candidate_set_invalid/u);
  });
});

test('supplemental resolver rejects invalid live artifact metadata', () => {
  for (const mutate of [
    (artifact) => {
      artifact.expired = true;
    },
    (artifact) => {
      artifact.archive_download_url = 'https://example.invalid/untrusted.zip';
    },
  ]) {
    withResolverFixture(({ execute, runs }) => {
      const bridgeRun = runs.find(
        ({ artifact }) => artifact.name === contracts.browser_bridge,
      );
      bridgeRun.artifact.archive_download_url =
        `https://api.github.com/repos/${repository}/actions/artifacts/${bridgeRun.artifact.id}/zip`;
      mutate(bridgeRun.artifact);
      const { result } = execute();
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, /reason=producer_candidate_set_invalid/u);
    });
  }
});
