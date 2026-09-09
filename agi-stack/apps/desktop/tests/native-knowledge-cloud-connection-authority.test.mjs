import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { pullContext } from './nativeKnowledgeFixtures.mjs';
import { readFileSync, readdirSync } from 'node:fs';
const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/src';
const {
  createDesktopProjectMemoriesOperationsV2,
  createDesktopNativeKnowledgeConnectionClientV2,
  withDesktopProjectMemoriesAuthorityOperationV2,
} = require(root + '/plugins/desktopProjectMemoriesAuthorityModuleV2.js');
const { createDesktopNativeKnowledgeConnectionHttpV2 } = require(
  root + '/plugins/desktopNativeKnowledgeConnectionHttpV2.js',
);
const scope = {
  tenant_id: 'local-tenant',
  project_id: 'local-project',
  context_revision: 7,
  profile_id: 'native-profile',
  generation: 4,
  digest: 'a'.repeat(64),
};
const projectScope = {
  authority: 'local',
  tenantId: scope.tenant_id,
  projectId: scope.project_id,
};
const config = {
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://cloud.test',
  apiKey: 'local-identity',
  localApiToken: 'local-launch',
  tenantId: scope.tenant_id,
  projectId: scope.project_id,
  workspaceId: '',
  workspaceRoot: '',
  mode: 'local',
};
const connection = {
  connection_revision: 'b'.repeat(64),
  authority: 'https://cloud.example.test',
  actor_id: 'remote-actor',
};
const generation = {
  contract_version: '1.0.0',
  descriptor: {
    profile_id: 'cloud-profile',
    generation: 81,
    digest: 'c'.repeat(64),
  },
};
const enrollment = {
  contract_version: '1.0.0',
  tenant_id: 'remote-tenant',
  project_id: 'remote-project',
  actor_id: 'remote-actor',
  enabled: true,
  can_enroll: true,
  bootstrap_count: 0,
  next_cursor: 0,
  replayed: false,
  generation,
};
const target = {
  expected_connection_revision: connection.connection_revision,
  tenant_id: 'remote-tenant',
  project_id: 'remote-project',
  expected_generation: generation,
};
const envelope = (result) => ({ contract_version: '1.0.0', scope, result });
const status = {
  replica_id: '00000000-0000-4000-8000-000000000001',
  pending_changes: 0,
  pending_graph_changes: 0,
  link: {
    remote_tenant_id: 'remote-tenant',
    remote_project_id: 'remote-project',
    remote_actor_id: 'remote-actor',
  },
};
const cases = [
  [{ operation: 'connection' }, { connection }],
  [
    {
      operation: 'tenants',
      expected_connection_revision: connection.connection_revision,
    },
    { connection, items: [{ id: 'remote-tenant', name: 'Team' }] },
  ],
  [
    {
      operation: 'projects',
      expected_connection_revision: connection.connection_revision,
      tenant_id: 'remote-tenant',
    },
    {
      connection,
      tenant_id: 'remote-tenant',
      items: [{ id: 'remote-project', tenant_id: 'remote-tenant', name: 'Project' }],
    },
  ],
  [
    {
      operation: 'enrollment',
      expected_connection_revision: connection.connection_revision,
      tenant_id: 'remote-tenant',
      project_id: 'remote-project',
    },
    { connection, enrollment },
  ],
  [
    { operation: 'enroll', ...target },
    { connection, enrollment },
  ],
  [
    { operation: 'bind', ...target },
    { connection, enrollment, association_state: 'verified', status },
  ],
];
function actions(events, executeConnection, digest = scope.digest) {
  return {
    acquireServiceOperationLease: async (request) => {
      events.push(['acquire', request]);
      return {
        status: 'accepted',
        digest,
        useService: (use) =>
          use({
            bindOperation: () => ({
              load: async () => {
                throw Error('unexpected');
              },
              executeSync: async () => {
                throw Error('unexpected');
              },
              executeConnection,
            }),
          }),
        release: async () => {
          events.push(['release']);
        },
      };
    },
  };
}
const json = (body) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });

