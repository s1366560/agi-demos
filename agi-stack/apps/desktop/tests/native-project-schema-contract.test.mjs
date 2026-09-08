import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import {
  require,
  dist,
  scope,
  actor,
  document,
  change,
  receipt,
  envelope,
  capability,
} from './nativeProjectSchemaFixtures.mjs';
const {
  prepareNativeProjectSchemaRequest: prepare,
  requireNativeProjectSchemaResponse: decode,
  requireNativeProjectSchemaCapabilities: decodeCap,
} = require(`${dist}/src/features/project-administration/nativeProjectSchemaValidation.js`);
const { freezeSchemaJson: freeze } = require(
  `${dist}/src/features/project-administration/nativeProjectSchemaShape.js`,
);
const { requireSchemaDocument: checkDocument, requireSchemaSuccessor: successor } = require(
  `${dist}/src/features/project-administration/nativeProjectSchemaDocument.js`,
);
const { parseNativeProjectSchemaJson: parse } = require(
  `${dist}/src/features/project-administration/nativeProjectSchemaJson.js`,
);
const {
  NATIVE_PROJECT_SCHEMA_ACTIONS: actions,
  NATIVE_PROJECT_SCHEMA_DEFINITIONS: definitions,
} = require(`${dist}/src/features/project-administration/nativeProjectSchemaSchemaGenerated.js`);
const fixtureText = readFileSync(
  new URL('../../../../contracts/project-schema-v1/fixtures.json', import.meta.url),
  'utf8',
);
const fixture = fixtureText
  .split('\n')
  .map((line) => line.trim())
  .filter((line) => line.startsWith('{'))
  .map((raw) => ({
    raw: raw.replace(/,$/, ''),
    ...JSON.parse(raw.replace(/,$/, '')),
  }));
assert.equal(fixture.length, JSON.parse(fixtureText).length);
for (const row of fixture)
  test(`portable schema Rust/Python corpus: ${row.name}`, () => {
    const validate = () => {
      const parsed = parse(row.raw);
      const doc = freeze(
        typeof parsed.document === 'string' ? parse(parsed.document) : parsed.document,
      );
      checkDocument(doc, scope);
      if (Object.hasOwn(row, 'previous')) {
        assert.equal(row.expected_revision, row.previous?.revision ?? 0);
        successor(row.previous, doc);
      }
    };
    if (row.valid) assert.doesNotThrow(validate);
    else assert.throws(validate);
  });
