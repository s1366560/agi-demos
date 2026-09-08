import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { nativeScope, projectScope } from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const {
  createNativeKnowledgeProcessingController,
} = require('/tmp/agistack-project-knowledge-test-dist/src/features/project-knowledge/nativeKnowledgeProcessingController.js');
const configuration = {
  revision: 8,
  build_id: 'desired-B',
  provider_id: 'provider-1',
  provider_revision: 3,
  model_id: 'model-1',
  dimensions: 3,
  input_contract_version: 1,
  normalization_version: 1,
};
const snapshot = {
  configuration,
  active_build_id: 'active-A',
  processing: { current_sources: 5, applied_sources: 2, pending_sources: 2, failed_sources: 1 },
  index: { current_sources: 2, completed_sources: 1, failed_sources: 1 },
};
const receipt = {
  input: {
    source: {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      memory_id: 'memory-1',
      revision: 2,
      change_sequence: 3,
    },
    audit_attempt: 1,
    input_digest: 'digest-1',
  },
  attempt: 4,
  status: 'failed',
  failure: 'provider_unavailable',
};
const authority = {
  scope: projectScope,
  userId: 'user-1',
  sessionId: 'session-1',
  contextRevision: 7,
  generationDigest: 'renderer-1',
  available: true,
  allowedActions: [
    'configuration',
    'index_one',
    'promote_index',
    'retry_index',
    'select_embedding',
    'configure_embedding',
    'process_one',
  ],
};
function fixture(options = {}) {
  const queries = [],
    writes = [];
  const queryClient = {
    query: async (scope, command, request) => {
      queries.push({ scope, command, request });
      return (
        (await options.query?.(queries)) ?? {
          contract_version: '1.0.0',
          scope: nativeScope,
          result: structuredClone(snapshot),
        }
      );
    },
  };
  const commandClient = {
    execute: async (scope, command, request) => {
      writes.push({ scope, command, request });
      return (
        (await options.execute?.(writes)) ?? {
          contract_version: '1.0.0',
          scope: nativeScope,
          result:
            command.operation === 'index_one'
              ? { receipt: structuredClone(receipt) }
              : command.operation === 'retry_index'
                ? { accepted: true, input: command.input, attempt: command.expected_attempt }
                : command.operation === 'promote_index'
                  ? { configuration, active_build_id: command.build_id }
                  : {
                      configuration: { ...configuration, build_id: command.build_id, revision: 9 },
                    },
        }
      );
    },
  };
  const controller = createNativeKnowledgeProcessingController({
    queryClient: options.noQuery ? undefined : queryClient,
    commandClient: options.noCommand ? undefined : commandClient,
    authority: { ...authority, ...options.authority },
    onAccepted: options.onAccepted,
  });
  return { controller, queries, writes };
}

test('write admission requires both clients, configuration read and exact operation declarations', async () => {
  const unsupported = fixture();
  await unsupported.controller.review('configure_embedding');
  await unsupported.controller.review('process_one');
  assert.equal(unsupported.queries.length, 0);
  assert.equal(unsupported.writes.length, 0);
  for (const options of [
    { noQuery: true },
    { noCommand: true },
    { authority: { allowedActions: ['index_one'] } },
    { authority: { available: false } },
    { authority: { sessionId: null } },
    { authority: { generationDigest: null } },
    { authority: { scope: { ...projectScope, authority: 'cloud' } } },
  ]) {
    const { controller, queries, writes } = fixture(options);
    await controller.review('index_one');
    await controller.confirm();
    assert.equal(queries.length, 0);
    assert.equal(writes.length, 0);
    assert.equal(controller.getSnapshot().phase, 'unavailable');
  }
  const f = fixture({ authority: { allowedActions: ['configuration', 'promote_index'] } });
  await f.controller.review('index_one');
  assert.equal(f.queries.length, 0);
  await f.controller.review('promote_index');
  assert.equal(f.controller.getSnapshot().phase, 'reviewing');
});

test('index review and confirmation reread exact scope and configuration, preserve real failed receipt', async () => {
  const f = fixture();
  await f.controller.review('index_one');
  assert.equal(f.writes.length, 0);
  assert.equal(f.controller.getSnapshot().selection.operation, 'index_one');
  await f.controller.confirm();
  assert.equal(f.queries.length, 2);
  assert.equal(f.writes.length, 1);
  assert.deepEqual(f.writes[0].command, {
    operation: 'index_one',
    build_id: 'desired-B',
    config_revision: 8,
  });
  assert.deepEqual(f.writes[0].request.expectedScope, nativeScope);
  assert.ok(Object.isFrozen(f.writes[0].command));
  assert.deepEqual(f.controller.getSnapshot().failedTask.receipt, receipt);
  assert.equal(f.controller.getSnapshot().phase, 'accepted');
});

test('retry uses only an observed failed task receipt and exact attempt, never failure counts', async () => {
  const f = fixture();
  await f.controller.review('retry_index');
  assert.equal(f.controller.getSnapshot().error, 'failedReceiptRequired');
  assert.equal(f.writes.length, 0);
  await f.controller.review('index_one');
  await f.controller.confirm();
  await f.controller.review('retry_index');
  await f.controller.confirm();
  assert.deepEqual(f.writes[1].command, {
    operation: 'retry_index',
    build_id: 'desired-B',
    config_revision: 8,
    input: receipt.input,
    expected_attempt: 4,
  });
  assert.ok(Object.isFrozen(f.writes[1].command.input.source));
  assert.equal(f.controller.getSnapshot().outcome.operation, 'retry_index');
  assert.equal(f.controller.getSnapshot().failedTask, null);
});

