import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import {
  cases,
  envelope,
  nativeScope,
  projectScope,
  pullContext,
  cloudContext,
  record,
  outcome,
} from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const {
  createNativeKnowledgeConflictController,
} = require('/tmp/agistack-project-knowledge-test-dist/src/features/project-knowledge/nativeKnowledgeConflictController.js');
const all = [
  'pull_conflict_context',
  'resolve_pull',
  'cloud_conflict_context',
  'resolve_push',
  'resolution',
  'reconciliation_context',
  'reconcile_resolution',
  'resume_resolution',
];
const authority = {
  scope: projectScope,
  userId: 'local-actor',
  sessionId: 'session-1',
  contextRevision: nativeScope.context_revision,
  generationDigest: 'renderer-1',
  available: true,
  allowedActions: all,
};
function fixture(options = {}) {
  const calls = [];
  let serial = 0;
  const client = {
    execute: async (scope, command, request) => {
      calls.push({ scope, command, request });
      const result = options.execute ? await options.execute(command, request, calls) : undefined;
      return (
        result ??
        envelope(
          command,
          structuredClone(cases.find(([item]) => item.operation === command.operation)[1]),
        )
      );
    },
  };
  const controller = createNativeKnowledgeConflictController({
    client,
    authority: { ...authority, ...options.authority },
    newId: () => `decision-${++serial}`,
  });
  return { controller, calls };
}
const error = (status, message = 'request_failed') => Object.assign(new Error(message), { status });

test('conflicts require exact read and write declarations and reject invalid authority', async () => {
  for (const restriction of [
    { allowedActions: ['view', 'update'] },
    { available: false },
    { userId: null },
    { sessionId: null },
    { generationDigest: null },
    { scope: { ...projectScope, authority: 'cloud' } },
  ]) {
    const { controller, calls } = fixture({ authority: restriction });
    await controller.open({ kind: 'pull', id: 'memory-1' });
    controller.choose('use_local');
    await controller.submit();
    assert.equal(calls.length, 0);
  }
  const { controller, calls } = fixture({
    authority: { allowedActions: ['pull_conflict_context'] },
  });
  await controller.open({ kind: 'pull', id: 'memory-1' });
  controller.choose('use_remote');
  await controller.submit();
  assert.deepEqual(controller.decisions(), []);
  assert.equal(calls.length, 1);
});

test('pull choices submit full fresh guards, merge preserves metadata, and retries preserve exact command/key', async () => {
  for (const decision of ['use_local', 'use_remote', 'keep_both', 'merged']) {
    let fail = true;
    const { controller, calls } = fixture({
      execute: async (command) => {
        if (command.operation === 'resolve_pull' && fail) throw error(502);
      },
    });
    await controller.open({ kind: 'pull', id: 'memory-1' });
    controller.choose(decision);
    if (decision === 'merged')
      controller.setDraft({
        title: 'merged title',
        content: 'merged content',
        metadata: { forged: true },
      });
    await controller.submit();
    assert.equal(controller.getSnapshot().phase, 'uncertain');
    const sent = calls.find((item) => item.command.operation === 'resolve_pull');
    assert.equal(sent.command.resolution.expected_local_revision, pullContext.local.version);
    assert.deepEqual(sent.request.expectedScope, nativeScope);
    assert.equal(
      calls.filter((item) => item.command.operation === 'pull_conflict_context').length,
      2,
    );
    assert.ok(Object.isFrozen(sent.command.resolution));
    if (decision === 'merged')
      assert.deepEqual(
        sent.command.resolution.choice.content.metadata,
        pullContext.remote.content.metadata,
      );
    controller.close();
    controller.choose('use_remote');
    await controller.open({ kind: 'push', localSequence: 1 });
    await controller.submit();
    assert.equal(controller.getSnapshot().phase, 'uncertain');
    fail = false;
    await controller.retry();
    const writes = calls.filter((item) => item.command.operation === 'resolve_pull');
    assert.equal(writes.length, 2);
    assert.equal(writes[0].command, writes[1].command);
    assert.equal(controller.getSnapshot().phase, 'accepted');
  }
});

test('changed preview invalidates decision before any write, including non-guard content changes', async () => {
  let count = 0;
  const { controller, calls } = fixture({
    execute: async (command) => {
      if (command.operation === 'pull_conflict_context') {
        count += 1;
        return envelope(command, {
          context:
            count === 1 ? pullContext : { ...pullContext, local_metadata: { changed: true } },
        });
      }
    },
  });
  await controller.open({ kind: 'pull', id: 'memory-1' });
  controller.choose('keep_both');
  await controller.submit();
  assert.equal(controller.getSnapshot().error, 'reviewChanged');
  assert.equal(controller.getSnapshot().decision, null);
  assert.equal(
    calls.some((item) => item.command.operation === 'resolve_pull'),
    false,
  );
  controller.choose('use_local');
  await controller.submit();
  assert.equal(controller.getSnapshot().phase, 'accepted');
});

