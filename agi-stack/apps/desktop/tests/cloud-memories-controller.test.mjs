import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const {
  createCloudMemoriesController,
} = require('/tmp/agistack-project-knowledge-test-dist/src/features/project-knowledge/cloudMemoriesController.js');
const scope = { authority: 'cloud', tenantId: 'tenant-1', projectId: 'project-1' };
const memory = {
  id: 'memory-1',
  projectId: 'project-1',
  title: 'Original title',
  content: 'Original full content',
  contentType: 'text',
  version: 1,
  status: 'ENABLED',
  processingStatus: 'pending',
  createdAt: '2026-09-08T00:00:00Z',
  updatedAt: null,
};
const authority = {
  scope,
  actorId: 'actor-1',
  sessionId: 'session-1',
  contextRevision: 7,
  generationDigest: 'generation-1',
  available: true,
  allowedActions: ['list', 'view'],
};
function fixture(options = {}) {
  let current = { ...memory };
  const calls = [],
    loads = [];
  const listClient = {
    load: async (s, request) => {
      loads.push(request);
      return (
        (await options.load?.(current, request, loads)) ?? {
          scope,
          scopeRevision: 7,
          authority: 'cloud',
          availability: 'degraded',
          reasonCode: 'partial',
          allowedActions: ['list', 'view', 'create', 'update', 'delete'],
          memories: current ? [{ ...current }] : [],
          page: request.page,
          pageSize: 50,
          total: current ? 1 : 0,
          commandCapabilities: {
            protocolVersion: 1,
            tenantId: 'tenant-1',
            projectId: 'project-1',
            actorId: 'actor-1',
            allowedActions: ['create'],
            objects: current
              ? [
                  {
                    memoryId: current.id,
                    revision: current.version,
                    allowedActions: ['update', 'delete'],
                  },
                ]
              : [],
          },
        }
      );
    },
  };
  const client = {
    execute: async (s, command, request) => {
      calls.push({ scope: s, command, request });
      const overridden = await options.execute?.(
        command,
        request,
        calls,
        () => current,
        (value) => {
          current = value;
        },
      );
      if (overridden) return overridden;
      if (command.operation === 'get') return { operation: 'get', result: { ...current } };
      if (command.operation === 'create')
        current = {
          ...memory,
          id: 'created-memory',
          title: command.memory.title,
          content: command.memory.content,
        };
      if (command.operation === 'update')
        current = { ...current, ...command.patch, version: current.version + 1 };
      if (command.operation === 'delete') {
        current = null;
        return { operation: 'delete', result: { memoryId: command.id, deleted: true } };
      }
      return { operation: command.operation, result: { ...current } };
    },
  };
  const controller = createCloudMemoriesController({
    authority: { ...authority, ...options.authority },
    listClient,
    client: options.noClient ? undefined : client,
  });
  return { controller, calls, loads, listClient };
}

test('cloud UI requires trusted binding and supports list-only without command client', async () => {
  for (const patch of [
    { available: false },
    { actorId: null },
    { sessionId: null },
    { generationDigest: null },
    { contextRevision: null },
    { scope: { ...scope, authority: 'local' } },
  ]) {
    const f = fixture({ authority: patch });
    await f.controller.loadPage();
    assert.equal(f.loads.length, 0);
    assert.equal(f.controller.getSnapshot().phase, 'unavailable');
  }
  const f = fixture({ noClient: true });
  await f.controller.loadPage();
  assert.equal(f.loads.length, 1);
  assert.equal(f.controller.getSnapshot().canCreate, false);
  assert.equal(f.controller.canView(), false);
});

