import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { memory, nativeScope, projectScope } from './nativeKnowledgeFixtures.mjs';

const require = createRequire(import.meta.url);
const {
  createNativeMemoriesController,
} = require('/tmp/agistack-project-knowledge-test-dist/src/features/project-knowledge/nativeMemoriesController.js');
const authority = {
  scope: projectScope,
  userId: memory.author_id,
  sessionId: 'session-1',
  contextRevision: nativeScope.context_revision,
  generationDigest: 'renderer-generation-1',
  available: true,
  allowedActions: ['view', 'list', 'create', 'update', 'delete'],
};
const error = (status, message = 'request_failed') => Object.assign(new Error(message), { status });
function fixture(overrides = {}) {
  const calls = [];
  let serial = 0;
  let accepted = 0;
  const stored = { ...memory, tags: ['preserve'], entities: [{ name: 'node', kind: 'topic' }] };
  const client = {
    execute: async (scope, command, options) => {
      calls.push({ scope, command, options });
      if (overrides.execute) return overrides.execute(scope, command, options, calls);
      const result =
        command.operation === 'sync_status'
          ? { status: {} }
          : command.operation === 'get'
            ? { memory: stored }
            : {
                receipt: {
                  sequence: 1,
                  deleted: command.operation === 'delete',
                  memory: {
                    ...(command.memory ?? stored),
                    version: command.operation === 'create' ? 1 : command.expected_revision + 1,
                  },
                },
                replayed: false,
                processing_status: 'accepted',
              };
      return {
        contract_version: '1.0.0',
        scope: nativeScope,
        operation: command.operation,
        result,
      };
    },
  };
  const controller = createNativeMemoriesController({
    client,
    authority: { ...authority, ...overrides.authority },
    newId: () => `generated-${++serial}`,
    now: () => 123,
    onAccepted: () => {
      accepted += 1;
    },
  });
  return { controller, calls, stored, accepted: () => accepted };
}

test('native editor permissions come only from the declared current authority', async () => {
  for (const restricted of [
    { available: false },
    { allowedActions: [] },
    { userId: null },
    { sessionId: null },
    { generationDigest: null },
    { scope: { ...projectScope, authority: 'cloud' } },
  ]) {
    const { controller, calls } = fixture({ authority: restricted });
    await controller.create();
    await controller.open(memory.id, 'edit');
    await controller.confirmDelete();
    await controller.save();
    assert.equal(calls.length, 0);
    assert.equal(controller.getSnapshot().draft, null);
  }
  const { controller, calls } = fixture({ authority: { allowedActions: ['view', 'list'] } });
  await controller.create();
  await controller.open(memory.id, 'edit');
  await controller.open(memory.id, 'delete');
  assert.equal(calls.length, 0);
  await controller.open(memory.id, 'view');
  assert.deepEqual(
    calls.map(({ command }) => command.operation),
    ['sync_status', 'get'],
  );
  assert.equal(controller.getSnapshot().phase, 'viewing');
});

test('create observes context and uses the trusted actor and one immutable request', async () => {
  const { controller, calls, accepted } = fixture();
  await controller.create();
  controller.setDraft({ title: 'New', content: 'Body' });
  controller.setDraft({ author_id: 'forged', project_id: 'other', id: 'forged' });
  await controller.save();
  const sent = calls.at(-1);
  assert.equal(sent.command.operation, 'create');
  assert.equal(sent.command.memory.author_id, authority.userId);
  assert.equal(sent.command.memory.project_id, projectScope.projectId);
  assert.equal(sent.command.memory.created_at_ms, 123);
  assert.equal(sent.command.memory.version, 1);
  assert.equal(sent.command.idempotency_key, 'generated-2');
  assert.deepEqual(sent.options.expectedScope, nativeScope);
  assert(Object.isFrozen(sent.command.memory));
  assert.equal(controller.getSnapshot().notice, 'accepted');
  assert.equal(accepted(), 1);
});

test('double submit sends one write and unmount prevents a delayed acceptance refresh', async () => {
  let finish;
  const { controller, calls, accepted } = fixture({
    execute: async (_scope, command) => {
      if (command.operation === 'sync_status') return { scope: nativeScope };
      return new Promise((resolve) => {
        finish = resolve;
      });
    },
  });
  await controller.create();
  controller.setDraft({ content: 'Once only' });
  const first = controller.save();
  await controller.save();
  await controller.retryWrite();
  assert.equal(calls.filter(({ command }) => command.operation === 'create').length, 1);
  finish({ result: { receipt: { memory, deleted: false } } });
  controller.stop();
  await first;
  assert.equal(accepted(), 0);
  controller.activate();
  assert.equal(controller.getSnapshot().phase, 'idle');
  assert.equal(controller.getSnapshot().draft, null);
});

