import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { cases, envelope, nativeScope, projectScope, status } from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const {
  createNativeKnowledgeSyncController,
} = require('/tmp/agistack-project-knowledge-test-dist/src/features/project-knowledge/nativeKnowledgeSyncController.js');
const all = [
  'sync_status',
  'sync_pull',
  'sync_push',
  'sync_unbind',
  'sync_outbox',
  'pull_conflicts',
  'push_conflicts',
  'pending_resolutions',
  'resolutions',
];
const authority = {
  scope: projectScope,
  userId: 'local-actor',
  sessionId: 'session-1',
  contextRevision: nativeScope.context_revision,
  generationDigest: nativeScope.digest,
  available: true,
  allowedActions: all,
};
function fixture(options = {}) {
  const calls = [];
  const client = {
    observeScope: async (scope, request) => {
      assert.deepEqual(scope, projectScope);
      assert.equal(request.expectedActorId, 'local-actor');
      return options.observeScope ? options.observeScope(request) : nativeScope;
    },
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
  const controller = createNativeKnowledgeSyncController({
    client,
    authority: { ...authority, ...options.authority },
  });
  return { controller, calls };
}
const error = (status) => Object.assign(new Error('request_failed'), { status });

test('sync never infers operation permissions from CRUD and invalid bindings perform no RPC', async () => {
  for (const restriction of [
    { allowedActions: ['list', 'view', 'update', 'create'] },
    { available: false },
    { userId: null },
    { sessionId: null },
    { generationDigest: null },
    { scope: { ...projectScope, authority: 'cloud' } },
  ]) {
    const { controller, calls } = fixture({ authority: restriction });
    await controller.refresh();
    await controller.sync('sync_push');
    await controller.sync('sync_pull');
    assert.equal(calls.length, 0);
  }
  const { controller, calls } = fixture({
    authority: { allowedActions: ['sync_status'] },
  });
  await controller.refresh();
  await controller.sync('sync_pull');
  assert.deepEqual(
    calls.map((item) => item.command.operation),
    ['sync_status'],
  );
});

test('sync refresh fetches only declared collections and forwards the observed scope', async () => {
  const { controller, calls } = fixture();
  await controller.refresh();
  assert.equal(controller.getSnapshot().status.link.remote_actor_id, status.link.remote_actor_id);
  assert.deepEqual(
    calls.map((item) => item.command.operation),
    [
      'sync_status',
      'sync_outbox',
      'pull_conflicts',
      'push_conflicts',
      'pending_resolutions',
      'resolutions',
    ],
  );
  for (const call of calls) assert.deepEqual(call.request.expectedScope, nativeScope);
  await controller.sync('sync_pull');
  assert.equal(calls.filter((item) => item.command.operation === 'sync_pull').length, 1);
  assert.equal(controller.getSnapshot().result.applied, 1);
  assert.equal(controller.getSnapshot().phase, 'ready');
});

test('unknown sync requires a successful complete refresh before a new explicit sync', async () => {
  let failWrite = true;
  let failRefresh = false;
  const { controller, calls } = fixture({
    execute: async (command) => {
      if (command.operation === 'sync_push' && failWrite) throw error(502);
      if (command.operation === 'pending_resolutions' && failRefresh) throw error(502);
    },
  });
  await controller.refresh();
  await controller.sync('sync_push');
  assert.equal(controller.getSnapshot().phase, 'uncertain');
  assert.equal(controller.getSnapshot().recoveryRequired, true);
  await controller.sync('sync_push');
  assert.equal(calls.filter((item) => item.command.operation === 'sync_push').length, 1);
  failRefresh = true;
  await controller.refresh();
  assert.equal(controller.getSnapshot().recoveryRequired, true);
  await controller.sync('sync_push');
  assert.equal(calls.filter((item) => item.command.operation === 'sync_push').length, 1);
  failRefresh = false;
  failWrite = false;
  await controller.refresh();
  assert.equal(controller.getSnapshot().recoveryRequired, false);
  assert.equal(calls.filter((item) => item.command.operation === 'sync_push').length, 1);
  await controller.sync('sync_push');
  assert.equal(calls.filter((item) => item.command.operation === 'sync_push').length, 2);
});

test('unbind forwards the explicit policy and refreshes the cleared binding state', async () => {
  const { controller, calls } = fixture({
    execute: async (command, _request, previous) => {
      if (
        command.operation === 'sync_status' &&
        previous.some((item) => item.command.operation === 'sync_unbind')
      )
        return envelope(command, { status: { ...status, link: null, pending_changes: 0 } });
      return undefined;
    },
  });
  await controller.refresh();
  await controller.unbind('delete');
  const unbindCalls = calls.filter((item) => item.command.operation === 'sync_unbind');
  assert.equal(unbindCalls.length, 1);
  assert.equal(unbindCalls[0].command.policy, 'delete');
  assert.equal(controller.getSnapshot().phase, 'ready');
  assert.equal(controller.getSnapshot().status.link, null);
  assert.equal(controller.getSnapshot().status.pending_changes, 0);
});

test('unbind without the declared action or a configured link performs no RPC', async () => {
  const restricted = fixture({ authority: { allowedActions: ['sync_status'] } });
  await restricted.controller.refresh();
  await restricted.controller.unbind('keep');
  assert.equal(
    restricted.calls.some((item) => item.command.operation === 'sync_unbind'),
    false,
  );
  const unlinked = fixture({
    execute: async (command) =>
      command.operation === 'sync_status'
        ? envelope(command, { status: { ...status, link: null } })
        : undefined,
  });
  await unlinked.controller.refresh();
  await unlinked.controller.unbind('keep');
  assert.equal(
    unlinked.calls.some((item) => item.command.operation === 'sync_unbind'),
    false,
  );
});

test('unknown unbind requires a successful complete refresh before a new explicit unbind', async () => {
  let failWrite = true;
  const { controller, calls } = fixture({
    execute: async (command) => {
      if (command.operation === 'sync_unbind' && failWrite) throw error(502);
    },
  });
  await controller.refresh();
  await controller.unbind('keep');
  assert.equal(controller.getSnapshot().phase, 'uncertain');
  assert.equal(controller.getSnapshot().recoveryRequired, true);
  await controller.unbind('keep');
  assert.equal(calls.filter((item) => item.command.operation === 'sync_unbind').length, 1);
  failWrite = false;
  await controller.refresh();
  assert.equal(controller.getSnapshot().recoveryRequired, false);
  await controller.unbind('keep');
  assert.equal(calls.filter((item) => item.command.operation === 'sync_unbind').length, 2);
});

test('sync scope drift clears data, no configured link forbids sync, and stop discards a late read', async () => {
  const changed = fixture({
    execute: async (command) =>
      envelope(command, { status }, { ...nativeScope, context_revision: 8 }),
  });
  await changed.controller.refresh();
  assert.equal(changed.controller.getSnapshot().error, 'contextChanged');
  assert.equal(changed.controller.getSnapshot().status, null);
  const unlinked = fixture({
    execute: async (command) =>
      command.operation === 'sync_status'
        ? envelope(command, { status: { ...status, link: null } })
        : undefined,
  });
  await unlinked.controller.refresh();
  await unlinked.controller.sync('sync_pull');
  assert.equal(
    unlinked.calls.some((item) => item.command.operation === 'sync_pull'),
    false,
  );
  let release;
  const late = fixture({
    execute: async (command) =>
      new Promise((resolve) => {
        release = () => resolve(envelope(command, { status }));
      }),
  });
  const work = late.controller.refresh();
  await new Promise(setImmediate);
  late.controller.stop();
  release();
  await work;
  assert.equal(late.controller.getSnapshot().status, null);
  assert.equal(late.calls.length, 1);
  await late.controller.refresh();
  assert.equal(late.controller.getSnapshot().phase, 'idle');
  assert.equal(late.calls.length, 1);
});

test('explicit pages use returned cursors and suppress duplicate simultaneous sync', async () => {
  let release;
  const { controller, calls } = fixture({
    execute: async (command) => {
      if (command.operation === 'sync_outbox')
        return envelope(command, {
          items: Array.from({ length: command.after_sequence ? 1 : 50 }, (_, index) => ({
            change_id: `change-${command.after_sequence + index + 1}`,
            local_change: {
              sequence: command.after_sequence + index + 1,
              memory: { title: 'item' },
            },
          })),
          next_sequence: command.after_sequence ? 51 : 50,
        });
      if (command.operation === 'pending_resolutions')
        return envelope(command, {
          items: [],
          next_before_resolution_id: command.before_resolution_id ? null : 'resolution-cursor',
        });
      if (command.operation === 'sync_pull')
        return new Promise((resolve) => {
          release = () =>
            resolve(
              envelope(command, {
                next_cursor: 1,
                applied: 1,
                conflicts: 0,
                has_more: false,
              }),
            );
        });
    },
  });
  await controller.refresh();
  await controller.moreOutbox();
  await controller.morePending();
  assert.equal(controller.getSnapshot().outbox.items.length, 51);
  assert.equal(
    calls.filter((item) => item.command.operation === 'sync_outbox')[1].command.after_sequence,
    50,
  );
  assert.equal(
    calls.filter((item) => item.command.operation === 'pending_resolutions')[1].command
      .before_resolution_id,
    'resolution-cursor',
  );
  const work = controller.sync('sync_pull');
  await controller.sync('sync_pull');
  assert.equal(calls.filter((item) => item.command.operation === 'sync_pull').length, 1);
  release();
  await work;
});

test('scope changes while loading a subsequent page clear previous sensitive state', async () => {
  const { controller } = fixture({
    execute: async (command) => {
      if (command.operation === 'pending_resolutions')
        return envelope(
          command,
          { items: [], next_before_resolution_id: 'next' },
          command.before_resolution_id
            ? { ...nativeScope, generation: nativeScope.generation + 1 }
            : nativeScope,
        );
    },
  });
  await controller.refresh();
  assert.ok(controller.getSnapshot().status);
  await controller.morePending();
  assert.equal(controller.getSnapshot().error, 'contextChanged');
  assert.equal(controller.getSnapshot().status, null);
  assert.equal(controller.getSnapshot().outbox, null);
});

test('a stopped scope observation cannot start a status RPC or publish stale state', async () => {
  let release;
  const { controller, calls } = fixture({
    observeScope: () =>
      new Promise((resolve) => {
        release = () => resolve(nativeScope);
      }),
  });
  const pending = controller.refresh();
  controller.stop();
  release();
  await pending;
  assert.deepEqual(calls, []);
  assert.equal(controller.getSnapshot().status, null);
});
