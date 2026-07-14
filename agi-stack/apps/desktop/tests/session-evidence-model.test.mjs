import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { artifactEvidenceForCurrentVersions } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionEvidenceModel.js'
);

const baseVersion = {
  id: 'artifact-version-2',
  artifact_id: 'conversation-1:report',
  source_artifact_id: 'report',
  conversation_id: 'conversation-1',
  run_id: 'run-1',
  version: 2,
  status: 'ready',
  revision: 3,
  filename: 'report.md',
  mime_type: 'text/markdown',
  path: '/workspace/.agistack/artifacts/report/v2/report.md',
  relative_path: '.agistack/artifacts/report/v2/report.md',
  bytes: 128,
  sources: [],
  checks: [],
  created_at: '2026-07-13T08:50:00Z',
  updated_at: '2026-07-13T08:50:00Z',
};

test('current artifact evidence uses only the latest version per stable artifact', () => {
  const previous = {
    ...baseVersion,
    id: 'artifact-version-1',
    version: 1,
    revision: 8,
    sources: [{ id: 'old-source', label: 'Superseded source' }],
  };
  const current = {
    ...baseVersion,
    sources: [{ id: 'current-source', label: 'Current source' }],
  };
  const model = artifactEvidenceForCurrentVersions([previous, current], 'sources');

  assert.deepEqual(model.rows.map((row) => row.evidenceId), ['current-source']);
  assert.equal(model.rows[0]?.artifactVersionId, 'artifact-version-2');
  assert.equal(model.missing.length, 0);
});

test('sources and checks preserve explicit identity, location, and status fields', () => {
  const model = artifactEvidenceForCurrentVersions(
    [
      {
        ...baseVersion,
        checks: [
          {
            id: 'check-1',
            kind: 'test',
            label: 'Desktop unit tests',
            status: 'passed',
            path: 'apps/desktop/tests',
            line: 42,
            uri: 'artifact://check-1',
          },
        ],
      },
    ],
    'checks',
  );

  assert.deepEqual(model.rows[0], {
    artifactId: 'conversation-1:report',
    artifactVersionId: 'artifact-version-2',
    sourceArtifactId: 'report',
    filename: 'report.md',
    version: 2,
    revision: 3,
    runId: 'run-1',
    updatedAt: '2026-07-13T08:50:00Z',
    evidenceId: 'check-1',
    collection: 'checks',
    kind: 'test',
    label: 'Desktop unit tests',
    status: 'passed',
    uri: 'artifact://check-1',
    path: 'apps/desktop/tests',
    line: 42,
    raw: {
      id: 'check-1',
      kind: 'test',
      label: 'Desktop unit tests',
      status: 'passed',
      path: 'apps/desktop/tests',
      line: 42,
      uri: 'artifact://check-1',
    },
  });
});

test('missing checks remain explicitly missing and never become passed', () => {
  const model = artifactEvidenceForCurrentVersions([baseVersion], 'checks');
  assert.equal(model.rows.length, 0);
  assert.deepEqual(model.missing, [
    {
      artifactId: 'conversation-1:report',
      artifactVersionId: 'artifact-version-2',
      sourceArtifactId: 'report',
      filename: 'report.md',
      version: 2,
      revision: 3,
      runId: 'run-1',
      updatedAt: '2026-07-13T08:50:00Z',
      collection: 'checks',
    },
  ]);
});

test('unknown evidence remains inspectable without semantic inference', () => {
  const raw = { message: 'all tests appear green', details: { count: 4 } };
  const model = artifactEvidenceForCurrentVersions(
    [{ ...baseVersion, checks: [raw] }],
    'checks',
  );
  assert.equal(model.rows[0]?.label, null);
  assert.equal(model.rows[0]?.status, null);
  assert.equal(model.rows[0]?.kind, 'check');
  assert.deepEqual(model.rows[0]?.raw, raw);
});
