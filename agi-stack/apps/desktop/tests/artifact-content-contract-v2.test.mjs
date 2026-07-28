import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  ARTIFACT_CONFLICT_ACTIONS,
  applyArtifactSaveReceipt,
  createArtifactDraftState,
  createArtifactSaveCommandV2,
  editArtifactDraft,
  isEditableArtifactMime,
  markArtifactSaveConflict,
  planArtifactConflictResolution,
  readArtifactContentContractV2,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/artifactContentContractV2.js',
);

const HASH_A = `sha256:${'a'.repeat(64)}`;
const HASH_B = `sha256:${'b'.repeat(64)}`;
const HASH_C = `sha256:${'c'.repeat(64)}`;

function authority(overrides = {}) {
  return {
    contract_version: 2,
    artifact_id: 'artifact-1',
    revision: 7,
    content_hash: HASH_A,
    mime_type: 'text/markdown; charset=UTF-8',
    content: '# Server copy',
    ...overrides,
  };
}

test('ArtifactContentContractV2 accepts canonical authority and normalizes MIME parameters', () => {
  assert.deepEqual(readArtifactContentContractV2(authority()), {
    ok: true,
    value: {
      contract_version: 2,
      artifact_id: 'artifact-1',
      revision: 7,
      content_hash: HASH_A,
      mime_type: 'text/markdown',
      content: '# Server copy',
    },
  });
});

test('ArtifactContentContractV2 fails closed on malformed version, revision, hash, or identity', () => {
  for (const [value, reason] of [
    [authority({ contract_version: 1 }), 'unsupported_contract_version'],
    [authority({ artifact_id: '  ' }), 'invalid_artifact_id'],
    [authority({ revision: -1 }), 'invalid_revision'],
    [authority({ revision: 1.5 }), 'invalid_revision'],
    [authority({ content_hash: 'sha256:not-a-digest' }), 'invalid_content_hash'],
    [authority({ mime_type: '' }), 'invalid_mime_type'],
    [authority({ content: null }), 'invalid_content'],
  ]) {
    assert.deepEqual(readArtifactContentContractV2(value), { ok: false, reason });
  }
});

test('only an explicit set of text MIME types is editable', () => {
  for (const mimeType of [
    'text/plain',
    'text/markdown; charset=utf-8',
    'text/html',
    'text/css',
    'text/javascript',
    'text/x-python',
    'text/x-typescript',
    'text/csv',
    'text/xml',
    'text/yaml',
    'application/json',
    'application/xml',
    'application/javascript',
    'application/x-yaml',
  ]) {
    assert.equal(isEditableArtifactMime(mimeType), true, mimeType);
  }

  for (const mimeType of [
    'application/pdf',
    'image/svg+xml',
    'image/png',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/octet-stream',
    'text/event-stream',
  ]) {
    assert.equal(isEditableArtifactMime(mimeType), false, mimeType);
  }
});

test('save command binds draft hash, expected authority revision, and idempotency key', () => {
  const result = createArtifactSaveCommandV2({
    authority: authority(),
    draftContent: '# Local draft',
    draftContentHash: HASH_B,
    expectedRevision: 7,
    idempotencyKey: 'artifact-1:save:revision-7',
  });

  assert.deepEqual(result, {
    ok: true,
    command: {
      contract_version: 2,
      expected_revision: 7,
      content_hash: HASH_B,
      idempotency_key: 'artifact-1:save:revision-7',
      content: '# Local draft',
    },
  });
});

