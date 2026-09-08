import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import {
  wireCases,
  nativeScope,
  projectScope,
  response,
  operation,
  source,
} from './nativeKnowledgeProcessingFixtures.mjs';
const require = createRequire(import.meta.url);
const v = require(
  `${process.env.AGISTACK_KNOWLEDGE_HTTP_TEST_DIST ?? '/tmp/agistack-desktop-test-dist'}/src/features/project-knowledge/nativeKnowledgeProcessingValidation.js`,
);
const command = (name) => Boolean(wireCases.find((c) => c.name === name).request.command);
const prepare = (name, value) =>
  command(name)
    ? v.prepareNativeKnowledgeProcessingCommand(value, projectScope)
    : v.prepareNativeKnowledgeProcessingQuery(value, projectScope);
const validate = (name, value, op = operation(name)) =>
  command(name)
    ? v.requireNativeKnowledgeProcessingCommandResponse(value, op, projectScope, nativeScope)
    : v.requireNativeKnowledgeProcessingQueryResponse(value, op, projectScope, nativeScope);
const objects = (value, path = []) =>
  value && typeof value === 'object'
    ? [
        ...(!Array.isArray(value) ? [path] : []),
        ...Object.entries(value).flatMap(([key, v]) => objects(v, [...path, key])),
      ]
    : [];
const at = (value, path) => path.reduce((v, key) => v[key], value);

for (const row of wireCases)
  test(`${row.name} rejects unknown properties at every request and response object`, () => {
    const op = operation(row.name),
      result = response(row.name);
    assert.deepEqual(prepare(row.name, op), op);
    assert.deepEqual(validate(row.name, result), result);
    for (const path of objects(op)) {
      const forged = structuredClone(op);
      at(forged, path).private_override = true;
      assert.throws(
        () => prepare(row.name, forged),
        (e) => e.status === 422,
      );
    }
    for (const path of objects(result)) {
      const forged = structuredClone(result);
      at(forged, path).private_override = true;
      assert.throws(() => validate(row.name, forged));
    }
  });

test('private provider data, omitted CAS, unsafe numbers, cyclic and undefined payloads are rejected', () => {
  for (const field of [
    'profile',
    'vector',
    'credential_binding_digest',
    'lease_ms',
    'provider_base_url',
  ])
    assert.throws(() => prepare('index_one', { ...operation('index_one'), [field]: 'forged' }));
  for (const name of ['configure_embedding', 'select_embedding', 'promote_index']) {
    const op = operation(name);
    delete op[name === 'promote_index' ? 'expected_active_build_id' : 'expected_config_revision'];
    assert.throws(() => prepare(name, op));
  }
  for (const value of [0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, NaN, Infinity, '1'])
    assert.throws(() => prepare('semantic', { ...operation('semantic'), config_revision: value }));
  for (const value of ['', 'x'.repeat(4097), '汉'.repeat(1366)])
    assert.throws(() => prepare('text', { ...operation('text'), literal: value }));
  assert.throws(() => prepare('semantic', { ...operation('semantic'), query: '   ' }));
  assert.doesNotThrow(() => prepare('text', { ...operation('text'), literal: ' ' }));
  const cyclic = operation('entities');
  cyclic.request.source = cyclic;
  assert.throws(() => prepare('entities', cyclic));
  assert.throws(() =>
    prepare('entities', {
      ...operation('entities'),
      request: { limit: 1, source: undefined },
    }),
  );
  assert.throws(() => prepare('process_one', { ...operation('process_one'), workspace_id: ' ' }));
});

test('nested sources and cursor query binding cannot cross tenant, project, source or literal', () => {
  for (const key of ['tenant_id', 'project_id']) {
    assert.throws(() =>
      prepare('entities', {
        operation: 'entities',
        request: { limit: 1, source: { ...source, [key]: 'other' } },
      }),
    );
    const r = response('relationships');
    r.result.items[0].source_entity.source[key] = 'other';
    assert.throws(() => validate('relationships', r));
  }
  const cursor = {
    tenant_id: 'tenant',
    project_id: 'project',
    kind: 'text',
    source: null,
    literal: 'Content',
    upper_change_sequence: 4,
    after: { change_sequence: 1, item_index: 0 },
  };
  const q = {
    operation: 'text',
    literal: 'Content',
    request: { limit: 1, cursor },
  };
  assert.deepEqual(prepare('text', q), q);
  for (const patch of [
    { kind: 'entities' },
    { literal: 'different' },
    { tenant_id: 'other' },
    { project_id: 'other' },
    { source },
    { upper_change_sequence: 0 },
    { after: { change_sequence: 0, item_index: 0 } },
    { after: { change_sequence: 1, item_index: 1 } },
  ])
    assert.throws(() =>
      prepare('text', {
        ...q,
        request: { limit: 1, cursor: { ...cursor, ...patch } },
      }),
    );
});