test('all six connection RPCs use the local authority and exact observed fields', async () => {
  const originalFetch = globalThis.fetch;
  try {
    for (const [command, result] of cases) {
      const requests = [];
      globalThis.fetch = async (url, init) => {
        requests.push({ url, init });
        return json(
          requests.length === 1 ? { contract_version: '1.0.0', scope } : envelope(result),
        );
      };
      const client = createDesktopNativeKnowledgeConnectionHttpV2(config, projectScope);
      const response = await client.executeConnection(command, {
        expectedScope: scope,
      });
      assert.deepEqual(response, envelope(result));
      assert.equal(requests.length, 2);
      assert.equal(new URL(requests[1].url).origin, config.apiBaseUrl);
      assert.equal(
        new URL(requests[1].url).pathname,
        `/api/v1/knowledge/sync-${command.operation}`,
      );
      const { operation, ...fields } = command;
      assert.deepEqual(JSON.parse(requests[1].init.body), { scope, ...fields });
      assert.equal(JSON.stringify(requests).includes('cloud_bearer'), false);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('connection commands retain the project service lease and immutable inputs', async () => {
  for (const [command, result] of cases) {
    const events = [];
    const client = createDesktopNativeKnowledgeConnectionClientV2(
      createDesktopProjectMemoriesOperationsV2(() =>
        actions(events, async (received) => {
          assert.deepEqual(received, command);
          events.push(['execute']);
          return envelope(result);
        }),
      ),
      config,
    );
    const response = await client.execute(projectScope, command, {
      expectedScope: scope,
    });
    assert(Object.isFrozen(response));
    assert(Object.isFrozen(response.result));
    assert.deepEqual(
      events.map(([event]) => event),
      ['acquire', 'execute', 'release'],
    );
    assert.deepEqual(events[0][1].scope, {
      kind: 'project',
      tenant_id: scope.tenant_id,
      project_id: scope.project_id,
    });
  }
});

test('untrusted extra credentials and missing generation fail before lease admission', async () => {
  const events = [];
  const client = createDesktopNativeKnowledgeConnectionClientV2(
    createDesktopProjectMemoriesOperationsV2(() =>
      actions(events, async () => envelope({ connection })),
    ),
    config,
  );
  for (const command of [
    { operation: 'connection', actor_id: 'injected' },
    { operation: 'connection', credential: 'injected' },
    {
      operation: 'bind',
      expected_connection_revision: connection.connection_revision,
      tenant_id: 't',
      project_id: 'p',
    },
    { operation: 'tenants', expected_connection_revision: 'invalid' },
  ])
    await assert.rejects(
      client.execute(projectScope, command, { expectedScope: scope }),
      /native_knowledge_cloud_connection_invalid/u,
    );
  assert.deepEqual(events, []);
});

test('scope, connection, cloud generation and selected actor mismatches are rejected', async () => {
  const [command, validResult] = cases.at(-1);
  for (const mutated of [
    { ...envelope(validResult), scope: { ...scope, generation: 5 } },
    envelope({
      ...validResult,
      connection: { ...connection, connection_revision: 'd'.repeat(64) },
    }),
    envelope({
      ...validResult,
      enrollment: { ...enrollment, actor_id: 'wrong' },
    }),
    envelope({
      ...validResult,
      enrollment: {
        ...enrollment,
        generation: {
          ...generation,
          descriptor: { ...generation.descriptor, generation: 82 },
        },
      },
    }),
    envelope({
      ...validResult,
      status: { ...status, link: { ...status.link, remote_actor_id: 'wrong' } },
    }),
  ]) {
    const events = [];
    const client = createDesktopNativeKnowledgeConnectionClientV2(
      createDesktopProjectMemoriesOperationsV2(() => actions(events, async () => mutated)),
      config,
    );
    await assert.rejects(client.execute(projectScope, command, { expectedScope: scope }));
    assert.equal(events.at(-1)[0], 'release');
  }
});

test('a retired generation and retained connection authority cannot execute', async () => {
  let calls = 0;
  const events = [];
  const execute = async () => {
    calls += 1;
    return envelope({ connection });
  };
  const client = createDesktopNativeKnowledgeConnectionClientV2(
    createDesktopProjectMemoriesOperationsV2(() => actions(events, execute, 'd'.repeat(64))),
    config,
  );
  await assert.rejects(
    client.execute(projectScope, { operation: 'connection' }, { expectedScope: scope }),
    /knowledge_generation_mismatch/u,
  );
  assert.equal(calls, 0);
  let retained;
  await withDesktopProjectMemoriesAuthorityOperationV2(
    actions(events, execute),
    {
      kind: 'connection',
      config,
      scope: projectScope,
      command: { operation: 'connection' },
      expectedScope: scope,
    },
    (authority) => {
      retained = authority;
    },
  );
  await assert.rejects(
    retained.executeConnection({ operation: 'connection' }, { expectedScope: scope }),
    (error) => error.code === 'desktop_project_memories_operation_released',
  );
  assert.equal(calls, 0);
});

test('the published native QA snapshot binds initial sync and conflict reads through the real renderer Loader', async () => {
  const { LoaderV2, createDesktopRendererDefinitionsV2 } = require('@agistack/plugin-runtime');
  const { createDesktopNativeKnowledgeClientV2 } = require(
    root + '/plugins/desktopProjectMemoriesAuthorityModuleV2.js',
  );
  const { acquireDesktopRendererServiceOperationLeaseV2 } = require(
    root + '/plugins/desktopRendererServiceOperationLeaseV2.js',
  );
  const snapshot = JSON.parse(
    readFileSync(
      new URL(
        '../../../../shared/profiles/memstack-knowledge-sync-acceptance.v2.json',
        import.meta.url,
      ),
      'utf8',
    ),
  );
  const modules = readdirSync(root + '/plugins')
    .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
    .flatMap((name) =>
      Object.values(require(root + '/plugins/' + name)).filter(
        (value) => value?.moduleRef && typeof value.apply === 'function',
      ),
    );
  const loader = new LoaderV2(
    [...createDesktopRendererDefinitionsV2(), ...modules],
    'desktop-renderer',
  );
  const generation = await loader.stage(snapshot);
  const native = {
    ...scope,
    profile_id: snapshot.profile_id,
    generation: snapshot.generation,
    digest: snapshot.digest,
  };
  assert.equal(generation.snapshot.digest, native.digest);
  const operations = createDesktopProjectMemoriesOperationsV2(() => ({
    acquireServiceOperationLease: (request) =>
      acquireDesktopRendererServiceOperationLeaseV2(generation, request, () => ({
        release: async () => {},
      })),
  }));
  const originalFetch = globalThis.fetch;
  let actorId = 'local-actor';
  let actorReads = 0;
  let returnedScope = native;
  const queries = [];
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    if (path === '/api/v1/auth/me') {
      actorReads += 1;
      return json({ user_id: actorId, is_active: true });
    }
    if (path === '/api/v1/knowledge/context')
      return json({ contract_version: '1.0.0', scope: returnedScope });
    if (path === '/api/v1/knowledge/query') {
      const body = JSON.parse(init.body);
      assert.deepEqual(body.scope, native);
      queries.push(body.query.operation);
      const result =
        body.query.operation === 'sync_status'
          ? { status: { ...status, link: null } }
          : {
              context: {
                ...pullContext,
                local: { ...pullContext.local, project_id: native.project_id },
              },
            };
      return json({ contract_version: '1.0.0', scope: native, result });
    }
    assert.equal(path, '/api/v1/knowledge/sync-connection');
    return json({
      contract_version: '1.0.0',
      scope: native,
      result: { connection: null },
    });
  };
  try {
    const observed = await createDesktopNativeKnowledgeClientV2(operations, config).observeScope(
      projectScope,
      { expectedActorId: 'local-actor' },
    );
    const result = await createDesktopNativeKnowledgeConnectionClientV2(operations, config).execute(
      projectScope,
      { operation: 'connection' },
      { expectedScope: observed },
    );
    assert.equal(result.scope.digest, snapshot.digest);
    assert.equal(result.result.connection, null);
    actorReads = 0;
    const { createNativeKnowledgeSyncController } = require(
      root + '/features/project-knowledge/nativeKnowledgeSyncController.js',
    );
    const controller = createNativeKnowledgeSyncController({
      client: createDesktopNativeKnowledgeClientV2(operations, config),
      authority: {
        scope: projectScope,
        userId: 'local-actor',
        sessionId: 'session',
        contextRevision: native.context_revision,
        generationDigest: native.digest,
        available: true,
        allowedActions: ['sync_status', 'sync_pull', 'sync_push'],
      },
    });
    await controller.refresh();
    assert.equal(
      actorReads,
      2,
      'initial sync must verify the local actor before and after scope discovery',
    );
    assert.equal(controller.getSnapshot().error, null);
    assert.equal(controller.getSnapshot().phase, 'ready');
    assert.equal(controller.getSnapshot().status.link, null);
    await controller.sync('sync_pull');
    await controller.sync('sync_push');
    assert.equal(controller.getSnapshot().phase, 'ready');
    assert.deepEqual(queries, ['sync_status']);
    const { createNativeKnowledgeConflictController } = require(
      root + '/features/project-knowledge/nativeKnowledgeConflictController.js',
    );
    const conflicts = createNativeKnowledgeConflictController({
      client: createDesktopNativeKnowledgeClientV2(operations, config),
      authority: {
        scope: projectScope,
        userId: 'local-actor',
        sessionId: 'session',
        contextRevision: native.context_revision,
        generationDigest: native.digest,
        available: true,
        allowedActions: ['pull_conflict_context'],
      },
    });
    await conflicts.open({ kind: 'pull', id: pullContext.local.id });
    assert.equal(conflicts.getSnapshot().error, null);
    assert.equal(conflicts.getSnapshot().phase, 'reviewing');
    assert.deepEqual(queries, ['sync_status', 'pull_conflict_context']);
    for (const drift of [
      { actor: 'other-actor' },
      { scope: { ...native, tenant_id: 'other-tenant' } },
      { scope: { ...native, project_id: 'other-project' } },
      { scope: { ...native, context_revision: native.context_revision + 1 } },
      { scope: { ...native, digest: 'e'.repeat(64) } },
      { scope: { ...native, generation: native.generation + 1 } },
    ]) {
      actorId = drift.actor ?? 'local-actor';
      returnedScope = drift.scope ?? native;
      const invalid = createNativeKnowledgeSyncController({
        client: createDesktopNativeKnowledgeClientV2(operations, config),
        authority: {
          scope: projectScope,
          userId: 'local-actor',
          sessionId: 'session',
          contextRevision: native.context_revision,
          generationDigest: native.digest,
          available: true,
          allowedActions: ['sync_status'],
        },
      });
      await invalid.refresh();
      assert.equal(invalid.getSnapshot().status, null);
      assert.notEqual(invalid.getSnapshot().error, null);
      assert.deepEqual(queries, ['sync_status', 'pull_conflict_context']);
    }
  } finally {
    globalThis.fetch = originalFetch;
    await generation.dispose();
  }
});
