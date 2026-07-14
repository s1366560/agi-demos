import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  artifactDeliveryRequest,
  artifactReviewRequest,
  artifactVersionActions,
  currentArtifactVersions,
  deliveryForArtifactVersion,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionArtifactModel.js');

const run = {
  id: 'run-1',
  conversation_id: 'conversation-1',
  project_id: 'project-1',
  plan_version_id: 'plan-1',
  idempotency_key: 'run-key',
  message_id: 'message-1',
  request_message: 'Build it',
  status: 'ready_review',
  revision: 8,
  created_at: '2026-07-13T08:00:00Z',
  updated_at: '2026-07-13T09:00:00Z',
  authorization_snapshot: {},
};

const ready = {
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

test('current artifacts select the highest immutable version per stable artifact', () => {
  const previous = { ...ready, id: 'artifact-version-1', version: 1, status: 'superseded' };
  const other = {
    ...ready,
    id: 'artifact-version-other',
    artifact_id: 'conversation-1:patch',
    source_artifact_id: 'patch',
    filename: 'change.patch',
  };
  assert.deepEqual(
    currentArtifactVersions([previous, ready, other]).map((version) => version.id),
    ['artifact-version-2', 'artifact-version-other'],
  );
});

test('ready artifact actions keep approval separate from delivery', () => {
  assert.deepEqual(artifactVersionActions(ready, run), ['request_changes', 'approve']);
  assert.deepEqual(artifactVersionActions({ ...ready, status: 'approved' }, run), [
    'request_changes',
    'deliver',
  ]);
});

test('request changes binds artifact revision and authoritative run revision', () => {
  assert.deepEqual(artifactReviewRequest(ready, 'request_changes', run, 'Add the missing source'), {
    action: 'request_changes',
    expectedRevision: 3,
    runExpectedRevision: 8,
    feedback: 'Add the missing source',
  });
});

test('delivery is idempotent for one approved version revision', () => {
  assert.deepEqual(artifactDeliveryRequest({ ...ready, status: 'approved', revision: 4 }), {
    expectedRevision: 4,
    idempotencyKey: 'artifact-version-2:4:deliver',
    destination: 'local_workspace',
  });
});

test('delivered and superseded versions expose no mutation actions', () => {
  assert.deepEqual(artifactVersionActions({ ...ready, status: 'delivered' }, run), []);
  assert.deepEqual(artifactVersionActions({ ...ready, status: 'superseded' }, run), []);
});

test('delivery receipt selection stays bound to artifact version identity', () => {
  const receipt = {
    id: 'delivery-1',
    artifact_version_id: ready.id,
    artifact_id: ready.artifact_id,
    conversation_id: ready.conversation_id,
    destination: 'local_workspace',
    receipt: { path: ready.path },
    idempotency_key: 'delivery-key',
    created_at: '2026-07-13T09:30:00Z',
  };
  assert.equal(deliveryForArtifactVersion([receipt], ready.id)?.id, 'delivery-1');
  assert.equal(deliveryForArtifactVersion([receipt], 'other-version'), null);
});
