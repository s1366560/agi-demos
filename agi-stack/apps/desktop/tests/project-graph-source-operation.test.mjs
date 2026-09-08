import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync, readdirSync } from 'node:fs';
import { test } from 'node:test';
import { scope, config, episode, sourceSnapshot, json } from './projectGraphProvenanceFixtures.mjs';
const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/src';
const {
  createDesktopProjectGraphOperationsV2,
  createDesktopProjectGraphClientV2,
  withDesktopProjectGraphAuthorityOperationV2,
} = require(root + '/plugins/desktopProjectGraphAuthorityModuleV2.js');
const { createDesktopProjectGraphHttpAuthorityV2 } = require(
  root + '/plugins/desktopProjectGraphHttpProjectionV2.js',
);
const query = { episodeUuid: episode.uuid, expectedContextRevision: 23 };
function actions(events, result = sourceSnapshot()) {
  return {
    acquireServiceOperationLease: async (request) => {
      events.push(['acquire', request]);
      return {
        status: 'accepted',
        digest: 'published',
        useService: (use) =>
          use({
            bindOperation: () => ({
              load: async (signal, received) => {
                events.push(['load', received]);
                return result;
              },
            }),
          }),
        release: async () => {
          events.push(['release']);
        },
      };
    },
  };
}

test('source queries freeze their UUID/context and retain the project service lease through validation', async () => {
  const events = [];
  const operations = createDesktopProjectGraphOperationsV2(() => actions(events));
  const client = createDesktopProjectGraphClientV2(operations, config);
  const mutable = { ...query };
  const pending = client.loadSource(scope, mutable);
  mutable.episodeUuid = 'changed';
  const result = await pending;
  assert.deepEqual(
    events.map(([kind]) => kind),
    ['acquire', 'load', 'release'],
  );
  assert.deepEqual(events[0][1].scope, {
    kind: 'project',
    tenant_id: scope.tenantId,
    project_id: scope.projectId,
  });
  assert.deepEqual(events[1][1], query);
  assert(Object.isFrozen(events[1][1]));
  assert(Object.isFrozen(result.nodes[0]));
  assert.equal(result.nodes[0].uuid, episode.uuid);
  let escaped;
  await withDesktopProjectGraphAuthorityOperationV2(
    actions([]),
    { config, scope, sourceQuery: query },
    (authority) => {
      escaped = authority;
    },
  );
  await assert.rejects(
    escaped.load(undefined, query),
    (error) => error.code === 'desktop_project_graph_operation_released',
  );
});

test('arbitrary neighbor expansion, malformed scopes and foreign source results fail closed', async () => {
  const events = [];
  const operations = createDesktopProjectGraphOperationsV2(() => actions(events));
  for (const sourceQuery of [
    { ...query, includeNeighbors: true },
    { ...query, episodeUuid: '' },
    { ...query, expectedContextRevision: -1 },
    { ...query, node_uuids: ['other'] },
  ])
    await assert.rejects(
      async () => operations.loadProjectGraph({ config, scope, sourceQuery }),
      (error) => error.code === 'desktop_project_graph_operation_input_invalid',
    );
  assert.deepEqual(events, []);
  for (const result of [
    sourceSnapshot({ ...episode, uuid: 'other' }),
    sourceSnapshot({ ...episode, type: 'Entity' }),
    sourceSnapshot({ ...episode, project_id: 'other' }),
    { ...sourceSnapshot(), scopeRevision: 24 },
    { ...sourceSnapshot(), nodes: [episode, { ...episode, id: 'another-element' }] },
  ])
    await assert.rejects(
      createDesktopProjectGraphOperationsV2(() => actions([], result)).loadProjectGraph({
        config,
        scope,
        sourceQuery: query,
      }),
    );
  const missing = await createDesktopProjectGraphOperationsV2(() =>
    actions([], sourceSnapshot(null)),
  ).loadProjectGraph({ config, scope, sourceQuery: query });
  assert.deepEqual(missing.nodes, []);
});

