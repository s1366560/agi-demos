import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { memory, nativeScope, projectScope } from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const {
  createNativeKnowledgeRetrievalController,
} = require('/tmp/agistack-project-knowledge-test-dist/src/features/project-knowledge/nativeKnowledgeRetrievalController.js');
const source = {
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  memory_id: memory.id,
  revision: 1,
  change_sequence: 1,
};
const configuration = {
  revision: 8,
  build_id: 'build-B',
  provider_id: 'provider-1',
  provider_revision: 2,
  model_id: 'embedding-model',
  dimensions: 3,
  input_contract_version: 1,
  normalization_version: 1,
};
const snapshot = {
  configuration,
  active_build_id: 'build-A',
  processing: {
    current_sources: 5,
    applied_sources: 2,
    pending_sources: 2,
    failed_sources: 1,
  },
  index: { current_sources: 2, completed_sources: 1, failed_sources: 1 },
};
const authority = {
  scope: projectScope,
  userId: 'user-1',
  sessionId: 'session-1',
  contextRevision: 7,
  generationDigest: 'renderer-1',
  available: true,
  allowedActions: ['configuration', 'text', 'semantic', 'entities', 'relationships', 'view'],
};
const semantic = {
  configuration,
  processing: snapshot.processing,
  index: snapshot.index,
  hits: [
    {
      input: { source, audit_attempt: 1, input_digest: 'digest-1' },
      score: -0.25,
    },
  ],
};
const results = {
  configuration: snapshot,
  text: {
    items: [
      {
        source,
        audit_attempt: 1,
        title: 'Title',
        content: 'Exact literal source',
      },
    ],
    next_cursor: null,
  },
  entities: {
    items: [
      {
        reference: { source, entity_index: 0 },
        audit_attempt: 1,
        entity: { name: 'Entity', kind: 'topic' },
      },
    ],
    next_cursor: null,
  },
  relationships: {
    items: [
      {
        source,
        relationship_index: 0,
        audit_attempt: 1,
        source_entity: { source, entity_index: 0 },
        target_entity: { source, entity_index: 1 },
        relationship: {
          source_index: 0,
          target_index: 1,
          relation_type: 'related',
          fact: 'Declared fact',
          score: 0.1,
        },
      },
    ],
    next_cursor: null,
  },
  semantic,
};
function fixture(options = {}) {
  const queries = [];
  const gets = [];
  const client = {
    query: async (scope, command, request) => {
      queries.push({ scope, command, request });
      return (
        (options.query ? await options.query(command, request, queries) : undefined) ?? {
          contract_version: '1.0.0',
          scope: nativeScope,
          result: structuredClone(results[command.operation]),
        }
      );
    },
  };
  const sourceClient = {
    execute: async (scope, command, request) => {
      gets.push({ scope, command, request });
      return (
        (options.get ? await options.get(command, request) : undefined) ?? {
          contract_version: '1.0.0',
          operation: 'get',
          scope: nativeScope,
          result: { memory },
        }
      );
    },
  };
  const controller = createNativeKnowledgeRetrievalController({
    client: options.missingClient ? undefined : client,
    sourceClient,
    authority: { ...authority, ...options.authority },
  });
  return { controller, queries, gets };
}

test('retrieval requires an admitted dedicated client and exact operations, not CRUD permissions', async () => {
  for (const restriction of [
    { available: false },
    { userId: null },
    { sessionId: null },
    { generationDigest: null },
    { scope: { ...projectScope, authority: 'cloud' } },
    { allowedActions: ['view', 'list', 'update'] },
  ]) {
    const { controller, queries } = fixture({ authority: restriction });
    await controller.refreshConfiguration();
    controller.setMode('semantic');
    controller.setDraft('query');
    await controller.submit();
    assert.equal(queries.length, 0);
  }
  const absent = fixture({ missingClient: true });
  await absent.controller.refreshConfiguration();
  await absent.controller.submit();
  assert.equal(absent.controller.getSnapshot().phase, 'unavailable');
  assert.equal(absent.queries.length, 0);
  const textOnly = fixture({ authority: { allowedActions: ['text'] } });
  await textOnly.controller.refreshConfiguration();
  textOnly.controller.setDraft('term');
  await textOnly.controller.submit();
  assert.deepEqual(
    textOnly.queries.map((q) => q.command.operation),
    ['text'],
  );
});