test('retrieval pages enforce exact cursor position, upper bound, ordering and reference indexes', () => {
  const q = operation('entities'),
    r = response('entities');
  r.result.next_cursor = {
    tenant_id: 'tenant',
    project_id: 'project',
    kind: 'entities',
    source: null,
    literal: null,
    upper_change_sequence: 4,
    after: { change_sequence: 1, item_index: 0 },
  };
  validate('entities', r, q);
  for (const patch of [
    { after: { change_sequence: 2, item_index: 0 } },
    { kind: 'relationships' },
    { source },
    { literal: 'x' },
  ]) {
    const bad = structuredClone(r);
    bad.result.next_cursor = { ...bad.result.next_cursor, ...patch };
    assert.throws(() => validate('entities', bad, q));
  }
  const second = response('entities');
  second.result.items[0].reference.entity_index = 1;
  const next = { ...q, request: { limit: 1, cursor: r.result.next_cursor } };
  validate('entities', second, next);
  assert.throws(() => validate('entities', response('entities'), next));
  const more = response('entities');
  more.result.items.push(more.result.items[0]);
  assert.throws(() => validate('entities', more, q));
  const rel = response('relationships');
  rel.result.items[0].target_entity.entity_index = 0;
  assert.throws(() => validate('relationships', rel));
  const text = response('text');
  text.result.items[0].content = 'different';
  assert.throws(() => validate('text', text));
});

test('status counters, semantic build and scores, exact retry and receipt outcomes stay consistent', () => {
  for (const patch of [
    { configuration: null },
    {
      processing: {
        current_sources: 1,
        applied_sources: 2,
        pending_sources: 0,
        failed_sources: 0,
      },
    },
    { index: { current_sources: 1, completed_sources: 2, failed_sources: 0 } },
  ])
    assert.throws(() =>
      validate('configuration', {
        ...response('configuration'),
        result: { ...response('configuration').result, ...patch },
      }),
    );
  for (const key of ['build_id', 'revision']) {
    const r = response('semantic');
    r.result.configuration[key] = key === 'revision' ? 2 : 'other';
    assert.throws(() => validate('semantic', r));
  }
  for (const score of [-1.01, 1.01, NaN, Infinity]) {
    const r = response('semantic');
    r.result.hits[0].score = score;
    assert.throws(() => validate('semantic', r));
  }
  const duplicate = response('semantic');
  duplicate.result.hits.push(duplicate.result.hits[0]);
  assert.throws(() => validate('semantic', duplicate));
  for (const name of ['index_one', 'process_one']) {
    const r = response(name);
    r.result.receipt.status = 'failed';
    assert.throws(() => validate(name, r));
    r.result.receipt.failure = name === 'index_one' ? 'invalid_embedding' : 'invalid_extraction';
    validate(name, r);
    r.result.receipt.attempt = 0;
    assert.throws(() => validate(name, r));
    r.result.receipt = null;
    validate(name, r);
  }
  const retry = response('retry_index');
  retry.result.attempt = 2;
  assert.throws(() => validate('retry_index', retry));
  const configured = response('configure_embedding');
  configured.result.configuration.provider_revision = 1;
  assert.throws(() => validate('configure_embedding', configured));
  const selected = response('select_embedding');
  selected.result.configuration.revision = 1;
  assert.throws(() => validate('select_embedding', selected));
  const promoted = response('promote_index');
  promoted.result.active_build_id = 'other';
  assert.throws(() => validate('promote_index', promoted));
});

test('response envelope rejects wrong version, scope, missing fields and misplaced operation', () => {
  for (const patch of [
    { contract_version: '2.0.0' },
    { scope: { ...nativeScope, tenant_id: 'other' } },
    { scope: { ...nativeScope, generation: 2 } },
    { scope: { ...nativeScope, digest: ' ' } },
    { operation: 'configuration' },
  ])
    assert.throws(() => validate('configuration', { ...response('configuration'), ...patch }));
  const result = response('configuration');
  delete result.result.index;
  assert.throws(() => validate('configuration', result));
});