test('HTTP source lookup is a scoped UUID query with revision checks before and after the response', async () => {
  const previous = globalThis.fetch;
  try {
    for (const drift of ['none', 'before', 'after']) {
      const calls = [];
      let contexts = 0;
      globalThis.fetch = async (url, init) => {
        const path = new URL(url).pathname;
        calls.push({ path, init });
        if (path === '/api/v1/workspace-context') {
          contexts += 1;
          const revision = drift === 'before' || (drift === 'after' && contexts === 2) ? 24 : 23;
          return json({
            context: { tenant_id: scope.tenantId, project_id: scope.projectId, revision },
          });
        }
        assert.equal(path, '/api/v1/graph/memory/graph/subgraph');
        assert.equal(init.method, 'POST');
        assert.deepEqual(JSON.parse(init.body), {
          node_uuids: [episode.uuid],
          include_neighbors: false,
          limit: 1,
          tenant_id: scope.tenantId,
          project_id: scope.projectId,
        });
        return json({ elements: { nodes: [{ data: episode }], edges: [] } });
      };
      const work = createDesktopProjectGraphHttpAuthorityV2(config, scope).load(undefined, query);
      if (drift === 'none') {
        const result = await work;
        assert.equal(result.nodes[0].content, episode.content);
      } else await assert.rejects(work, (error) => error.status === 409);
      assert.equal(
        calls.filter((call) => call.path.endsWith('/subgraph')).length,
        drift === 'before' ? 0 : 1,
      );
    }
    let calls = 0;
    globalThis.fetch = async () => {
      calls += 1;
      throw Error('not allowed');
    };
    await assert.rejects(
      createDesktopProjectGraphHttpAuthorityV2(
        { ...config, mode: 'local' },
        { ...scope, authority: 'local' },
      ).load(undefined, query),
      (error) => error.status === 501,
    );
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = previous;
  }
});

test('the real renderer Loader routes source inspection through the published Graph authority', async () => {
  const { LoaderV2, createDesktopRendererDefinitionsV2 } = require('@agistack/plugin-runtime');
  const { acquireDesktopRendererServiceOperationLeaseV2 } = require(
    root + '/plugins/desktopRendererServiceOperationLeaseV2.js',
  );
  const modules = readdirSync(root + '/plugins')
    .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
    .flatMap((name) =>
      Object.values(require(root + '/plugins/' + name)).filter(
        (value) => value?.moduleRef && typeof value.apply === 'function',
      ),
    );
  const profile = JSON.parse(
    readFileSync(
      new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
      'utf8',
    ),
  );
  const loader = new LoaderV2(
    [...createDesktopRendererDefinitionsV2(), ...modules],
    'desktop-renderer',
  );
  const generation = await loader.stage(profile);
  let released = 0;
  const operations = createDesktopProjectGraphOperationsV2(() => ({
    acquireServiceOperationLease: (request) =>
      acquireDesktopRendererServiceOperationLeaseV2(generation, request, () => ({
        release: async () => {
          released += 1;
        },
      })),
  }));
  const previous = globalThis.fetch;
  globalThis.fetch = async (url, init) =>
    new URL(url).pathname === '/api/v1/workspace-context'
      ? json({ context: { tenant_id: scope.tenantId, project_id: scope.projectId, revision: 23 } })
      : (assert.equal(new URL(url).pathname, '/api/v1/graph/memory/graph/subgraph'),
        assert.equal(JSON.parse(init.body).node_uuids[0], episode.uuid),
        json({ elements: { nodes: [{ data: episode }], edges: [] } }));
  try {
    const result = await createDesktopProjectGraphClientV2(operations, config).loadSource(
      scope,
      query,
    );
    assert.equal(result.nodes[0].uuid, episode.uuid);
    assert.equal(released, 1);
  } finally {
    globalThis.fetch = previous;
    await generation.dispose();
  }
});