test('literal preserves exact text and opaque query-bound cursors; changing query clears results and cursor', async () => {
  const literal = '  A%_  ';
  const cursor = {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    kind: 'text',
    source: null,
    literal,
    upper_change_sequence: 10,
    after: { change_sequence: 1, item_index: 0 },
  };
  const { controller, queries } = fixture({
    query: async (command) =>
      command.operation === 'text'
        ? {
            scope: nativeScope,
            result: {
              ...results.text,
              next_cursor: command.request.cursor ? null : cursor,
            },
          }
        : undefined,
  });
  controller.setDraft(literal);
  await controller.submit();
  await controller.nextPage();
  assert.equal(queries[0].command.literal, literal);
  assert.equal(queries[1].command.literal, literal);
  assert.deepEqual(queries[1].command.request.cursor, cursor);
  assert.deepEqual(queries[1].request.expectedScope, nativeScope);
  assert.equal(controller.getSnapshot().result.result.items.length, 2);
  controller.setDraft('other');
  assert.equal(controller.getSnapshot().result, null);
  await controller.nextPage();
  assert.equal(queries.length, 2);
  await controller.submit();
  assert.equal(queries[2].command.request.cursor, undefined);
});

test('semantic sends only discovered build and config plus user query, preserving negative scores without fallback', async () => {
  const { controller, queries } = fixture();
  await controller.refreshConfiguration();
  controller.setMode('semantic');
  controller.setDraft('explicit semantic query');
  await controller.submit();
  assert.deepEqual(
    queries.map((q) => q.command.operation),
    ['configuration', 'configuration', 'semantic'],
  );
  assert.deepEqual(queries[2].command, {
    operation: 'semantic',
    build_id: 'build-B',
    config_revision: 8,
    query: 'explicit semantic query',
    limit: 25,
  });
  assert.deepEqual(queries[2].request.expectedScope, nativeScope);
  assert.equal(controller.getSnapshot().result.result.hits[0].score, -0.25);
  await controller.nextPage();
  assert.equal(queries.length, 3);
});

test('semantic requires configuration and never silently adopts a changed desired selection', async () => {
  const missing = fixture({ authority: { allowedActions: ['semantic'] } });
  missing.controller.setDraft('query');
  await missing.controller.submit();
  assert.equal(missing.controller.getSnapshot().error, 'configurationRequired');
  assert.equal(missing.queries.length, 0);
  let reads = 0;
  const changed = fixture({
    query: async (command) => {
      if (command.operation === 'configuration')
        return {
          scope: nativeScope,
          result: {
            ...snapshot,
            configuration:
              ++reads === 1
                ? configuration
                : { ...configuration, revision: 9, build_id: 'build-C' },
          },
        };
    },
  });
  await changed.controller.refreshConfiguration();
  changed.controller.setMode('semantic');
  changed.controller.setDraft('query');
  await changed.controller.submit();
  assert.equal(changed.controller.getSnapshot().error, 'configurationChanged');
  assert.equal(
    changed.queries.some((q) => q.command.operation === 'semantic'),
    false,
  );
  assert.equal(changed.controller.getSnapshot().configuration.configuration.build_id, 'build-C');
});

test('an unavailable active build does not fall back to literal search or the old active build', async () => {
  const { controller, queries } = fixture({
    query: async (command) => {
      if (command.operation === 'semantic')
        throw Object.assign(new Error('knowledge_revision_conflict'), {
          status: 409,
        });
    },
  });
  await controller.refreshConfiguration();
  controller.setMode('semantic');
  controller.setDraft('query');
  await controller.submit();
  assert.equal(controller.getSnapshot().error, 'configurationUnavailable');
  assert.equal(controller.getSnapshot().result, null);
  assert.equal(
    queries.filter((q) => q.command.operation === 'semantic')[0].command.build_id,
    'build-B',
  );
  assert.equal(
    queries.some((q) => q.command.operation === 'text'),
    false,
  );
});

