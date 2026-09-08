import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { parseCloudMemoryCapabilities } = require(
  (process.env.CLOUD_MEMORY_CLIENT_DIST ?? '/tmp/agistack-desktop-test-dist') +
    '/src/features/project-knowledge/cloudMemoryCapabilities.js',
);
const scope = { authority: 'cloud', tenantId: 'tenant', projectId: 'project' };
const rows = [{ id: 'memory', version: 3 }];
const wire = () => ({
  protocol_version: 1,
  tenant_id: 'tenant',
  project_id: 'project',
  actor_id: 'actor',
  allowed_actions: ['create'],
  objects: [{ memory_id: 'memory', revision: 3, allowed_actions: ['update'] }],
});

test('cloud capabilities bind actor, scope and exact page revision immutably', () => {
  const input = wire();
  const result = parseCloudMemoryCapabilities(input, scope, rows, 'actor');
  assert.equal(result.actorId, 'actor');
  assert.deepEqual(result.allowedActions, ['create']);
  assert.deepEqual(result.objects, [
    { memoryId: 'memory', revision: 3, allowedActions: ['update'] },
  ]);
  input.objects[0].allowed_actions.push('delete');
  assert.deepEqual(result.objects[0].allowedActions, ['update']);
  assert.ok(Object.isFrozen(result.objects[0].allowedActions));
});

for (const value of [undefined, null, {}, { ...wire(), protocol_version: 2 }]) {
  test(`missing or unsupported capability data disables writes: ${JSON.stringify(value)}`, () => {
    assert.equal(parseCloudMemoryCapabilities(value, scope, rows, 'actor'), null);
  });
}
for (const change of [
  {
    objects: [{ memory_id: 'other', revision: 3, allowed_actions: ['update'] }],
  },
  {
    objects: [{ memory_id: 'memory', revision: 2, allowed_actions: ['update'] }],
  },
  {
    objects: [{ memory_id: 'memory', revision: 3, allowed_actions: ['share'] }],
  },
  { objects: [wire().objects[0], wire().objects[0]] },
  { allowed_actions: ['create', 'create'] },
  {
    objects: [{ ...wire().objects[0], allowed_actions: ['update', 'update'] }],
  },
  { extra: true },
]) {
  test(`malformed independent capability data disables writes: ${JSON.stringify(change)}`, () => {
    assert.equal(
      parseCloudMemoryCapabilities({ ...wire(), ...change }, scope, rows, 'actor'),
      null,
    );
  });
}
for (const change of [{ tenant_id: 'other' }, { project_id: 'other' }, { actor_id: 'other' }]) {
  test(`identity or scope conflict rejects the response: ${JSON.stringify(change)}`, () => {
    assert.throws(
      () => parseCloudMemoryCapabilities({ ...wire(), ...change }, scope, rows, 'actor'),
      /cloud_memory_capability_scope_conflict/,
    );
  });
}
