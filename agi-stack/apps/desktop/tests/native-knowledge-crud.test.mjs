import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { memory, nativeScope, projectScope, envelope } from './nativeKnowledgeFixtures.mjs';

const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/src';
const {
  prepareNativeKnowledgeCommand,
  requireNativeKnowledgeCommandOptions,
  requireNativeKnowledgeResponse,
} = require(root + '/features/project-knowledge/nativeKnowledgeValidation.js');
const { createDesktopNativeKnowledgeSyncHttpV2 } = require(
  root + '/plugins/desktopNativeKnowledgeSyncHttpV2.js',
);
const { createDesktopProjectMemoriesOperationsV2, createDesktopNativeKnowledgeClientV2 } = require(
  root + '/plugins/desktopProjectMemoriesAuthorityModuleV2.js',
);
const config = {
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://cloud.test',
  apiKey: 'identity',
  localApiToken: 'launch',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  workspaceRoot: '',
  mode: 'local',
};
const observed = { expectedScope: nativeScope };
const create = { operation: 'create', memory, idempotency_key: 'create-memory-1' };
const update = {
  operation: 'update',
  memory: { ...memory, version: 4, content: 'updated' },
  expected_revision: 4,
  idempotency_key: 'update-memory-1',
};
const remove = {
  operation: 'delete',
  id: memory.id,
  expected_revision: 5,
  idempotency_key: 'delete-memory-1',
};
const get = { operation: 'get', id: memory.id };
const outcome = (command, replayed = false) => ({
  receipt: {
    sequence: 17,
    memory:
      command.operation === 'delete'
        ? { ...memory, version: command.expected_revision + 1 }
        : {
            ...command.memory,
            embedding: command.memory.embedding ?? null,
            version: command.operation === 'create' ? 1 : command.expected_revision + 1,
          },
    deleted: command.operation === 'delete',
  },
  replayed,
  processing_status: 'accepted',
});
const cases = [[get, { memory }], ...[create, update, remove].map((c) => [c, outcome(c)])];
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
const errorCode = (code) => (error) => error.message === code;

async function withFetch(fetch, run) {
  const original = globalThis.fetch;
  globalThis.fetch = fetch;
  try {
    await run();
  } finally {
    globalThis.fetch = original;
  }
}

test('get and mutation contracts validate immutable Rust receipts including replay', () => {
  for (const [command, result] of cases) {
    const prepared = prepareNativeKnowledgeCommand(command);
    assert.deepEqual(prepared, command);
    assert(Object.isFrozen(prepared));
    const response = requireNativeKnowledgeResponse(
      envelope(command, result),
      command,
      projectScope,
      nativeScope,
    );
    assert.deepEqual(response.result, result);
    assert(Object.isFrozen(response.result));
  }
  for (const command of [create, update, remove]) {
    const replay = outcome(command, true);
    assert.deepEqual(
      requireNativeKnowledgeResponse(envelope(command, replay), command, projectScope, nativeScope)
        .result,
      replay,
    );
  }
  const { embedding, ...withoutEmbedding } = memory;
  const command = {
    ...create,
    memory: { ...withoutEmbedding, title: '', entities: [{ name: '', kind: 'tag' }] },
  };
  assert.deepEqual(
    requireNativeKnowledgeResponse(
      envelope(command, outcome(command)),
      command,
      projectScope,
      nativeScope,
    ).result,
    outcome(command),
  );
  const embedded = { ...create, memory: { ...memory, embedding: [0.1] } };
  const rounded = outcome(embedded);
  rounded.receipt.memory.embedding = [Math.fround(0.1)];
  requireNativeKnowledgeResponse(envelope(embedded, rounded), embedded, projectScope, nativeScope);
});