test('missing malformed actor-mismatched and wrong row revision capabilities never grant writes', async () => {
  for (const capabilities of [
    undefined,
    null,
    { protocolVersion: 1 },
    {
      protocolVersion: 1,
      tenantId: 'tenant-1',
      projectId: 'project-1',
      actorId: 'actor-2',
      allowedActions: ['create'],
      objects: [],
    },
    {
      protocolVersion: 1,
      tenantId: 'tenant-1',
      projectId: 'project-1',
      actorId: 'actor-1',
      allowedActions: ['create'],
      objects: [{ memoryId: 'memory-1', revision: 9, allowedActions: ['update', 'delete'] }],
    },
  ]) {
    const f = fixture();
    const original = f.listClient.load;
    f.listClient.load = async (...args) => ({
      ...(await original(...args)),
      commandCapabilities: capabilities,
    });
    await f.controller.loadPage();
    assert.equal(f.controller.getSnapshot().canCreate, false);
    assert.equal(f.controller.canUpdate(memory), false);
    assert.equal(f.controller.canDelete(memory), false);
    await f.controller.open('memory-1', 'view');
    assert.equal(f.calls.length, 1);
  }
});

test('create uses immutable title-content-text command and exact actor/context, then acknowledged list refresh', async () => {
  const f = fixture();
  await f.controller.loadPage();
  f.controller.create();
  f.controller.setDraft({
    title: 'New title',
    content: 'Exact body',
    authorId: 'forged',
    tags: ['do not send'],
  });
  await f.controller.save();
  const command = f.calls[0].command;
  assert.equal(command.operation, 'create');
  assert.match(command.idempotencyKey, /^[0-9a-f-]{36}$/);
  assert.deepEqual(command.memory, {
    title: 'New title',
    content: 'Exact body',
    contentType: 'text',
  });
  assert.ok(Object.isFrozen(command.memory));
  assert.equal(f.calls[0].request.expectedActorId, 'actor-1');
  assert.equal(f.calls[0].request.expectedContextRevision, 7);
  assert.equal(f.controller.getSnapshot().notice, 'accepted');
  assert.equal(f.loads.length, 2);
});

test('detail comes from GET and updates only title and content at the exact authorized revision', async () => {
  const f = fixture();
  await f.controller.loadPage();
  await f.controller.open('memory-1', 'edit');
  assert.equal(f.calls[0].command.operation, 'get');
  f.controller.setDraft({ title: 'Changed', content: 'Changed body', metadata: { forged: true } });
  await f.controller.save();
  assert.deepEqual(f.calls[1].command.patch, { title: 'Changed', content: 'Changed body' });
  assert.equal(f.calls[1].command.expectedRevision, 1);
});

test('GET newer than advertised object capability remains read-only until fresh list review', async () => {
  const f = fixture({
    execute: async (command) =>
      command.operation === 'get'
        ? { operation: 'get', result: { ...memory, version: 2 } }
        : undefined,
  });
  await f.controller.loadPage();
  await f.controller.open('memory-1', 'edit');
  assert.equal(f.controller.getSnapshot().phase, 'viewing');
  assert.equal(f.controller.getSnapshot().error, 'permissionChanged');
  await f.controller.save();
  assert.equal(f.calls.length, 1);
});

test('unknown update preserves the original immutable request, UUID and revision; no refresh or competing action', async () => {
  let once = true;
  const f = fixture({
    execute: async (command) => {
      if (command.operation === 'update' && once) {
        once = false;
        throw Object.assign(Error('response_lost'), { status: 502 });
      }
    },
  });
  await f.controller.loadPage();
  await f.controller.open('memory-1', 'edit');
  f.controller.setDraft({ title: 'Draft', content: 'Unknown content' });
  await f.controller.save();
  const original = f.calls[1].command;
  assert.equal(f.controller.getSnapshot().phase, 'uncertain');
  f.controller.close();
  f.controller.create();
  await f.controller.loadPage();
  await f.controller.goToPage(2);
  await f.controller.save();
  assert.equal(f.calls.length, 2);
  assert.equal(f.loads.length, 1);
  assert.equal(f.controller.getSnapshot().draft.content, 'Unknown content');
  await f.controller.retryWrite();
  assert.strictEqual(f.calls[2].command, original);
  assert.equal(f.calls[2].request.expectedActorId, 'actor-1');
  assert.equal(f.controller.getSnapshot().notice, 'accepted');
});

