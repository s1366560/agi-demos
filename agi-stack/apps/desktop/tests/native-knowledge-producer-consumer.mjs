// Invoked by the ignored Rust TCP contract test; no producer responses are synthesized.
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { createInterface } from 'node:readline';

const require = createRequire(import.meta.url);
const root = process.env.KNOWLEDGE_RENDERER_COMPILED_ROOT;
assert(root, 'compiled renderer root required');
const { baseUrl, token, memory, tenantId, projectId, phase, stateFile } = JSON.parse(
  process.env.KNOWLEDGE_CONTRACT_CONFIG,
);
const {
  LoaderV2,
  GenerationManagerV2,
  createDesktopRendererDefinitionsV2,
} = require('@agistack/plugin-runtime');
const { acquireDesktopRendererServiceOperationLeaseV2 } = require(
  `${root}/plugins/desktopRendererServiceOperationLeaseV2.js`,
);
const { createDesktopNativeKnowledgeClientV2, createDesktopProjectMemoriesOperationsV2 } = require(
  `${root}/plugins/desktopProjectMemoriesAuthorityModuleV2.js`,
);
const modules = readdirSync(`${root}/plugins`)
  .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
  .flatMap((name) => Object.values(require(`${root}/plugins/${name}`)))
  .filter((value) => value?.moduleRef && typeof value.apply === 'function');
const profile = JSON.parse(
  readFileSync(
    new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
    'utf8',
  ),
);
const generation = await new LoaderV2(
  [...createDesktopRendererDefinitionsV2(), ...modules],
  'desktop-renderer',
).stage(profile);
const manager = new GenerationManagerV2();
await manager.publish(generation);
const operations = createDesktopProjectMemoriesOperationsV2(() => ({
  acquireServiceOperationLease: (request) =>
    acquireDesktopRendererServiceOperationLeaseV2(generation, request, (candidate) =>
      manager.acquire(candidate),
    ),
}));
const client = createDesktopNativeKnowledgeClientV2(operations, {
  apiBaseUrl: baseUrl,
  apiKey: token,
  localApiToken: token,
  mode: 'local',
  tenantId,
  projectId,
  deviceAuthorizationBaseUrl: '',
  workspaceId: '',
  workspaceRoot: '',
});
const scope = { authority: 'local', tenantId, projectId };
const observed = (await client.execute(scope, { operation: 'sync_status' })).scope;
const execute = (command) => client.execute(scope, command, { expectedScope: observed });
const create = {
  operation: 'create',
  memory: {
    ...memory,
    metadata: { nested: { flags: [false, null, 3, '中文'] } },
  },
  idempotency_key: 'renderer-create',
};
const update = {
  operation: 'update',
  memory: {
    ...memory,
    content: 'renderer-updated',
    metadata: { edited: ['retained', 2] },
  },
  expected_revision: 1,
  idempotency_key: 'renderer-update',
};
const get = { operation: 'get', id: memory.id };
const statusIs = (status) => (error) => error.status === status;
const emit = (event) => process.stdout.write(`${JSON.stringify({ event })}\n`);

try {
  if (phase === 'write') {
    const created = (await execute(create)).result;
    assert.equal(created.receipt.memory.version, 1);
    assert.equal(created.replayed, false);
    assert.deepEqual(created.receipt.memory.metadata, create.memory.metadata);
    assert.deepEqual((await execute(get)).result.memory, created.receipt.memory);
    const updated = (await execute(update)).result;
    assert.equal(updated.receipt.memory.version, 2);
    assert.equal(updated.processing_status, 'accepted');
    assert.deepEqual(updated.receipt.memory.metadata, update.memory.metadata);
    assert.deepEqual((await execute(get)).result.memory, updated.receipt.memory);
    await assert.rejects(execute({ ...update, idempotency_key: 'stale-revision' }), statusIs(409));
    await assert.rejects(
      execute({ ...create, memory: { ...memory, title: 'changed' } }),
      statusIs(409),
    );
    await assert.rejects(
      execute({
        ...create,
        idempotency_key: 'forged',
        memory: {
          ...memory,
          id: 'forged-memory',
          author_id: 'forged-author',
        },
      }),
      statusIs(403),
    );
    writeFileSync(stateFile, JSON.stringify({ created, updated }));
  } else {
    const { created, updated } = JSON.parse(readFileSync(stateFile, 'utf8'));
    assert.deepEqual((await execute(get)).result.memory, updated.receipt.memory);
    assert.deepEqual((await execute(update)).result, {
      ...updated,
      replayed: true,
    });
    if (phase === 'late') {
      const originalFetch = globalThis.fetch;
      const input = createInterface({ input: process.stdin });
      globalThis.fetch = async (url, options) => {
        if (new URL(url).pathname === '/api/v1/knowledge/mutations') {
          const continued = new Promise((resolve) => input.once('line', resolve));
          emit('before_mutation');
          assert.equal(await continued, 'continue');
        }
        return originalFetch(url, options);
      };
      try {
        await assert.rejects(
          execute({
            operation: 'update',
            memory: updated.receipt.memory,
            expected_revision: 2,
            idempotency_key: 'late-generation',
          }),
          (error) => error.status === 409 && error.message === 'knowledge_generation_mismatch',
        );
      } finally {
        globalThis.fetch = originalFetch;
        input.close();
      }
      // The original observed scope must also fail before another mutation can be issued.
      await assert.rejects(
        execute(get),
        (error) => error.status === 409 && error.message === 'project_knowledge_scope_conflict',
      );
    } else {
      assert.equal(phase, 'finish');
      const remove = {
        operation: 'delete',
        id: memory.id,
        expected_revision: 2,
        idempotency_key: 'renderer-delete',
      };
      const deleted = (await execute(remove)).result;
      assert.equal(deleted.receipt.memory.version, 3);
      assert.equal(deleted.receipt.deleted, true);
      assert.deepEqual((await execute(remove)).result, {
        ...deleted,
        replayed: true,
      });
      assert.deepEqual((await execute(create)).result, {
        ...created,
        replayed: true,
      });
      assert.deepEqual((await execute(update)).result, {
        ...updated,
        replayed: true,
      });
      await assert.rejects(execute(get), statusIs(404));
    }
  }
  emit('complete');
} finally {
  await manager.close();
}