test('push exposes only producer-supported choices and sends original conflict identity', async () => {
  const { controller, calls } = fixture();
  await controller.open({ kind: 'push', localSequence: 1 });
  assert.deepEqual(controller.decisions(), ['keep_current', 'use_proposed', 'merged']);
  controller.choose('keep_both');
  assert.equal(controller.getSnapshot().decision, null);
  controller.choose('use_proposed');
  await controller.submit();
  const write = calls.find((item) => item.command.operation === 'resolve_push').command;
  assert.equal(write.resolution.conflict_id, cloudContext.conflict_id);
  assert.equal(write.resolution.local_sequence, cloudContext.local_sequence);
  assert.deepEqual(write.resolution.choice, { decision: 'use_proposed' });
  assert.equal(controller.getSnapshot().pendingReconciliation, true);
});

test('pending reconciliation keeps original resolution ID and command on explicit unknown retry', async () => {
  let fail = true;
  const { controller, calls } = fixture({
    execute: async (command) => {
      if (command.operation === 'reconcile_resolution' && fail) throw error(502);
    },
  });
  await controller.open({ kind: 'resolution', id: record.resolution_id });
  controller.choose('keep_both');
  await controller.submit();
  assert.equal(controller.getSnapshot().phase, 'uncertain');
  fail = false;
  await controller.retry();
  const writes = calls.filter((item) => item.command.operation === 'reconcile_resolution');
  assert.equal(writes[0].command, writes[1].command);
  assert.equal(writes[0].command.resolution_id, record.resolution_id);
  assert.equal(writes[0].command.reconciliation.choice.decision, 'keep_both');
  assert.equal(controller.getSnapshot().pendingReconciliation, false);
});

test('resume rechecks persisted record; completed or rejected records cannot resume', async () => {
  for (const receipt of [null, record.receipt]) {
    const { controller, calls } = fixture({
      execute: async (command) =>
        command.operation === 'resolution'
          ? envelope(command, {
              record: {
                ...record,
                receipt,
                reconciliation: receipt ? { local_revision: 2 } : null,
              },
            })
          : undefined,
    });
    await controller.open({ kind: 'resolution', id: record.resolution_id });
    await controller.submit();
    assert.equal(
      calls.filter((item) => item.command.operation === 'resume_resolution').length,
      receipt ? 0 : 1,
    );
  }
  const rejected = fixture({
    execute: async (command) =>
      command.operation === 'resolution'
        ? envelope(command, {
            record: { ...record, receipt: null, rejection: { error: 'rejected' } },
          })
        : undefined,
  });
  await rejected.controller.open({ kind: 'resolution', id: record.resolution_id });
  await rejected.controller.submit();
  assert.equal(
    rejected.calls.some((item) => item.command.operation === 'resume_resolution'),
    false,
  );
});

test('409 needs a fresh reload and generation mismatch clears sensitive context', async () => {
  for (const message of ['request_failed', 'knowledge_generation_mismatch']) {
    const { controller, calls } = fixture({
      execute: async (command) => {
        if (command.operation === 'resolve_pull') throw error(409, message);
      },
    });
    await controller.open({ kind: 'pull', id: 'memory-1' });
    controller.choose('merged');
    await controller.submit();
    assert.equal(controller.getSnapshot().phase, 'error');
    assert.equal(controller.getSnapshot().draft, null);
    await controller.retry();
    assert.equal(calls.filter((item) => item.command.operation === 'resolve_pull').length, 1);
    if (message === 'knowledge_generation_mismatch')
      assert.equal(controller.getSnapshot().context, null);
    else {
      await controller.reload();
      assert.equal(controller.getSnapshot().phase, 'reviewing');
    }
  }
});

test('late context and accepted writes cannot repopulate a stopped or replaced binding', async () => {
  let release;
  const { controller } = fixture({
    execute: async (command) =>
      new Promise((resolve) => {
        release = () => resolve(envelope(command, { context: pullContext }));
      }),
  });
  const work = controller.open({ kind: 'pull', id: 'memory-1' });
  controller.stop();
  release();
  await work;
  assert.equal(controller.getSnapshot().context, null);
  controller.activate();
  const next = controller.open({ kind: 'pull', id: 'memory-1' });
  release();
  await next;
  assert.equal(controller.getSnapshot().phase, 'reviewing');
  let releaseWrite;
  const late = fixture({
    execute: async (command) =>
      command.operation === 'resolve_push'
        ? new Promise((resolve) => {
            releaseWrite = () => resolve(envelope(command, outcome));
          })
        : undefined,
  });
  await late.controller.open({ kind: 'push', localSequence: 1 });
  late.controller.choose('keep_current');
  const writing = late.controller.submit();
  while (!releaseWrite) await Promise.resolve();
  late.controller.stop();
  releaseWrite();
  await writing;
  assert.equal(late.controller.getSnapshot().phase, 'idle');
});