test('409 preserves draft until explicit latest GET plus capability refresh and new review', async () => {
  let once = true;
  const f = fixture({
    execute: async (command, request, calls, get, set) => {
      if (command.operation === 'update' && once) {
        once = false;
        set({ ...get(), version: 2, content: 'Remote changed content' });
        throw Object.assign(Error('revision_conflict'), { status: 409 });
      }
    },
  });
  await f.controller.loadPage();
  await f.controller.open('memory-1', 'edit');
  f.controller.setDraft({ title: 'My draft', content: 'My body' });
  await f.controller.save();
  const old = f.calls[1].command;
  assert.equal(f.controller.getSnapshot().phase, 'conflict');
  assert.equal(f.controller.getSnapshot().record.version, 1);
  await f.controller.reloadConflict();
  assert.equal(f.controller.getSnapshot().phase, 'reviewing');
  assert.equal(f.controller.getSnapshot().record.version, 1);
  assert.equal(f.controller.getSnapshot().latest.version, 2);
  assert.equal(f.controller.getSnapshot().draft.content, 'My body');
  await f.controller.save();
  assert.equal(f.calls.filter((call) => call.command.operation === 'update').length, 1);
  f.controller.adoptLatest();
  assert.equal(f.controller.getSnapshot().record.version, 2);
  assert.equal(f.controller.getSnapshot().draft.content, 'My body');
  await f.controller.save();
  const next = f.calls.at(-1).command;
  assert.equal(next.expectedRevision, 2);
  assert.notEqual(next.idempotencyKey, old.idempotencyKey);
});

test('403 keeps draft but disables writes; 401 and protocol scope drift clear all data', async () => {
  for (const error of [
    Object.assign(Error('forbidden'), { status: 403 }),
    Object.assign(Error('unauthorized'), { status: 401 }),
    Error('cloud_memory_scope_conflict'),
    Error('desktop_project_memories_operation_released'),
  ]) {
    const f = fixture({
      execute: async (command) => {
        if (command.operation === 'update') throw error;
      },
    });
    await f.controller.loadPage();
    await f.controller.open('memory-1', 'edit');
    f.controller.setDraft({ title: 'Draft', content: 'Body' });
    await f.controller.save();
    if (error.status === 403) {
      assert.equal(f.controller.getSnapshot().draft.content, 'Body');
      assert.equal(f.controller.getSnapshot().phase, 'conflict');
      await f.controller.save();
      assert.equal(f.calls.length, 2);
    } else {
      assert.equal(f.controller.getSnapshot().draft, null);
      assert.equal(f.controller.getSnapshot().list, null);
      assert.equal(f.controller.getSnapshot().error, 'contextChanged');
    }
  }
});

test('delete requires explicit confirmation and missing object after unknown is not success', async () => {
  let first = true;
  const f = fixture({
    execute: async (command) => {
      if (command.operation === 'delete' && first) {
        first = false;
        throw Object.assign(Error('response_lost'), { status: 502 });
      }
      if (command.operation === 'delete')
        throw Object.assign(Error('unavailable'), { status: 404 });
    },
  });
  await f.controller.loadPage();
  await f.controller.open('memory-1', 'delete');
  assert.equal(f.calls.length, 1);
  await f.controller.confirmDelete();
  assert.equal(f.calls[1].command.expectedRevision, 1);
  assert.equal(f.controller.getSnapshot().phase, 'uncertain');
  await f.controller.retryWrite();
  assert.strictEqual(f.calls[2].command, f.calls[1].command);
  assert.equal(f.controller.getSnapshot().notice, null);
  assert.equal(f.controller.getSnapshot().error, 'notFound');
});