test('mutation requests reject invalid revisions, keys, entity shapes and spoofed fields', () => {
  const invalid = [
    { ...create, memory: { ...memory, version: 2 } },
    ...[0, -1, 1.5, 4294967295, 4294967296, Number.MAX_SAFE_INTEGER].flatMap(
      (expected_revision) => [
        { ...update, expected_revision },
        { ...remove, expected_revision },
      ],
    ),
    { ...update, memory: { ...update.memory, version: 3 } },
    ...['', ' leading', 'trailing ', '\n', 'x'.repeat(513)].map((idempotency_key) => ({
      ...create,
      idempotency_key,
    })),
    { ...create, scope: nativeScope },
    { ...create, actor_id: 'spoofed' },
    { ...create, memory: { ...memory, tenant_id: 'spoofed' } },
    { ...create, memory: { ...memory, entities: [{ unexpected: true }] } },
    { ...create, memory: { ...memory, embedding: [1e39] } },
    { ...create, memory: { ...memory, created_at_ms: Number.MAX_SAFE_INTEGER + 1 } },
  ];
  for (const command of invalid) assert.throws(() => prepareNativeKnowledgeCommand(command));
  for (const command of [create, update, remove]) {
    assert.throws(
      () => requireNativeKnowledgeCommandOptions(command),
      errorCode('native_knowledge_expected_scope_required'),
    );
  }
  assert.throws(
    () =>
      requireNativeKnowledgeCommandOptions(
        { ...create, memory: { ...memory, project_id: 'other-project' } },
        observed,
      ),
    errorCode('project_knowledge_scope_conflict'),
  );
});

test('native CRUD HTTP uses fixed routes, observed context, idempotency and matching revision headers', async () => {
  let current, requests;
  await withFetch(
    async (url, init = {}) => {
      requests.push({ url: String(url), init });
      const headers = new Headers(init.headers);
      assert.equal(headers.get('Authorization'), 'Bearer identity');
      assert.equal(headers.get('X-Agistack-Launch'), 'launch');
      if (String(url).endsWith('/context'))
        return json({ contract_version: '1.0.0', scope: nativeScope });
      const [command, result] = current;
      const body = JSON.parse(init.body);
      assert.deepEqual(body.scope, nativeScope);
      if (command.operation === 'get') {
        assert.equal(new URL(url).pathname, '/api/v1/knowledge/query');
        assert.deepEqual(body, { scope: nativeScope, query: command });
        assert.equal(headers.get('Idempotency-Key'), null);
      } else {
        assert.equal(new URL(url).pathname, '/api/v1/knowledge/mutations');
        const { idempotency_key, ...mutation } = command;
        assert.deepEqual(body, { scope: nativeScope, mutation });
        assert.equal(headers.get('Idempotency-Key'), idempotency_key);
        assert.equal(
          headers.get('X-Expected-Revision'),
          command.expected_revision === undefined ? null : String(command.expected_revision),
        );
      }
      return json({ contract_version: '1.0.0', scope: nativeScope, result });
    },
    async () => {
      const authority = createDesktopNativeKnowledgeSyncHttpV2(config, projectScope);
      for (current of cases) {
        requests = [];
        assert.deepEqual((await authority.executeSync(current[0], observed)).result, current[1]);
        assert.equal(requests.length, 2);
      }
    },
  );
});

test('mutations reject absent or changed observed context before a write', async () => {
  let requests = 0;
  await withFetch(
    async () => {
      requests++;
      return json({ contract_version: '1.0.0', scope: nativeScope });
    },
    async () => {
      const authority = createDesktopNativeKnowledgeSyncHttpV2(config, projectScope);
      for (const command of [create, update, remove]) {
        await assert.rejects(
          authority.executeSync(command),
          errorCode('native_knowledge_expected_scope_required'),
        );
        assert.equal(requests, 0);
      }
      for (const [key, value] of Object.entries(nativeScope)) {
        requests = 0;
        const expectedScope = {
          ...nativeScope,
          [key]: typeof value === 'number' ? value + 1 : value + '-stale',
        };
        await assert.rejects(
          authority.executeSync(update, { expectedScope }),
          errorCode('project_knowledge_scope_conflict'),
        );
        assert.equal(requests, key === 'project_id' ? 0 : 1);
      }
    },
  );
});

