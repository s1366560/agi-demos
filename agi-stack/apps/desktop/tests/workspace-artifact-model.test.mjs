import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const {
  artifactIdFromRaw,
  artifactKind,
  artifactStatusRank,
  artifactsFromPlan,
  buildReviewDecisionSummary,
  buildWorkspaceArtifacts,
  makeWorkspaceArtifact,
  socketArtifactCandidate,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/workspaceArtifactModel.js'
);

test('artifact kind buckets names and hints into review categories', () => {
  assert.equal(artifactKind('fix.patch'), 'Patches');
  assert.equal(artifactKind('weekly-report.md'), 'Reports');
  assert.equal(artifactKind('run.log'), 'Logs');
  assert.equal(artifactKind('stream', 'artifact_created'), 'Events');
  assert.equal(artifactKind('plain.txt'), 'Files');
});

test('artifact status rank orders lifecycle progression', () => {
  assert.ok(artifactStatusRank('error') > artifactStatusRank('ready'));
  assert.ok(artifactStatusRank('ready') > artifactStatusRank('observed'));
  assert.ok(artifactStatusRank('observed') > artifactStatusRank('created'));
  assert.ok(artifactStatusRank('created') > artifactStatusRank('running'));
  assert.ok(artifactStatusRank('running') > artifactStatusRank('unknown'));
});

test('makeWorkspaceArtifact derives display time and searchable text', () => {
  const artifact = makeWorkspaceArtifact({
    id: 'a1',
    name: 'Report.md',
    path: 'docs/Report.md',
    kind: 'Reports',
    source: 'plan',
    status: 'indexed',
    sortTime: Number.NaN,
    size: '1.0 KB',
    diff: '',
    preview: 'Preview',
    raw: null,
  });
  assert.equal(artifact.time, 'unknown');
  assert.ok(artifact.searchableText.includes('report.md'));
  assert.ok(artifact.searchableText.includes('reports'));
});

test('workspace artifacts dedupe by identity and keep the furthest status', () => {
  const artifacts = buildWorkspaceArtifacts(
    [],
    [
      {
        type: 'artifact_created',
        payload: { artifact_id: 'a1', filename: 'report.md' },
      },
      {
        type: 'artifact_ready',
        payload: { artifact_id: 'a1', filename: 'report.md' },
      },
    ],
    null,
  );
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].status, 'ready');
  assert.equal(artifacts[0].name, 'report.md');
});

test('review decision summary falls back to an empty packet', () => {
  const summary = buildReviewDecisionSummary(null);
  assert.equal(summary.title, 'No review packet loaded');
  assert.equal(summary.risk, 'Unassessed');
  assert.equal(summary.filesChanged, 0);
  assert.equal(summary.canAct, false);
  assert.deepEqual(summary.artifacts, []);
  assert.deepEqual(summary.checks, []);
});

test('socket artifact candidate unwraps nested artifact envelopes', () => {
  const candidate = socketArtifactCandidate({
    type: 'message',
    payload: { type: 'artifact_ready', data: { artifact_id: 'a1' } },
  });
  assert.equal(candidate.type, 'artifact_ready');
  assert.deepEqual(candidate.payload, { artifact_id: 'a1' });
  assert.equal(
    socketArtifactCandidate({ type: 'progress', payload: { message: 'work' } }),
    null,
  );
});

test('artifact id resolves through nested payload envelopes', () => {
  assert.equal(artifactIdFromRaw({ payload: { data: { artifact_id: 'x' } } }), 'x');
  assert.equal(artifactIdFromRaw({ artifactId: 'y' }), 'y');
  assert.equal(artifactIdFromRaw('nope'), undefined);
  assert.equal(artifactIdFromRaw({ payload: { payload: {} } }), undefined);
});

test('plan artifact index entries become indexed plan artifacts', () => {
  assert.deepEqual(artifactsFromPlan(null), []);
  const artifacts = artifactsFromPlan({
    artifacts: [{ name: 'report.md', type: 'file' }],
  });
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].id, 'plan-artifact-0');
  assert.equal(artifacts[0].source, 'plan');
  assert.equal(artifacts[0].status, 'indexed');
  assert.equal(artifacts[0].kind, 'Reports');
});
