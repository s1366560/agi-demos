import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { scope, deferred } from './projectGraphProvenanceFixtures.mjs';
const require = createRequire(import.meta.url);
const {
  createProjectGraphMemoryReader,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-knowledge/projectGraphMemoryReader.js');
const authority = {
  scope,
  actorId: 'actor',
  sessionId: 'session',
  contextRevision: 23,
  generationDigest: 'generation',
  available: true,
  allowedActions: ['view'],
};
const memory = {
  id: 'memory-1',
  projectId: scope.projectId,
  title: 'Current memory',
  content: 'Changed after capture',
  version: 9,
};
function fixture(overrides = {}) {
  const calls = [];
  const binding = {
    authority,
    client: {
      execute: async (...args) => {
        calls.push(args);
        return { operation: 'get', result: memory };
      },
    },
    ...overrides,
  };
  return {
    calls,
    reader: createProjectGraphMemoryReader({
      binding,
      scope,
      contextRevision: 23,
      memoryId: 'memory-1',
    }),
  };
}
test('current memory is an explicit read with its own revision and no write capability', async () => {
  const { reader, calls } = fixture();
  assert.equal(calls.length, 0);
  await reader.load();
  assert.deepEqual(calls[0][1], { operation: 'get', id: 'memory-1' });
  assert.equal(calls[0][2].expectedActorId, 'actor');
  assert.equal(calls[0][2].expectedContextRevision, 23);
  assert.equal(reader.getSnapshot().memory.content, 'Changed after capture');
  assert.equal(reader.getSnapshot().memory.version, 9);
  assert.equal('update' in reader, false);
  assert.equal('delete' in reader, false);
});
test('current memory uses current read permissions and discards late or unavailable results', async () => {
  for (const change of [
    { available: false },
    { allowedActions: ['list'] },
    { contextRevision: 24 },
    { scope: { ...scope, projectId: 'other' } },
  ]) {
    const { reader, calls } = fixture({ authority: { ...authority, ...change } });
    await reader.load();
    assert.equal(calls.length, 0);
    assert.equal(reader.getSnapshot().state, 'unavailable');
  }
  const pending = deferred();
  const { reader } = fixture({ client: { execute: () => pending.promise } });
  const request = reader.load();
  reader.stop();
  pending.resolve({ operation: 'get', result: memory });
  await request;
  assert.equal(reader.getSnapshot().memory, null);
  for (const status of [401, 403, 404]) {
    const { reader } = fixture({
      client: {
        execute: async () => {
          throw Object.assign(new Error('unavailable'), { status });
        },
      },
    });
    await reader.load();
    assert.equal(reader.getSnapshot().state, 'unavailable');
    assert.equal(reader.getSnapshot().memory, null);
  }
});