test('entities and relationships are explicit browsing operations with no inferred text filter', async () => {
  const { controller, queries } = fixture();
  for (const mode of ['entities', 'relationships']) {
    controller.setMode(mode);
    await controller.submit();
    assert.deepEqual(queries.at(-1).command, {
      operation: mode,
      request: { limit: 25 },
    });
    assert.equal(controller.getSnapshot().result.operation, mode);
  }
});

test('entity navigation pins the exact source, keeps it through pagination and can return to all sources', async () => {
  const cursor = { after: { change_sequence: 1, item_index: 0 } };
  const { controller, queries } = fixture({
    query: async (command) =>
      command.operation === 'relationships'
        ? {
            scope: nativeScope,
            result: {
              ...results.relationships,
              next_cursor: command.request.cursor ? null : cursor,
            },
          }
        : undefined,
  });
  controller.setMode('entities');
  await controller.submit();
  const reference = structuredClone(results.entities.items[0].reference);
  await controller.navigateReference('relationships', reference);
  reference.source.revision = 99;
  assert.deepEqual(queries.at(-1).command, {
    operation: 'relationships',
    request: { limit: 25, source },
  });
  assert.deepEqual(controller.getSnapshot().navigation.source, source);
  await controller.nextPage();
  assert.deepEqual(queries.at(-1).command.request, {
    limit: 25,
    source,
    cursor,
  });
  await controller.navigateReference('entities', results.relationships.items[0].target_entity);
  assert.equal(controller.getSnapshot().navigation.entity_index, 1);
  assert.equal(controller.getSnapshot().mode, 'entities');
  controller.clearNavigation();
  assert.equal(controller.getSnapshot().navigation, null);
  await controller.submit();
  assert.deepEqual(queries.at(-1).command, {
    operation: 'entities',
    request: { limit: 25 },
  });
});

test('navigation only accepts visible exact entity references and admitted target operations', async () => {
  const { controller, queries } = fixture();
  controller.setMode('entities');
  await controller.submit();
  for (const reference of [
    { source: { ...source, tenant_id: 'other' }, entity_index: 0 },
    { source: { ...source, revision: 2 }, entity_index: 0 },
    { source, entity_index: 99 },
  ])
    await controller.navigateReference('relationships', reference);
  await controller.navigateReference('semantic', results.entities.items[0].reference);
  assert.equal(queries.length, 1);
  const restricted = fixture({ authority: { allowedActions: ['entities'] } });
  restricted.controller.setMode('entities');
  await restricted.controller.submit();
  await restricted.controller.navigateReference(
    'relationships',
    results.entities.items[0].reference,
  );
  assert.equal(restricted.queries.length, 1);
});

test('navigation cannot restore results after stop or a newer mode selection', async () => {
  for (const change of ['stop', 'mode']) {
    let release;
    const { controller } = fixture({
      query: async (command) =>
        command.operation === 'relationships'
          ? new Promise((resolve) => {
              release = () => resolve({ scope: nativeScope, result: results.relationships });
            })
          : undefined,
    });
    controller.setMode('entities');
    await controller.submit();
    const pending = controller.navigateReference(
      'relationships',
      results.entities.items[0].reference,
    );
    if (change === 'stop') controller.stop();
    else controller.setMode('text');
    release();
    await pending;
    assert.equal(controller.getSnapshot().navigation, null);
    assert.equal(controller.getSnapshot().result, null);
  }
});

test('a stale source returns no navigation results without fetching a replacement revision', async () => {
  const { controller, queries, gets } = fixture({
    query: async (command) =>
      command.operation === 'relationships'
        ? { scope: nativeScope, result: { items: [], next_cursor: null } }
        : undefined,
  });
  controller.setMode('entities');
  await controller.submit();
  await controller.navigateReference('relationships', results.entities.items[0].reference);
  assert.equal(controller.getSnapshot().result.result.items.length, 0);
  assert.deepEqual(queries.at(-1).command.request.source, source);
  assert.equal(gets.length, 0);
});

