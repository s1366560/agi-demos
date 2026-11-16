import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const {
  createConversationApprovalSync,
  approvalMode,
  approvalPreset,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/conversationApprovalSyncModel.js');
const result = (approval_mode) => ({ agent_config: { approval_mode } });
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};

test('canonical modes map exactly and absent or unknown modes fail closed', () => {
  for (const [preset, mode] of [
    ['default', 'ask'],
    ['relaxed', 'auto_edit'],
    ['full', 'full_access'],
  ]) {
    assert.equal(approvalMode(preset), mode);
    assert.equal(approvalPreset(result(mode)), preset);
  }
  assert.equal(approvalPreset({ agent_config: {} }), 'default');
  assert.equal(approvalPreset(result('invalid')), 'default');
});

test('a late read cannot replace a saved mode, and concurrent saves are suppressed', async () => {
  const read = deferred(),
    update = deferred(),
    states = [];
  let writes = 0;
  const sync = createConversationApprovalSync({
    read: () => read.promise,
    update: () => {
      writes++;
      return update.promise;
    },
    publish: (state) => states.push(state),
    onError: () => assert.fail('unexpected error'),
  });
  const reading = sync.refresh();
  const saving = sync.save('full');
  assert.deepEqual(states.at(-1), { preset: 'default', pending: true });
  await sync.save('relaxed');
  assert.equal(writes, 1);
  update.resolve(result('full_access'));
  await saving;
  read.resolve(result('ask'));
  await reading;
  assert.deepEqual(states.at(-1), { preset: 'full', pending: false });
});

test('scope disposal prevents reads, writes and errors reaching a later scope', async () => {
  const pending = deferred(),
    states = [];
  const sync = createConversationApprovalSync({
    read: () => pending.promise,
    update: () => pending.promise,
    publish: (state) => states.push(state),
    onError: () => assert.fail('stale error'),
  });
  const reading = sync.refresh();
  const saving = sync.save('full');
  const count = states.length;
  sync.dispose();
  pending.reject(new Error('old scope'));
  await Promise.all([reading, saving]);
  assert.equal(states.length, count);
});

test('failed mutations and background refresh revoke automatic approvals', async () => {
  const states = [],
    errors = [];
  let fail = false;
  const sync = createConversationApprovalSync({
    read: async () => {
      if (fail) throw new Error('offline');
      return result('full_access');
    },
    update: async () => {
      throw new Error('denied');
    },
    publish: (state) => states.push(state),
    onError: (error) => errors.push(error),
  });
  await sync.refresh();
  assert.equal(states.at(-1).preset, 'full');
  await sync.save('relaxed');
  assert.deepEqual(states.at(-1), { preset: 'default', pending: false });
  await sync.refresh();
  fail = true;
  await sync.refresh();
  assert.deepEqual(states.at(-1), { preset: 'default', pending: false });
  assert.equal(errors.length, 2);
});
