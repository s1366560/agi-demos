import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { definitions: d } = require(
  `${process.env.AGISTACK_KNOWLEDGE_CONNECTION_SCHEMA_DIST ?? '/tmp/agistack-project-knowledge-test-dist'}/src/features/project-knowledge/nativeKnowledgeConnectionSchemaGenerated.js`,
);
const scope = {
  tenant_id: 'local-tenant', project_id: 'local-project', context_revision: 1,
  profile_id: 'local-profile', generation: 1, digest: 'ab'.repeat(32),
};
const generation = {
  contract_version: '1.0.0',
  descriptor: { profile_id: 'cloud-profile', generation: 81, digest: 'cd'.repeat(32) },
};
const connection = {
  connection_revision: 'ef'.repeat(32), authority: 'https://cloud.example/api/v1',
  actor_id: 'remote-actor',
};
const target = {
  scope, expected_connection_revision: connection.connection_revision,
  tenant_id: 'remote-tenant', project_id: 'remote-project', expected_generation: generation,
};

test('generated connection schemas reject authority injection and omitted observations', () => {
  assert.equal(d.NativeKnowledgeSyncTargetRequest(target), true);
  for (const key of Object.keys(target)) {
    const missing = structuredClone(target);
    delete missing[key];
    assert.equal(d.NativeKnowledgeSyncTargetRequest(missing), false);
  }
  for (const key of ['credential', 'authority', 'actor_id', 'base_url']) {
    assert.equal(d.NativeKnowledgeSyncTargetRequest({ ...target, [key]: 'forged' }), false);
  }
  assert.equal(d.NativeKnowledgeSyncConnectionResult({ connection: null }), true);
  assert.equal(d.NativeKnowledgeSyncConnectionResult({ connection }), true);
});

test('generated checks preserve integer, digest and nested closed-object conditions', () => {
  for (const value of [0, -1, 1.5, '81', true, Number.MAX_SAFE_INTEGER + 1]) {
    const invalid = structuredClone(target);
    invalid.expected_generation.descriptor.generation = value;
    assert.equal(d.NativeKnowledgeSyncTargetRequest(invalid), false);
  }
  for (const value of ['sha256:' + 'ab'.repeat(32), 'AB'.repeat(32), 'a'.repeat(63)]) {
    const invalid = structuredClone(target);
    invalid.expected_generation.descriptor.digest = value;
    assert.equal(d.NativeKnowledgeSyncTargetRequest(invalid), false);
  }
  const extra = structuredClone(target);
  extra.expected_generation.descriptor.credential = 'forged';
  assert.equal(d.NativeKnowledgeSyncTargetRequest(extra), false);
});

test('generated string and list bounds use Unicode code points and declared catalog limits', () => {
  assert.equal(d.NativeKnowledgeSyncTenant({ id: 'a'.repeat(512), name: '界'.repeat(4096) }), true);
  assert.equal(d.NativeKnowledgeSyncTenant({ id: 'a'.repeat(513), name: 'ok' }), false);
  assert.equal(d.NativeKnowledgeSyncTenant({ id: 'id', name: '𠮷'.repeat(4097) }), false);
  const item = { id: 'tenant', name: 'Tenant' };
  assert.equal(d.NativeKnowledgeSyncTenantsResult({ connection, items: Array(10000).fill(item) }), true);
  assert.equal(d.NativeKnowledgeSyncTenantsResult({ connection, items: Array(10001).fill(item) }), false);
});
