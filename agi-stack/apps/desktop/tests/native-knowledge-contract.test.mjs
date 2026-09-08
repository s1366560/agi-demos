import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import {
  cases,
  envelope,
  nativeScope,
  projectScope,
  changeId,
  record,
  cloudResolution,
} from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const {
  prepareNativeKnowledgeCommand,
  requireNativeKnowledgeScope,
  requireNativeKnowledgeResponse,
} = require('/tmp/agistack-project-knowledge-test-dist/src/features/project-knowledge/nativeKnowledgeValidation.js');

test('typed native commands and responses preserve all declared sync contracts immutably', () => {
  for (const [command, result] of cases) {
    const prepared = prepareNativeKnowledgeCommand(command);
    assert.deepEqual(prepared, command);
    assert.notEqual(prepared, command);
    assert(Object.isFrozen(prepared));
    const response = requireNativeKnowledgeResponse(
      envelope(command, result),
      prepared,
      projectScope,
      nativeScope,
    );
    assert.deepEqual(response.result, result);
    assert(Object.isFrozen(response));
    assert(Object.isFrozen(response.scope));
    if (response.result !== null) assert(Object.isFrozen(response.result));
  }
});

test('native context requires exact version, six safe scope fields and matching project', () => {
  const input = { contract_version: '1.0.0', scope: nativeScope };
  assert.deepEqual(requireNativeKnowledgeScope(input, projectScope), nativeScope);
  for (const altered of [
    { ...input, contract_version: '1.0.1' },
    { ...input, contract_version: 1 },
    ...[
      { actor: 'forged' },
      { context_revision: 1.5 },
      { generation: Number.MAX_SAFE_INTEGER + 1 },
      { profile_id: '' },
      { digest: '' },
      { tenant_id: 'other' },
      { project_id: 'other' },
    ].map((change) => ({ ...input, scope: { ...nativeScope, ...change } })),
  ])
    assert.throws(() => requireNativeKnowledgeScope(altered, projectScope));
});

test('native commands reject actor, snapshots, URLs, unsafe counters and malformed choices', () => {
  for (const bad of [
    { operation: 'sync_push', actor: 'forged' },
    { operation: 'sync_pull', url: 'https://other' },
    { operation: 'pending_resolutions', limit: 0 },
    { operation: 'pending_resolutions', limit: 201 },
    { operation: 'pending_resolutions', limit: 1, before_resolution_id: 'bad' },
    {
      operation: 'sync_outbox',
      limit: 1,
      after_sequence: Number.MAX_SAFE_INTEGER + 1,
    },
    { operation: 'resume_resolution', resolution_id: 'bad' },
    {
      operation: 'resolve_push',
      resolution: cloudResolution,
      idempotency_key: ' ',
    },
    ...[
      { remote: {} },
      { choice: { decision: 'automatic' } },
      { guard: { ...cloudResolution.guard, conflict_sequences: [3, 2] } },
    ].map((change) => ({
      operation: 'resolve_push',
      resolution: { ...cloudResolution, ...change },
      idempotency_key: 'key',
    })),
  ])
    assert.throws(() => prepareNativeKnowledgeCommand(bad));
});

test('native results reject scope drift, unsafe values and crossed recovery identities', () => {
  const [command, result] = cases.find(([c]) => c.operation === 'resolution');
  for (const bad of [
    { ...envelope(command, result), contract_version: '2.0.0' },
    { ...envelope(command, result), operation: 'resolutions' },
    { ...envelope(command, result), extra: true },
    envelope(command, result, { ...nativeScope, generation: 5 }),
    ...[
      { resolution_id: '00000000-0000-4000-8000-000000000009' },
      { local_sequence: Number.MAX_SAFE_INTEGER + 1 },
      { request_json: JSON.stringify({ change_id: 'bad' }) },
      {
        receipt: {
          ...record.receipt,
          change_id: '00000000-0000-4000-8000-000000000009',
        },
      },
    ].map((change) => envelope(command, { record: { ...record, ...change } })),
  ])
    assert.throws(() => requireNativeKnowledgeResponse(bad, command, projectScope, nativeScope));
  const page = { operation: 'pending_resolutions', limit: 1 };
  for (const result of [
    { items: [record, record], next_before_resolution_id: changeId },
    {
      items: [record],
      next_before_resolution_id: '00000000-0000-4000-8000-000000000009',
    },
    {
      items: [
        {
          ...record,
          rejection: { detail: { code: 'knowledge_sync_resolution_stale' } },
        },
      ],
      next_before_resolution_id: null,
    },
  ])
    assert.throws(() =>
      requireNativeKnowledgeResponse(envelope(page, result), page, projectScope, nativeScope),
    );
});

test('completed recovery records retain the sidecar automatic reconciliation provenance', () => {
  const command = {
    operation: 'resolution',
    resolution_id: record.resolution_id,
  };
  const reconciled = {
    ...record,
    reconciliation_command: { source: 'cloud_receipt' },
    reconciliation_archive: record.archive,
    reconciliation: {
      local_revision: 2,
      copy_memory_id: null,
      processing_sequences: [3],
      pending_push_sequences: [],
      superseded_sequences: [],
      conflict_sequences: [2],
    },
  };
  const response = requireNativeKnowledgeResponse(
    envelope(command, { record: reconciled }),
    command,
    projectScope,
    nativeScope,
  );
  assert.deepEqual(response.result.record.reconciliation_command, {
    source: 'cloud_receipt',
  });
  for (const altered of [
    { reconciliation_command: null },
    { reconciliation_archive: null },
    { reconciliation: null },
    { reconciliation_archive: { ...record.archive, local_sequence: 2 } },
  ]) {
    assert.throws(() =>
      requireNativeKnowledgeResponse(
        envelope(command, { record: { ...reconciled, ...altered } }),
        command,
        projectScope,
        nativeScope,
      ),
    );
  }
});

test('local user metadata is bounded JSON, retained in immutable commands and explicitly clearable', async () => {
  const { memory } = await import('./nativeKnowledgeFixtures.mjs');
  const metadata = { nested: { values: [false, null, 7, '中文'] } };
  const command = {
    operation: 'create',
    memory: { ...memory, metadata },
    idempotency_key: 'metadata-contract',
  };
  const prepared = prepareNativeKnowledgeCommand(command);
  metadata.nested.values.push('later');
  assert.deepEqual(prepared.memory.metadata, {
    nested: { values: [false, null, 7, '中文'] },
  });
  assert(Object.isFrozen(prepared.memory.metadata.nested.values));
  assert.deepEqual(
    prepareNativeKnowledgeCommand({
      ...command,
      memory: { ...memory, metadata: {} },
    }).memory.metadata,
    {},
  );
  for (const invalid of [undefined, null, [], 'object', 1, { oversized: '界'.repeat(22_000) }]) {
    assert.throws(() =>
      prepareNativeKnowledgeCommand({
        ...command,
        memory: { ...memory, metadata: invalid },
      }),
    );
  }
});