test('mutation receipts reject wrong identity, revision, deletion, content and processing claims', () => {
  const alterations = [
    (r) => {
      r.receipt.sequence = 0;
    },
    (r) => {
      r.receipt.memory.id = 'other';
    },
    (r) => {
      r.receipt.memory.project_id = 'other';
    },
    (r) => {
      r.receipt.memory.version += 1;
    },
    (r) => {
      r.receipt.memory.content = 'wrong content';
    },
    (r) => {
      r.receipt.memory.author_id = 'other';
    },
    (r) => {
      r.receipt.deleted = true;
    },
    (r) => {
      r.processing_status = 'completed';
    },
    (r) => {
      r.receipt.extra = true;
    },
  ];
  for (const alter of alterations) {
    const result = structuredClone(outcome(update));
    alter(result);
    assert.throws(() =>
      requireNativeKnowledgeResponse(envelope(update, result), update, projectScope, nativeScope),
    );
  }
  const deletion = outcome(remove);
  deletion.receipt.deleted = false;
  assert.throws(() =>
    requireNativeKnowledgeResponse(envelope(remove, deletion), remove, projectScope, nativeScope),
  );
  assert.throws(() =>
    requireNativeKnowledgeResponse(
      envelope(get, { memory: { ...memory, id: 'other' } }),
      get,
      projectScope,
      nativeScope,
    ),
  );
});

test('HTTP failures retain structured reasons and never retry a mutation implicitly', async () => {
  for (const [status, code, command] of [
    [404, 'knowledge_not_found', get],
    [409, 'knowledge_revision_conflict', update],
    [409, 'knowledge_idempotency_conflict', create],
    [403, 'knowledge_write_forbidden', remove],
  ]) {
    let posts = 0;
    await withFetch(
      async (url) => {
        if (String(url).endsWith('/context'))
          return json({ contract_version: '1.0.0', scope: nativeScope });
        posts++;
        return json({ error: { code, message: 'rejected', target: 'desktop-sidecar' } }, status);
      },
      async () => {
        const authority = createDesktopNativeKnowledgeSyncHttpV2(config, projectScope);
        await assert.rejects(
          authority.executeSync(command, observed),
          (error) => error.message === code && error.status === status,
        );
        assert.equal(posts, 1);
      },
    );
  }
});

test('unknown write failure requires explicit retry with the same stable request and replay receipt', async () => {
  const bodies = [];
  await withFetch(
    async (url, init = {}) => {
      if (String(url).endsWith('/context'))
        return json({ contract_version: '1.0.0', scope: nativeScope });
      bodies.push({ body: init.body, key: new Headers(init.headers).get('Idempotency-Key') });
      if (bodies.length === 1) throw new TypeError('connection closed');
      return json({ contract_version: '1.0.0', scope: nativeScope, result: outcome(update, true) });
    },
    async () => {
      const authority = createDesktopNativeKnowledgeSyncHttpV2(config, projectScope);
      await assert.rejects(authority.executeSync(update, observed));
      assert.equal(bodies.length, 1);
      assert.equal((await authority.executeSync(update, observed)).result.replayed, true);
      assert.deepEqual(bodies[0], bodies[1]);
    },
  );
});

test('CRUD operation admission preserves lease release and rejects missing observed scope before acquisition', async () => {
  const events = [];
  const actions = {
    async acquireServiceOperationLease(request) {
      events.push(['acquire', request]);
      return {
        status: 'accepted',
        digest: 'renderer-digest',
        useService(fn) {
          return fn({
            bindOperation() {
              return {
                load: async () => {
                  throw Error('unexpected load');
                },
                executeSync: async (command) => {
                  events.push(['execute']);
                  return envelope(command, outcome(command));
                },
              };
            },
          });
        },
        async release() {
          events.push(['release']);
        },
      };
    },
  };
  const client = createDesktopNativeKnowledgeClientV2(
    createDesktopProjectMemoriesOperationsV2(() => actions),
    config,
  );
  await assert.rejects(async () => client.execute(projectScope, create));
  assert.equal(events.length, 0);
  await client.execute(projectScope, create, observed);
  assert.deepEqual(
    events.map(([name]) => name),
    ['acquire', 'execute', 'release'],
  );
  assert.deepEqual(events[0][1].scope, {
    kind: 'project',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
  });
});