test('generated scope and action methods retain canonical source, not Memory capability actions', () => {
  const canonical = JSON.parse(
    readFileSync(
      new URL(
        '../../../../shared/schemas/knowledge/native-knowledge-definitions-1.v1.schema.json',
        import.meta.url,
      ),
      'utf8',
    ),
  ).$defs.NativeKnowledgeScope;
  const { ['x-rust-name']: unused, ...shape } = canonical;
  const {
    ['x-rust-name']: unused2,
    ['x-rust-type']: unused3,
    ...generated
  } = definitions.NativeProjectSchemaScope;
  assert.deepEqual(generated, shape);
  assert.equal(Object.keys(actions).length, 5);
  for (const action of Object.values(actions)) {
    assert.equal(action.method, 'POST');
    assert.match(action.path, /^\/api\/v1\/knowledge\/schema\//);
  }
});
test('strict JSON rejects duplicate keys, escaped key aliases, unsafe numbers and integer token drift', () => {
  for (const raw of [
    '{"a":1,"a":2}',
    '{"a":1,"\\u0061":2}',
    '{"scope":{"generation":1e0}}',
    '{"scope":{"context_revision":-0}}',
    '{"x":9007199254740992}',
    '{"x":NaN}',
    '{"x":1} true',
  ])
    assert.throws(() => parse(raw));
  assert.deepEqual(
    parse('{"result":{"document":{"entity_types":[{"schema":{"minimum":0.25}}]}}}'),
    { result: { document: { entity_types: [{ schema: { minimum: 0.25 } }] } } },
  );
});
test('prepared command preserves explicit intent and is deeply frozen before awaiting', () => {
  const input = {
    scope,
    change_id: change,
    expected_revision: 0,
    document: structuredClone(document),
  };
  const command = prepare('schema_bootstrap', input);
  input.document.deleted = true;
  assert.equal(command.document.deleted, false);
  assert.ok(Object.isFrozen(command.document.entity_types));
  for (const body of [
    { ...input, actor_id: actor },
    { ...input, scope: undefined },
    { ...input, change_id: 'legacy' },
    { ...input, expected_revision: 1 },
  ])
    assert.throws(() => prepare('schema_bootstrap', body));
  let accesses = 0;
  const getter = {
    get scope() {
      accesses++;
      return scope;
    },
  };
  assert.throws(() => prepare('schema_read', getter));
  assert.equal(accesses, 0);
  const cyclic = {};
  cyclic.self = cyclic;
  assert.throws(() => freeze(cyclic));
});
test('decoder rejects foreign scope, actor, receipt identity and history gaps/cursors', () => {
  const request = { scope, change_id: change, expected_revision: 0, document };
  const valid = envelope('schema_bootstrap', { receipt });
  assert.deepEqual(decode('schema_bootstrap', valid, request, actor), valid);
  for (const edit of [
    (v) => (v.scope.project_id = 'foreign'),
    (v) => (v.actor_id = 'foreign'),
    (v) => (v.result.receipt.change_id = document.schema_id),
    (v) => (v.result.receipt.sequence = 2),
    (v) => (v.result.extra = true),
    (v) => (v.result.receipt.document.revision = 2),
  ]) {
    const bad = structuredClone(valid);
    edit(bad);
    assert.throws(() => decode('schema_bootstrap', bad, request, actor));
  }
  const hrequest = { scope, after_revision: 0, limit: 1 };
  const history = envelope('schema_history', {
    schema_id: document.schema_id,
    after_revision: 0,
    upper_revision: 2,
    next_after_revision: 1,
    has_more: true,
    items: [receipt],
  });
  assert.deepEqual(decode('schema_history', history, hrequest, actor), history);
  for (const edit of [
    (v) => (v.result.next_after_revision = 2),
    (v) => (v.result.has_more = false),
    (v) => (v.result.schema_id = null),
    (v) => (v.result.items = []),
    (v) => (v.result.items[0].sequence = 2),
  ]) {
    const bad = structuredClone(history);
    edit(bad);
    assert.throws(() => decode('schema_history', bad, hrequest, actor));
  }
  assert.deepEqual(decodeCap(capability, scope, actor), capability);
  const duplicate = structuredClone(capability);
  duplicate.result.allowed_actions[1] = duplicate.result.allowed_actions[0];
  assert.throws(() => decodeCap(duplicate, scope, actor));
});
test(
  'real Rust HTTP producer responses decode in TypeScript',
  { skip: !process.env.NATIVE_PROJECT_SCHEMA_RPC_FIXTURE },
  () => {
    const produced = JSON.parse(
      readFileSync(process.env.NATIVE_PROJECT_SCHEMA_RPC_FIXTURE, 'utf8'),
    );
    decodeCap(produced.capabilities, produced.scope, produced.actor);
    for (const row of produced.cases) {
      const prepared = prepare(row.action, row.request);
      assert.deepEqual(decode(row.action, row.response, prepared, produced.actor), row.response);
    }
  },
);

test('history rejects repeated actor/change identity and a revision after terminal deletion', () => {
  const request = { scope, after_revision: 0, limit: 2 };
  const next = { ...receipt, sequence: 2, document: { ...document, revision: 2 } };
  const history = envelope('schema_history', {
    schema_id: document.schema_id,
    after_revision: 0,
    upper_revision: 2,
    next_after_revision: 2,
    has_more: false,
    items: [receipt, next],
  });
  assert.throws(() => decode('schema_history', history, request, actor));
  next.change_id = '00000000-0000-4000-8000-000000000003';
  assert.doesNotThrow(() => decode('schema_history', history, request, actor));
  next.document.deleted = true;
  assert.doesNotThrow(() => decode('schema_history', history, request, actor));
  history.result.upper_revision = 3;
  history.result.has_more = true;
  assert.throws(() => decode('schema_history', history, request, actor));
  assert.throws(() =>
    decode(
      'schema_read',
      envelope('schema_read', { document: { ...document, deleted: true } }),
      { scope },
      actor,
    ),
  );
});