test('a newer selection cancels an older read even if the transport ignores abort', async () => {
  let finish;
  const { controller, calls } = fixture({
    execute: async (_scope, command) => {
      if (command.operation === 'sync_status') return { scope: nativeScope };
      return new Promise((resolve) => {
        finish = resolve;
      });
    },
  });
  const read = controller.open(memory.id, 'edit');
  await new Promise((resolve) => setImmediate(resolve));
  const readSignal = calls.at(-1).options.signal;
  await controller.create();
  assert.equal(readSignal.aborted, true);
  finish({ scope: nativeScope, result: { memory } });
  await read;
  assert.equal(controller.getSnapshot().phase, 'creating');
  assert.equal(controller.getSnapshot().record, null);
  assert.deepEqual(controller.getSnapshot().draft, { title: '', content: '' });
});

test('edit and delete fetch the full record and retain its exact revision and metadata', async () => {
  const { controller, calls, stored } = fixture();
  await controller.open(memory.id, 'edit');
  controller.setDraft({ content: 'Edited' });
  await controller.save();
  const updated = calls.at(-1).command;
  assert.equal(updated.operation, 'update');
  assert.equal(updated.expected_revision, stored.version);
  assert.deepEqual(updated.memory, { ...stored, content: 'Edited' });
  await controller.open(memory.id, 'delete');
  assert.equal(controller.getSnapshot().phase, 'confirming_delete');
  assert.equal(calls.at(-1).command.operation, 'get');
  await controller.confirmDelete();
  assert.deepEqual(calls.at(-1).command, {
    operation: 'delete',
    id: memory.id,
    expected_revision: stored.version,
    idempotency_key: 'generated-2',
  });
  assert.equal(controller.getSnapshot().record, null);
});

test('unknown write outcome locks the draft and explicitly retries the same request and key', async () => {
  let writes = 0;
  const { controller, calls } = fixture({
    execute: async (_scope, command) => {
      if (command.operation === 'sync_status') return { scope: nativeScope };
      if (++writes === 1) throw error(502);
      return {
        scope: nativeScope,
        result: {
          receipt: { sequence: 1, memory: command.memory, deleted: false },
          replayed: true,
          processing_status: 'accepted',
        },
      };
    },
  });
  await controller.create();
  controller.setDraft({ content: 'Possibly committed' });
  await controller.save();
  const pending = calls.at(-1).command;
  assert.equal(controller.getSnapshot().phase, 'uncertain');
  controller.setDraft({ content: 'Must not replace request' });
  controller.close();
  await controller.create();
  await controller.open(memory.id, 'edit');
  await controller.save();
  assert.equal(writes, 1);
  assert.equal(controller.getSnapshot().draft.content, 'Possibly committed');
  await controller.retryWrite();
  assert.equal(writes, 2);
  assert.strictEqual(calls.at(-1).command, pending);
  assert.equal(controller.getSnapshot().notice, 'accepted');
});

test('409 requires explicit reload, while generation conflicts clear sensitive state', async () => {
  for (const message of ['knowledge_revision_conflict', 'knowledge_generation_mismatch']) {
    const { controller, calls } = fixture({
      execute: async (_scope, command) => {
        if (command.operation === 'sync_status') return { scope: nativeScope };
        if (command.operation === 'get') return { scope: nativeScope, result: { memory } };
        throw error(409, message);
      },
    });
    await controller.open(memory.id, 'edit');
    await controller.save();
    assert.equal(controller.getSnapshot().phase, 'conflict');
    const count = calls.length;
    await controller.retryWrite();
    await controller.save();
    assert.equal(calls.length, count);
    if (message === 'knowledge_generation_mismatch') {
      assert.equal(controller.getSnapshot().draft, null);
      assert.equal(controller.getSnapshot().record, null);
    } else {
      await controller.reload();
      assert.equal(calls.at(-1).command.operation, 'get');
      assert.equal(controller.getSnapshot().phase, 'viewing');
    }
  }
});

test('scope revision drift during observation fails closed before creating a draft', async () => {
  const { controller, calls } = fixture({
    execute: async () => ({
      scope: { ...nativeScope, context_revision: nativeScope.context_revision + 1 },
    }),
  });
  await controller.create();
  assert.equal(calls.length, 1);
  assert.equal(controller.getSnapshot().phase, 'conflict');
  assert.equal(controller.getSnapshot().draft, null);
});

test('stop cancels in-flight operations, clears sensitive data and drops late results', async () => {
  let finish;
  const { controller, calls, accepted } = fixture({
    execute: async (_scope, command) => {
      if (command.operation === 'sync_status') return { scope: nativeScope };
      return new Promise((resolve) => {
        finish = resolve;
      });
    },
  });
  await controller.create();
  controller.setDraft({ title: 'Sensitive' });
  const writing = controller.save();
  controller.stop();
  assert.equal(calls.at(-1).options.signal.aborted, true);
  finish({ result: { receipt: { memory, deleted: false } } });
  await writing;
  assert.equal(controller.getSnapshot().draft, null);
  assert.equal(controller.getSnapshot().record, null);
  assert.equal(controller.getSnapshot().phase, 'unavailable');
  assert.equal(accepted(), 0);
  const count = calls.length;
  await controller.create();
  await controller.retryWrite();
  assert.equal(calls.length, count);
});
