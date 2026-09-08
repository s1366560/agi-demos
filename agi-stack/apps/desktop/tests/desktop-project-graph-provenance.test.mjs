import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/src';
const { createDesktopProjectGraphHttpAuthorityV2 } = require(
  root + '/plugins/desktopProjectGraphHttpProjectionV2.js',
);
const { requireDesktopProjectGraphSnapshotV2 } = require(
  root + '/plugins/desktopProjectGraphOperationContractV2.js',
);
const scope = { authority: 'cloud', tenantId: 'tenant-1', projectId: 'project-1' };
const config = {
  apiBaseUrl: 'https://cloud.test',
  deviceAuthorizationBaseUrl: 'https://cloud.test',
  apiKey: 'test-session',
  localApiToken: '',
  tenantId: scope.tenantId,
  projectId: scope.projectId,
  workspaceId: '',
  workspaceRoot: '',
  mode: 'cloud',
};
const episode = {
  id: 'element-episode',
  label: 'Source',
  type: 'Episodic',
  name: 'Same name',
  uuid: 'episode-uuid',
  content: 'Captured content',
  source: 'text',
  source_description: 'document',
  memory_id: 'memory-uuid',
  created_at: '2026-09-08T01:00:00Z',
  valid_at: '2026-09-07T01:00:00Z',
  tenant_id: scope.tenantId,
  project_id: scope.projectId,
};
const entity = {
  id: 'element-entity',
  label: 'Entity',
  type: 'Entity',
  name: 'Same name',
  uuid: 'entity-uuid',
  entity_type: 'Person',
};
const edge = {
  id: 'element-edge',
  source: episode.id,
  target: entity.id,
  label: 'MENTIONS',
  uuid: 'edge-uuid',
  weight: 0.8,
  fact: 'Observed fact',
  episodes: [episode.uuid],
  relationship_type: 'KNOWS',
  created_at: episode.created_at,
  valid_at: episode.valid_at,
  invalid_at: null,
  expired_at: null,
};
const wire = () => ({
  elements: { nodes: [{ data: episode }, { data: entity }], edges: [{ data: edge }] },
});
const json = (value) =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
async function read(payload = wire()) {
  const previous = globalThis.fetch;
  globalThis.fetch = async (url) =>
    new URL(url).pathname === '/api/v1/workspace-context'
      ? json({ context: { tenant_id: scope.tenantId, project_id: scope.projectId, revision: 12 } })
      : json(payload);
  try {
    return await createDesktopProjectGraphHttpAuthorityV2(config, scope).load();
  } finally {
    globalThis.fetch = previous;
  }
}
test('graph HTTP and service contracts preserve actual source UUIDs, captured content and directed edge evidence', async () => {
  const snapshot = await read();
  assert.equal(snapshot.nodes[0].uuid, episode.uuid);
  assert.equal(snapshot.nodes[0].content, episode.content);
  assert.equal(snapshot.nodes[0].memory_id, episode.memory_id);
  assert.equal(snapshot.nodes[1].entity_type, entity.entity_type);
  assert.equal(snapshot.edges[0].source, episode.id);
  assert.equal(snapshot.edges[0].target, entity.id);
  assert.deepEqual(snapshot.edges[0].episodes, [episode.uuid]);
  assert.equal(snapshot.edges[0].fact, edge.fact);
  const accepted = requireDesktopProjectGraphSnapshotV2(snapshot, scope);
  assert.deepEqual(accepted, snapshot);
  assert(Object.isFrozen(accepted.edges[0].episodes));
  assert.equal('memory_revision' in accepted.nodes[0], false);
  assert.equal('source_url' in accepted.nodes[0], false);
});
test('optional provenance stays absent for legacy nodes and malformed or foreign provenance fails closed', async () => {
  const legacy = await read({
    elements: {
      nodes: [{ data: { id: 'node', label: 'Node', type: 'Entity', name: 'Node' } }],
      edges: [],
    },
  });
  assert.equal('uuid' in legacy.nodes[0], false);
  requireDesktopProjectGraphSnapshotV2(legacy, scope);
  for (const field of [
    { uuid: 5 },
    { memory_id: {} },
    { content: [] },
    { tenant_id: 'other' },
    { project_id: 'other' },
  ]) {
    const payload = wire();
    payload.elements.nodes[0].data = { ...episode, ...field };
    await assert.rejects(read(payload));
  }
  for (const field of [
    { episodes: ['episode-uuid', 5] },
    { uuid: [] },
    { fact: {} },
    { valid_at: 9 },
  ]) {
    const payload = wire();
    payload.elements.edges[0].data = { ...edge, ...field };
    await assert.rejects(read(payload));
  }
  const accepted = await read();
  assert.throws(() =>
    requireDesktopProjectGraphSnapshotV2(
      { ...accepted, nodes: [{ ...accepted.nodes[0], project_id: 'foreign' }, accepted.nodes[1]] },
      scope,
    ),
  );
  for (const field of [{ episodes: [5] }, { source_url: 'https://invented.test' }])
    assert.throws(() =>
      requireDesktopProjectGraphSnapshotV2(
        { ...accepted, edges: [{ ...accepted.edges[0], ...field }] },
        scope,
      ),
    );
});
