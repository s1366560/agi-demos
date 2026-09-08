import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import {
  scope,
  episode,
  entity,
  other,
  community,
  mention,
  relation,
  membership,
  snapshot,
  sourceSnapshot,
  deferred,
} from './projectGraphProvenanceFixtures.mjs';
const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/src/features/project-knowledge';
const { createProjectGraphController } = require(root + '/projectGraphController.js');
const { projectGraphAdjacentEdges, projectGraphSourceUuids } = require(
  root + '/projectGraphNavigation.js',
);
function fixture(overrides = {}) {
  const calls = [];
  const client = {
    load: async (scope) => snapshot(scope),
    loadSource: async (scope, query, options) => {
      calls.push({ scope, query, options });
      return sourceSnapshot(query.episodeUuid === episode.uuid ? episode : null);
    },
    ...overrides,
  };
  return {
    controller: createProjectGraphController({ authority: 'cloud', client, initialScope: scope }),
    calls,
  };
}
test('graph retains directed edges and distinguishes equal names by element IDs and source UUIDs', async () => {
  const { controller, calls } = fixture();
  await controller.load(scope);
  assert.deepEqual(controller.getSnapshot().edges, [mention, relation, membership]);
  controller.selectNode(entity.id);
  assert.deepEqual(
    projectGraphAdjacentEdges(controller.getSnapshot(), entity.id).map((e) => e.id),
    [mention.id, relation.id, membership.id],
  );
  assert.deepEqual(
    projectGraphSourceUuids(controller.getSnapshot(), controller.getSnapshot().selection),
    [episode.uuid],
  );
  controller.selectNode(other.id);
  assert.deepEqual(
    projectGraphSourceUuids(controller.getSnapshot(), controller.getSnapshot().selection),
    [],
  );
  controller.selectNode(community.id);
  assert.deepEqual(
    projectGraphSourceUuids(controller.getSnapshot(), controller.getSnapshot().selection),
    [],
  );
  controller.selectEdge(membership.id);
  assert.deepEqual(
    projectGraphSourceUuids(controller.getSnapshot(), controller.getSnapshot().selection),
    [],
  );
  controller.selectEdge(relation.id);
  assert.deepEqual(
    projectGraphSourceUuids(controller.getSnapshot(), controller.getSnapshot().selection),
    [episode.uuid, 'missing-episode'],
  );
  await controller.openSource('Same name');
  assert.equal(calls.length, 0);
  await controller.openSource(episode.uuid);
  assert.deepEqual(calls[0].query, { episodeUuid: episode.uuid, expectedContextRevision: 23 });
  assert.equal(controller.getSnapshot().source.content, episode.content);
  await controller.openSource('missing-episode');
  assert.equal(controller.getSnapshot().sourceState, 'ready');
  assert.equal(controller.getSnapshot().source, null);
});
test('changing selection or project and stopping discard late source content', async () => {
  for (const change of ['selection', 'scope', 'stop']) {
    const pending = deferred();
    const { controller } = fixture({ loadSource: () => pending.promise });
    await controller.load(scope);
    controller.selectEdge(relation.id);
    const request = controller.openSource(episode.uuid);
    if (change === 'selection') controller.selectNode(other.id);
    if (change === 'scope') await controller.load({ ...scope, projectId: 'project-2' });
    if (change === 'stop') controller.stop();
    pending.resolve(sourceSnapshot());
    await request;
    assert.equal(controller.getSnapshot().source, null);
  }
});
test('scope or permission failures clear graph state; incomplete or foreign source responses never publish', async () => {
  for (const status of [401, 403, 409]) {
    const { controller } = fixture({
      loadSource: async () => {
        throw Object.assign(new Error('rejected'), { status });
      },
    });
    await controller.load(scope);
    controller.selectEdge(relation.id);
    await controller.openSource(episode.uuid);
    assert.equal(controller.getSnapshot().source, null);
    assert.deepEqual(controller.getSnapshot().nodes, []);
    assert.deepEqual(controller.getSnapshot().allowedActions, []);
  }
  for (const value of [
    sourceSnapshot(entity),
    sourceSnapshot({ ...episode, project_id: 'foreign' }),
    { ...sourceSnapshot(), scopeRevision: 24 },
    { ...sourceSnapshot(), nodes: [episode, episode] },
  ]) {
    const { controller } = fixture({ loadSource: async () => value });
    await controller.load(scope);
    controller.selectEdge(relation.id);
    await controller.openSource(episode.uuid);
    assert.equal(controller.getSnapshot().source, null);
    assert.deepEqual(controller.getSnapshot().nodes, []);
  }
});
test('local graph remains unavailable and missing view permission cannot inspect or resolve sources', async () => {
  let calls = 0;
  const local = { ...scope, authority: 'local' };
  const controller = createProjectGraphController({
    authority: 'local',
    initialScope: local,
    client: {
      load: async () => {
        calls += 1;
      },
      loadSource: async () => {
        calls += 1;
      },
    },
  });
  await controller.load(local);
  controller.selectNode(episode.id);
  await controller.openSource(episode.uuid);
  assert.equal(calls, 0);
  assert.equal(controller.getSnapshot().state, 'unavailable');
  const denied = fixture({ load: async () => snapshot(scope, { allowedActions: [] }) });
  await denied.controller.load(scope);
  denied.controller.selectNode(episode.id);
  await denied.controller.openSource(episode.uuid);
  assert.equal(denied.controller.getSnapshot().selection, null);
  assert.equal(denied.calls.length, 0);
});