test('empty and oversized byte queries fail locally while whitespace is preserved literally', async () => {
  const { controller, queries } = fixture();
  await controller.submit();
  assert.equal(controller.getSnapshot().error, 'queryRequired');
  controller.setDraft('界'.repeat(1366));
  await controller.submit();
  assert.equal(controller.getSnapshot().error, 'queryTooLong');
  assert.equal(queries.length, 0);
  controller.setDraft('  ');
  await controller.submit();
  assert.equal(queries[0].command.literal, '  ');
});

test('semantic source content is shown only after matching the exact returned source revision', async () => {
  const changed = fixture({
    get: async () => ({
      scope: nativeScope,
      result: {
        memory: { ...memory, version: 2, content: 'different revision' },
      },
    }),
  });
  await changed.controller.refreshConfiguration();
  changed.controller.setMode('semantic');
  changed.controller.setDraft('query');
  await changed.controller.submit();
  await changed.controller.viewSource(source);
  assert.equal(changed.controller.getSnapshot().sourceState, 'changed');
  assert.equal(changed.controller.getSnapshot().source, null);
  const matching = fixture();
  matching.controller.setDraft('term');
  await matching.controller.submit();
  await matching.controller.viewSource(source);
  assert.equal(matching.controller.getSnapshot().source.content, memory.content);
  await matching.controller.viewSource({ ...source, memory_id: 'not-a-hit' });
  assert.equal(matching.gets.length, 1);
  const noView = fixture({ authority: { allowedActions: ['text'] } });
  noView.controller.setDraft('term');
  await noView.controller.submit();
  await noView.controller.viewSource(source);
  assert.equal(noView.gets.length, 0);
});

test('scope mismatch clears sensitive draft/config/results and late reads cannot restore an obsolete binding', async () => {
  const changed = fixture({
    query: async (command) => ({
      scope: { ...nativeScope, context_revision: 8 },
      result: results[command.operation],
    }),
  });
  changed.controller.setDraft('sensitive');
  await changed.controller.submit();
  assert.equal(changed.controller.getSnapshot().error, 'contextChanged');
  assert.equal(changed.controller.getSnapshot().draft, '');
  let release;
  const late = fixture({
    query: async (command) =>
      new Promise((resolve) => {
        release = () => resolve({ scope: nativeScope, result: results[command.operation] });
      }),
  });
  late.controller.setDraft('sensitive');
  const running = late.controller.submit();
  late.controller.stop();
  release();
  await running;
  assert.equal(late.controller.getSnapshot().draft, '');
  assert.equal(late.controller.getSnapshot().result, null);
  await late.controller.refreshConfiguration();
  assert.equal(late.queries.length, 1);
  late.controller.activate();
  const next = late.controller.refreshConfiguration();
  release();
  await next;
  assert.ok(late.controller.getSnapshot().configuration);
});

test('mode changes discard a delayed query and source lookup without altering the selected mode', async () => {
  let release;
  const delayed = fixture({
    query: async (command) =>
      new Promise((resolve) => {
        release = () => resolve({ scope: nativeScope, result: results[command.operation] });
      }),
  });
  delayed.controller.setDraft('term');
  const work = delayed.controller.submit();
  delayed.controller.setMode('entities');
  release();
  await work;
  assert.equal(delayed.controller.getSnapshot().mode, 'entities');
  assert.equal(delayed.controller.getSnapshot().result, null);
  let releaseGet;
  const sourceRead = fixture({
    get: async () =>
      new Promise((resolve) => {
        releaseGet = () => resolve({ scope: nativeScope, result: { memory } });
      }),
  });
  sourceRead.controller.setDraft('term');
  await sourceRead.controller.submit();
  const viewing = sourceRead.controller.viewSource(source);
  sourceRead.controller.setMode('relationships');
  releaseGet();
  await viewing;
  assert.equal(sourceRead.controller.getSnapshot().source, null);
});