test('late responses and pending retries are cleared on stop; StrictMode activation restores only a new load', async () => {
  let release;
  const f = fixture({
    execute: (command) =>
      command.operation === 'get' ? new Promise((resolve) => (release = resolve)) : undefined,
  });
  await f.controller.loadPage();
  const pending = f.controller.open('memory-1', 'edit');
  await new Promise((resolve) => setImmediate(resolve));
  f.controller.stop();
  release({ operation: 'get', result: memory });
  await pending;
  assert.equal(f.controller.getSnapshot().record, null);
  assert.equal(f.controller.canView(), false);
  f.controller.activate();
  await f.controller.loadPage();
  assert.equal(f.controller.getSnapshot().list.memories.length, 1);
  const unknown = fixture({
    execute: async (command) => {
      if (command.operation === 'create') throw Error('offline');
    },
  });
  await unknown.controller.loadPage();
  unknown.controller.create();
  unknown.controller.setDraft({ title: 'Draft', content: 'Body' });
  await unknown.controller.save();
  unknown.controller.stop();
  unknown.controller.activate();
  await unknown.controller.retryWrite();
  assert.equal(unknown.calls.length, 1);
  assert.equal(unknown.controller.getSnapshot().draft, null);
});

test('list scope revision mismatch clears content and count-free pagination uses hasMore', async () => {
  const drift = fixture({
    load: async () => ({
      scope,
      scopeRevision: 9,
      authority: 'cloud',
      availability: 'available',
      reasonCode: null,
      allowedActions: ['list'],
      memories: [memory],
      page: 1,
      pageSize: 50,
      total: 1,
    }),
  });
  await drift.controller.loadPage();
  assert.equal(drift.controller.getSnapshot().list, null);
  assert.equal(drift.controller.getSnapshot().error, 'contextChanged');
  const pages = fixture({
    load: async (current, request) => ({
      scope,
      scopeRevision: 7,
      authority: 'cloud',
      availability: 'available',
      reasonCode: null,
      allowedActions: ['list'],
      memories: [current],
      page: request.page,
      pageSize: 50,
      total: null,
      hasMore: request.page < 2,
    }),
  });
  await pages.controller.loadPage();
  await pages.controller.goToPage(2);
  await pages.controller.goToPage(3);
  assert.deepEqual(
    pages.loads.map((load) => load.page),
    [1, 2],
  );
  await pages.controller.goToPage(1);
  assert.equal(pages.loads.at(-1).page, 1);
  const deleted = fixture({
    load: async (current, request) => ({
      scope,
      scopeRevision: 7,
      authority: 'cloud',
      availability: 'available',
      reasonCode: null,
      allowedActions: ['list'],
      memories: [],
      page: request.page,
      pageSize: 50,
      total: 1,
    }),
  });
  await deleted.controller.loadPage(3);
  await deleted.controller.goToPage(2);
  assert.equal(deleted.loads.at(-1).page, 1);
});

test('an acknowledged mutation stays acknowledged when only its list refresh fails', async () => {
  const f = fixture({
    load: async (current, request, loads) => {
      if (loads.length > 1) throw Error('list_offline');
    },
  });
  await f.controller.loadPage();
  f.controller.create();
  f.controller.setDraft({ title: 'New', content: 'Body' });
  await f.controller.save();
  assert.equal(f.controller.getSnapshot().notice, 'accepted');
  assert.equal(f.controller.getSnapshot().phase, 'viewing');
  assert.equal(f.controller.getSnapshot().listState, 'error');
  await f.controller.retryWrite();
  assert.equal(f.calls.length, 1);
});

test('double save sends once and a late successful write cannot restore stopped context', async () => {
  let release;
  const f = fixture({
    execute: (command) =>
      command.operation === 'create' ? new Promise((resolve) => (release = resolve)) : undefined,
  });
  await f.controller.loadPage();
  assert.ok(Object.isFrozen(f.controller.getSnapshot().list.commandCapabilities.objects[0]));
  f.controller.create();
  f.controller.setDraft({ title: 'Draft', content: 'Late body' });
  const saving = f.controller.save();
  await new Promise((resolve) => setImmediate(resolve));
  await f.controller.save();
  assert.equal(f.calls.length, 1);
  f.controller.stop();
  assert.equal(f.calls[0].request.signal.aborted, true);
  release({ operation: 'create', result: { ...memory, id: 'new-memory' } });
  await saving;
  assert.equal(f.controller.getSnapshot().notice, null);
  assert.equal(f.controller.getSnapshot().list, null);
  assert.equal(f.controller.getSnapshot().draft, null);
});