test('mutation snapshot stays immutable while native context discovery is pending', async () => {
  let release;
  const ready = new Promise((resolve) => {
    release = resolve;
  });
  const input = structuredClone(update);
  const options = { expectedScope: structuredClone(nativeScope) };
  await withFetch(
    async (url, init = {}) => {
      if (String(url).endsWith('/context')) {
        await ready;
        return json({ contract_version: '1.0.0', scope: nativeScope });
      }
      const { idempotency_key, ...mutation } = update;
      assert.deepEqual(JSON.parse(init.body), { scope: nativeScope, mutation });
      assert.equal(new Headers(init.headers).get('Idempotency-Key'), idempotency_key);
      return json({ contract_version: '1.0.0', scope: nativeScope, result: outcome(update) });
    },
    async () => {
      const pending = createDesktopNativeKnowledgeSyncHttpV2(config, projectScope).executeSync(
        input,
        options,
      );
      input.memory.content = 'changed while waiting';
      input.idempotency_key = 'changed-key';
      options.expectedScope.generation++;
      release();
      assert.deepEqual((await pending).result, outcome(update));
    },
  );
});

test('CRUD transport rejects cloud and non-loopback modes before issuing requests', async () => {
  await withFetch(
    async () => {
      assert.fail('must not issue HTTP');
    },
    async () => {
      for (const [command] of cases) {
        for (const invalid of [
          { ...config, mode: 'cloud' },
          { ...config, apiBaseUrl: 'https://remote.test' },
        ]) {
          await assert.rejects(
            createDesktopNativeKnowledgeSyncHttpV2(invalid, projectScope).executeSync(
              command,
              observed,
            ),
          );
        }
      }
    },
  );
});

test('post-write scope drift and abort never return an accepted mutation receipt', async () => {
  for (const mode of ['scope-drift', 'abort']) {
    let posts = 0;
    const controller = new AbortController();
    await withFetch(
      async (url) => {
        if (String(url).endsWith('/context'))
          return json({ contract_version: '1.0.0', scope: nativeScope });
        posts++;
        if (mode === 'abort') controller.abort();
        return json({
          contract_version: '1.0.0',
          scope: { ...nativeScope, generation: nativeScope.generation + 1 },
          result: outcome(update),
        });
      },
      async () => {
        await assert.rejects(
          createDesktopNativeKnowledgeSyncHttpV2(config, projectScope).executeSync(update, {
            ...observed,
            signal: controller.signal,
          }),
          (error) => (mode === 'abort' ? error.name === 'AbortError' : error.status === 409),
        );
        assert.equal(posts, 1);
      },
    );
  }
});

test('mutation response validation releases the generation lease after rejection', async () => {
  let releases = 0;
  const actions = {
    async acquireServiceOperationLease() {
      return {
        status: 'accepted',
        digest: 'renderer-digest',
        useService(fn) {
          return fn({
            bindOperation() {
              return {
                load: async () => {
                  throw Error('unexpected load');
                },
                executeSync: async (command) => ({
                  ...envelope(command, outcome(command)),
                  scope: { ...nativeScope, generation: nativeScope.generation + 1 },
                }),
              };
            },
          });
        },
        async release() {
          releases++;
        },
      };
    },
  };
  const client = createDesktopNativeKnowledgeClientV2(
    createDesktopProjectMemoriesOperationsV2(() => actions),
    config,
  );
  await assert.rejects(
    client.execute(projectScope, create, observed),
    (error) => error.status === 409,
  );
  assert.equal(releases, 1);
});