test('promotion pins active build CAS and selection uses only observed active ID', async () => {
  const f = fixture();
  await f.controller.review('promote_index');
  await f.controller.confirm();
  assert.deepEqual(f.writes[0].command, {
    operation: 'promote_index',
    build_id: 'desired-B',
    config_revision: 8,
    expected_active_build_id: 'active-A',
  });
  await f.controller.review('select_embedding');
  await f.controller.confirm();
  assert.deepEqual(f.writes[1].command, {
    operation: 'select_embedding',
    build_id: 'active-A',
    expected_config_revision: 8,
  });
  assert.equal('profile' in f.writes[1].command, false);
  const noActive = fixture({
    query: async () => ({ scope: nativeScope, result: { ...snapshot, active_build_id: null } }),
  });
  await noActive.controller.review('select_embedding');
  assert.equal(noActive.controller.getSnapshot().error, 'activeRequired');
});

test('configuration and active changes require new review without sending the old command', async () => {
  for (const patch of [
    { configuration: { ...configuration, revision: 9 } },
    { active_build_id: 'new-active' },
  ]) {
    const f = fixture({
      query: async (calls) =>
        calls.length === 2 ? { scope: nativeScope, result: { ...snapshot, ...patch } } : undefined,
    });
    await f.controller.review('promote_index');
    await f.controller.confirm();
    assert.equal(f.writes.length, 0);
    assert.equal(f.controller.getSnapshot().error, 'reviewChanged');
    assert.equal(f.controller.getSnapshot().selection, null);
  }
  const ordered = fixture({
    query: async () => ({
      scope: nativeScope,
      result: {
        ...snapshot,
        configuration: Object.fromEntries(Object.entries(configuration).reverse()),
      },
    }),
  });
  await ordered.controller.review('index_one');
  await ordered.controller.confirm();
  assert.equal(ordered.writes.length, 1);
});

test('unknown writes never replay; unsuccessful recovery keeps locks and successful readback does not forge ACK', async () => {
  let failRefresh = false;
  const f = fixture({
    execute: async () => {
      throw Object.assign(Error('response_lost'), { status: 502 });
    },
    query: async () => {
      if (failRefresh) throw Error('offline');
    },
  });
  await f.controller.review('index_one');
  await f.controller.confirm();
  assert.equal(f.controller.getSnapshot().phase, 'uncertain');
  assert.equal(f.controller.getSnapshot().recoveryRequired, true);
  assert.equal(f.controller.getSnapshot().outcome, null);
  await f.controller.confirm();
  await f.controller.review('index_one');
  assert.equal(f.writes.length, 1);
  failRefresh = true;
  await f.controller.refresh();
  assert.equal(f.controller.getSnapshot().recoveryRequired, true);
  assert.equal(f.controller.getSnapshot().phase, 'uncertain');
  failRefresh = false;
  await f.controller.refresh();
  assert.equal(f.controller.getSnapshot().recoveryRequired, false);
  assert.equal(f.controller.getSnapshot().notice, 'recoveredUnknown');
  assert.equal(f.controller.getSnapshot().outcome, null);
  assert.equal(f.writes.length, 1);
  await f.controller.review('index_one');
  assert.equal(f.writes.length, 1);
  await f.controller.confirm();
  assert.equal(f.writes.length, 2);
});

test('scope drift clears reviewed data and late writes cannot return into stopped context', async () => {
  const drift = fixture({
    query: async (calls) =>
      calls.length === 2
        ? { scope: { ...nativeScope, generation: 99 }, result: snapshot }
        : undefined,
  });
  await drift.controller.review('index_one');
  await drift.controller.confirm();
  assert.equal(drift.writes.length, 0);
  assert.equal(drift.controller.getSnapshot().error, 'contextChanged');
  assert.equal(drift.controller.getSnapshot().snapshot, null);
  let release;
  let accepted = 0;
  const f = fixture({
    execute: () =>
      new Promise((resolve) => {
        release = resolve;
      }),
    onAccepted: () => accepted++,
  });
  await f.controller.review('index_one');
  const work = f.controller.confirm();
  await new Promise((resolve) => setImmediate(resolve));
  f.controller.stop();
  release({ scope: nativeScope, result: { receipt } });
  await work;
  assert.equal(f.controller.getSnapshot().outcome, null);
  assert.equal(accepted, 0);
  await f.controller.review('index_one');
  assert.equal(f.writes.length, 1);
  f.controller.activate();
  await f.controller.review('index_one');
  assert.equal(f.controller.getSnapshot().phase, 'reviewing');
});

test('double confirmation is serialized and null receipt is preserved without a completion verdict', async () => {
  let release;
  const f = fixture({
    execute: () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  });
  await f.controller.review('index_one');
  const first = f.controller.confirm();
  await new Promise((resolve) => setImmediate(resolve));
  await f.controller.confirm();
  assert.equal(f.writes.length, 1);
  release({ scope: nativeScope, result: { receipt: null } });
  await first;
  assert.deepEqual(f.controller.getSnapshot().outcome, {
    operation: 'index_one',
    result: { receipt: null },
  });
  assert.equal(f.controller.getSnapshot().failedTask, null);
});

test('known revision rejection is not an unknown write and provider unavailability is explicit', async () => {
  for (const [code, error] of [
    ['knowledge_revision_conflict', 'conflict'],
    ['knowledge_embedding_provider_unavailable', 'embeddingUnavailable'],
  ]) {
    const f = fixture({
      execute: async () => {
        throw Error(code);
      },
    });
    await f.controller.review('index_one');
    await f.controller.confirm();
    assert.equal(f.controller.getSnapshot().recoveryRequired, false);
    assert.equal(f.controller.getSnapshot().error, error);
    assert.equal(f.controller.getSnapshot().outcome, null);
  }
});