test('save command rejects stale revision, unsafe MIME, invalid hash, and invalid idempotency', () => {
  const base = {
    authority: authority(),
    draftContent: '# Local draft',
    draftContentHash: HASH_B,
    expectedRevision: 7,
    idempotencyKey: 'artifact-1:save:revision-7',
  };
  assert.deepEqual(createArtifactSaveCommandV2({ ...base, expectedRevision: 6 }), {
    ok: false,
    reason: 'expected_revision_mismatch',
  });
  assert.deepEqual(
    createArtifactSaveCommandV2({
      ...base,
      authority: authority({ mime_type: 'application/pdf' }),
    }),
    { ok: false, reason: 'mime_not_editable' },
  );
  assert.deepEqual(createArtifactSaveCommandV2({ ...base, draftContentHash: 'bad' }), {
    ok: false,
    reason: 'invalid_content_hash',
  });
  assert.deepEqual(createArtifactSaveCommandV2({ ...base, idempotencyKey: 'short' }), {
    ok: false,
    reason: 'invalid_idempotency_key',
  });
  assert.deepEqual(createArtifactSaveCommandV2({ ...base, draftContent: null }), {
    ok: false,
    reason: 'invalid_content',
  });
});

test('a 409 conflict preserves the exact local draft and exposes three explicit decisions', () => {
  const initial = createArtifactDraftState(authority());
  assert.ok(initial);
  const edited = editArtifactDraft(initial, '# Local draft', HASH_B);
  const conflict = markArtifactSaveConflict(edited, {
    httpStatus: 409,
    serverRevision: 8,
    serverContentHash: HASH_C,
  });

  assert.ok(conflict);
  assert.equal(conflict.phase, 'conflict');
  assert.equal(conflict.draftContent, '# Local draft');
  assert.equal(conflict.draftContentHash, HASH_B);
  assert.equal(conflict.authority.revision, 7);
  assert.deepEqual(conflict.conflict, {
    serverRevision: 8,
    serverContentHash: HASH_C,
  });
  assert.deepEqual(ARTIFACT_CONFLICT_ACTIONS, [
    'reload_server',
    'save_copy',
    'copy_draft',
  ]);

  assert.deepEqual(planArtifactConflictResolution(conflict, 'reload_server'), {
    type: 'reload_server',
    artifactId: 'artifact-1',
    preserveDraftUntilSuccess: true,
  });
  assert.deepEqual(planArtifactConflictResolution(conflict, 'save_copy'), {
    type: 'save_copy',
    artifactId: 'artifact-1',
    content: '# Local draft',
    contentHash: HASH_B,
  });
  assert.deepEqual(planArtifactConflictResolution(conflict, 'copy_draft'), {
    type: 'copy_draft',
    content: '# Local draft',
  });
  assert.equal(planArtifactConflictResolution(conflict, 'unexpected_action'), null);

  assert.equal(conflict.draftContent, '# Local draft');
  assert.equal(markArtifactSaveConflict(edited, { httpStatus: 412 }), null);
});

test('a matching save receipt advances authority and clears dirty state without trusting mismatches', () => {
  const initial = createArtifactDraftState(authority());
  assert.ok(initial);
  const edited = editArtifactDraft(initial, '# Local draft', HASH_B);
  const saved = applyArtifactSaveReceipt(edited, {
    artifact_id: 'artifact-1',
    revision: 8,
    content_hash: HASH_B,
    duplicate: false,
  });

  assert.ok(saved);
  assert.equal(saved.phase, 'clean');
  assert.equal(saved.authority.revision, 8);
  assert.equal(saved.authority.content_hash, HASH_B);
  assert.equal(saved.authority.content, '# Local draft');
  assert.equal(saved.draftContent, '# Local draft');
  assert.equal(saved.draftContentHash, HASH_B);
  assert.equal(saved.conflict, null);

  assert.equal(
    applyArtifactSaveReceipt(saved, {
      artifact_id: 'artifact-1',
      revision: 8,
      content_hash: HASH_B,
      duplicate: true,
    }),
    saved,
  );
  assert.equal(
    applyArtifactSaveReceipt(edited, {
      artifact_id: 'other-artifact',
      revision: 8,
      content_hash: HASH_B,
      duplicate: false,
    }),
    null,
  );
  assert.equal(
    applyArtifactSaveReceipt(edited, {
      artifact_id: 'artifact-1',
      revision: 8,
      content_hash: HASH_C,
      duplicate: false,
    }),
    null,
  );
});
