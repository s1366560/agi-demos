import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { config, capability, json } from './nativeKnowledgeProcessingFixtures.mjs';

const require = createRequire(import.meta.url);
const dist = process.env.AGISTACK_KNOWLEDGE_HTTP_TEST_DIST ?? '/tmp/agistack-desktop-test-dist';
const v = require(`${dist}/src/features/project-knowledge/nativeKnowledgeProcessingValidation.js`);
const { createDesktopNativeKnowledgeProcessingHttpV2: create } = require(
  `${dist}/src/plugins/desktopNativeKnowledgeProcessingHttpV2.js`,
);
// Captured from the Rust RPC test with real HttpLlm/policy/route dispatch.
// Set this environment variable to verify a newly produced run without rewriting the fixture.
const fixture = JSON.parse(
  readFileSync(
    process.env.AGISTACK_COMMUNITY_RPC_FIXTURE ??
      new URL('./fixtures/native-knowledge-community-rpc.v1.json', import.meta.url),
    'utf8',
  ),
);
const scope = {
  authority: 'local',
  tenantId: fixture.scope.tenant_id,
  projectId: fixture.scope.project_id,
};
const native = fixture.scope;
const buildCase = fixture.query_cases.find((c) => c.query.operation === 'community_build');
const page = buildCase.response.result.page;
const historyCase = fixture.query_cases.find((c) => c.query.operation === 'community_builds');
assert.ok(historyCase, 'Rust RPC fixture must include the build history query');
const queries = fixture.query_cases;
const buildId = page.build.build_id;
const candidateId = page.items[0].candidate_id;
const commands = [
  ...fixture.command_cases,
  {
    command: {
      operation: 'create_community_build',
      idempotency_key: 'community-fixture',
      min_community_size: 2,
    },
    response: { result: { build: page.build } },
  },
  {
    command: {
      operation: 'select_community_build',
      build_id: buildId,
      expected_selection_revision: 0,
    },
    response: {
      result: {
        selection: {
          requested_build_id: buildId,
          active_build_id: null,
          revision: 1,
        },
      },
    },
  },
  {
    command: {
      operation: 'retry_community',
      build_id: buildId,
      candidate_id: candidateId,
      expected_attempt: 1,
    },
    response: {
      result: {
        accepted: true,
        build_id: buildId,
        candidate_id: candidateId,
        attempt: 1,
      },
    },
  },
  {
    command: {
      operation: 'activate_community_build',
      build_id: buildId,
      expected_selection_revision: 1,
    },
    response: {
      result: {
        activated: true,
        build_id: buildId,
        selection_revision: 1,
      },
    },
  },
].map((c) => ({
  ...c,
  response: { contract_version: '1.0.0', scope: native, ...c.response },
}));
const cases = [...queries, ...commands];
const op = (row) => row.query ?? row.command;
const prepare = (row, value = op(row)) =>
  (row.query ? v.prepareNativeKnowledgeProcessingQuery : v.prepareNativeKnowledgeProcessingCommand)(
    value,
    scope,
  );
const validate = (row, value = row.response) =>
  (row.query
    ? v.requireNativeKnowledgeProcessingQueryResponse
    : v.requireNativeKnowledgeProcessingCommandResponse)(value, op(row), scope, native);
const change = (row, fn) => {
  const copy = structuredClone(row.response);
  fn(copy.result);
  return copy;
};
const rejectPage = (fn) =>
  assert.throws(
    () =>
      validate(
        buildCase,
        change(buildCase, (r) => fn(r.page)),
      ),
    (e) => e.message === 'native_knowledge_response_invalid',
  );

test('build history binds offset, limit, exact row counts and immutable scoped receipts', () => {
  validate(historyCase);
  for (const patch of [
    { offset: -1 },
    { offset: 1.5 },
    { offset: 4294967296 },
    { limit: 0 },
    { limit: 101 },
    { build_id: 'unsupported' },
  ])
    assert.throws(() => prepare(historyCase, { ...historyCase.query, ...patch }));
  for (const mutate of [
    (p) => {
      p.offset++;
    },
    (p) => {
      p.limit++;
    },
    (p) => {
      p.total++;
    },
    (p) => {
      p.items.pop();
    },
    (p) => {
      p.items[0].tenant_id = 'foreign';
    },
    (p) => {
      p.items[0].project_id = 'foreign';
    },
    (p) => {
      p.items[0].state = 'completed';
    },
    (p) => {
      p.items[0].candidate_count = 0;
      p.items[0].state = 'pending';
    },
  ])
    assert.throws(() =>
      validate(
        historyCase,
        change(historyCase, (r) => mutate(r.page)),
      ),
    );
  const beyond = { ...historyCase, query: { ...historyCase.query, offset: 10 } };
  validate(
    beyond,
    change(historyCase, (r) => {
      r.page.offset = 10;
      r.page.items = [];
    }),
  );
  validate(
    historyCase,
    change(historyCase, (r) => {
      r.page.total = 0;
      r.page.items = [];
    }),
  );
});

test('build history orders newest first, then exact binary build ID ascending, without duplicates', () => {
  const sameTime = change(historyCase, (r) => {
    r.page.items = ['build-A', 'build-B'].map((build_id) => ({ ...page.build, build_id }));
    r.page.total = 2;
  });
  validate(historyCase, sameTime);
  for (const mutate of [
    (p) => {
      p.items.reverse();
    },
    (p) => {
      p.items[1].build_id = p.items[0].build_id;
    },
    (p) => {
      p.items[1].created_at_ms++;
    },
  ]) {
    const bad = structuredClone(sameTime);
    mutate(bad.result.page);
    assert.throws(() => validate(historyCase, bad));
  }
  // SQLite BINARY compares UTF-8, not JavaScript's UTF-16 or the user's locale.
  const unicode = structuredClone(sameTime);
  unicode.result.page.items[0].build_id = '\uE000';
  unicode.result.page.items[1].build_id = '\u{10000}';
  validate(historyCase, unicode);
  unicode.result.page.items.reverse();
  assert.throws(() => validate(historyCase, unicode));
});

for (const row of cases) {
  test(`${op(row).operation} accepts the scoped producer contract and freezes it`, () => {
    assert.deepEqual(prepare(row), op(row));
    assert.deepEqual(validate(row), row.response);
    assert.ok(Object.isFrozen(validate(row).result));
    for (const patch of [{ extra: true }, { tenant_id: 'foreign' }])
      assert.throws(() => prepare(row, { ...op(row), ...patch }));
    assert.throws(() =>
      validate(row, {
        ...row.response,
        result: { ...row.response.result, secret: 'x' },
      }),
    );
    assert.throws(() =>
      validate(row, {
        ...row.response,
        scope: { ...native, generation: native.generation + 1 },
      }),
    );
  });
}

test('community request identifiers, attempts, pagination and selection CAS reject invalid inputs', () => {
  for (const row of cases) {
    for (const key of ['build_id', 'workspace_id', 'idempotency_key'])
      if (key in op(row))
        for (const value of ['', ' ', ' trailing '])
          assert.throws(() => prepare(row, { ...op(row), [key]: value }));
    for (const key of ['attempt', 'expected_attempt'])
      if (key in op(row))
        for (const value of [0, -1, 1.5, 4294967296])
          assert.throws(() => prepare(row, { ...op(row), [key]: value }));
    if ('candidate_id' in op(row))
      for (const value of ['x', 'g'.repeat(64), 'A'.repeat(64)])
        assert.throws(() => prepare(row, { ...op(row), candidate_id: value }));
    if ('expected_selection_revision' in op(row)) {
      const omitted = { ...op(row) };
      delete omitted.expected_selection_revision;
      assert.throws(() => prepare(row, omitted));
      for (const value of [-1, 1.5, Number.MAX_SAFE_INTEGER + 1])
        assert.throws(() => prepare(row, { ...op(row), expected_selection_revision: value }));
    }
  }
  for (const [key, values] of [
    ['offset', [-1, 1.5, 4294967296]],
    ['limit', [0, 101, 1.5]],
  ])
    for (const value of values)
      assert.throws(() => prepare(buildCase, { ...buildCase.query, [key]: value }));
  const select = commands.find((c) => c.command.operation === 'select_community_build');
  assert.throws(() =>
    prepare(select, {
      ...select.command,
      expected_selection_revision: Number.MAX_SAFE_INTEGER,
    }),
  );
});

test('community page binds request, receipt, status, counters and candidate identities', () => {
  for (const fn of [
    (p) => {
      p.build.build_id = 'other';
    },
    (p) => {
      p.build.tenant_id = 'foreign';
    },
    (p) => {
      p.build.project_id = 'foreign';
    },
    (p) => {
      p.build.state = 'completed_empty';
    },
    (p) => {
      p.status.build_id = 'other';
    },
    (p) => {
      p.status.candidate_count++;
    },
    (p) => {
      p.status.ready_count = 0;
    },
    (p) => {
      p.status.failed_count = 1;
    },
    (p) => {
      p.status.state = 'pending';
    },
    (p) => {
      p.total++;
    },
    (p) => {
      p.offset++;
    },
    (p) => {
      p.limit++;
    },
    (p) => {
      p.items = [];
    },
    (p) => {
      p.items.push(structuredClone(p.items[0]));
    },
    (p) => {
      p.items[0].candidate_id = 'b'.repeat(64);
    },
    (p) => {
      p.items[0].member_count++;
    },
  ])
    rejectPage(fn);
  const stale = change(buildCase, (r) => {
    r.page.current_graph = false;
  });
  assert.doesNotThrow(() => validate(buildCase, stale));
  const missing = change(buildCase, (r) => {
    r.page = null;
  });
  assert.doesNotThrow(() => validate(buildCase, missing));
});

test('completed job, result and applied audit agree on attempt, identifiers and terminal time', () => {
  for (const field of ['job', 'result', 'audit']) {
    for (const key of ['build_id', 'candidate_id', 'attempt'])
      rejectPage((p) => {
        p.items[0][field][key] =
          key === 'attempt' ? 2 : key === 'candidate_id' ? 'c'.repeat(64) : 'other';
      });
  }
  for (const fn of [
    (i) => {
      i.job.state = 'pending';
    },
    (i) => {
      i.job.failure = 'execution_failed';
    },
    (i) => {
      i.job.attempt = 0;
    },
    (i) => {
      i.result = null;
    },
    (i) => {
      i.audit = null;
    },
    (i) => {
      i.result.finished_at_ms++;
    },
    (i) => {
      i.audit.status = 'running';
    },
    (i) => {
      i.result.submission.build_id = 'other';
    },
    (i) => {
      i.result.submission.candidate_id = 'd'.repeat(64);
    },
    (i) => {
      i.result.submission.graph_digest = 'e'.repeat(64);
    },
  ])
    rejectPage((p) => fn(p.items[0]));
});

test('members and evidence retain exact source scope, revision, sequence and entity identity', () => {
  for (const group of ['members', 'evidence'])
    for (const key of ['tenant_id', 'project_id', 'memory_id', 'revision', 'change_sequence'])
      rejectPage((p) => {
        const submission = p.items[0].result.submission;
        const source = (group === 'members' ? submission.members : submission.decision.evidence)[0]
          .source;
        source[key] = typeof source[key] === 'number' ? source[key] + 1 : 'foreign';
      });
  rejectPage((p) => {
    p.items[0].result.submission.members[1] = structuredClone(
      p.items[0].result.submission.members[0],
    );
  });
  rejectPage((p) => {
    p.items[0].result.submission.decision.evidence[0].entity_index = 9;
  });
  rejectPage((p) => {
    p.items[0].result.submission.decision.evidence[0].relationship_index = -1;
  });
  for (const field of ['name', 'summary', 'rationale'])
    rejectPage((p) => {
      p.items[0].result.submission.decision[field] = '   ';
    });
});

test('pending, retry, running, failed, empty and insufficient evidence states remain representable', () => {
  for (const state of ['pending', 'leased', 'failed']) {
    const response = change(buildCase, (r) => {
      const p = r.page,
        i = p.items[0];
      p.status.ready_count = 0;
      p.status.state = state === 'failed' ? 'failed' : 'pending';
      p.status.failed_count = state === 'failed' ? 1 : 0;
      i.result = null;
      i.audit = null;
      i.job.state = state;
      i.job.failure = state === 'failed' ? 'execution_failed' : null;
    });
    validate(buildCase, response);
    // A requeued job retains its previous failed audit for the same attempt.
    response.result.page.items[0].audit = {
      ...page.items[0].audit,
      status: 'failed',
      failure: 'cancelled',
    };
    validate(buildCase, response);
  }
  const running = change(buildCase, (r) => {
    const i = r.page.items[0];
    r.page.status.ready_count = 0;
    r.page.status.state = 'pending';
    i.job.state = 'leased';
    i.result = null;
    Object.assign(i.audit, {
      status: 'running',
      finished_at_ms: null,
      latency_ms: null,
    });
  });
  validate(buildCase, running);
  const empty = change(buildCase, (r) => {
    const p = r.page;
    p.build.candidate_count = 0;
    p.build.state = 'completed_empty';
    Object.assign(p.status, {
      state: 'completed_empty',
      candidate_count: 0,
      ready_count: 0,
    });
    p.items = [];
    p.total = 0;
  });
  validate(buildCase, empty);
  const insufficient = change(buildCase, (r) => {
    r.page.status.ready_count = 0;
    r.page.status.insufficient_evidence_count = 1;
    r.page.items[0].result.submission.decision = {
      status: 'insufficient_evidence',
      rationale: 'No supported name.',
      evidence: [],
    };
  });
  validate(buildCase, insufficient);
});

test('partial pages bound each visible state against global counts and allow offset beyond total', () => {
  const response = change(buildCase, (r) => {
    r.page.limit = 1;
    r.page.total = 2;
    r.page.build.candidate_count = 2;
    r.page.status.candidate_count = 2;
    r.page.status.state = 'pending';
  });
  const row = { ...buildCase, query: { ...buildCase.query, limit: 1 } };
  validate(row, response);
  response.result.page.status.ready_count = 0;
  assert.throws(() => validate(row, response));
  const beyond = change(buildCase, (r) => {
    r.page.offset = 10;
    r.page.items = [];
  });
  validate({ ...buildCase, query: { ...buildCase.query, offset: 10 } }, beyond);
});

test('different page candidates cannot repeat IDs or claim the same frozen entity', () => {
  const duplicate = change(buildCase, (r) => {
    const p = r.page;
    p.build.candidate_count = p.total = p.status.candidate_count = p.status.ready_count = 2;
    p.items.push(structuredClone(p.items[0]));
  });
  assert.throws(() => validate(buildCase, duplicate));
  const second = duplicate.result.page.items[1];
  second.candidate_id = 'f'.repeat(64);
  for (const value of [second.job, second.audit, second.result, second.result.submission])
    value.candidate_id = second.candidate_id;
  assert.throws(() => validate(buildCase, duplicate));
});

test('active selection reports exactly one current completed build or the matching stale build', () => {
  const row = queries.find((c) => c.query.operation === 'community_active');
  for (const fn of [
    (r) => {
      r.selection.revision = 0;
    },
    (r) => {
      r.selection.requested_build_id = null;
    },
    (r) => {
      r.selection.active_build_id = null;
    },
    (r) => {
      r.current_status.build_id = 'other';
    },
    (r) => {
      r.current_status = null;
    },
    (r) => {
      r.stale_build_id = buildId;
    },
    (r) => {
      r.current_status.state = 'pending';
    },
  ])
    assert.throws(() => validate(row, change(row, fn)));
  validate(
    row,
    change(row, (r) => {
      r.current_status = null;
      r.stale_build_id = buildId;
    }),
  );
  validate(
    row,
    change(row, (r) => {
      r.current_status = null;
      r.selection = {
        requested_build_id: null,
        active_build_id: null,
        revision: 0,
      };
    }),
  );
});

test('audit summaries enforce identity, time, terminal status and omit private payloads', () => {
  const row = queries.find((c) => c.query.operation === 'community_audit');
  for (const patch of [
    { attempt: 2 },
    { build_id: 'other' },
    { candidate_id: 'f'.repeat(64) },
    { agent_id: ' ' },
    { provider_id: ' ' },
    { model_id: ' ' },
    { status: 'running' },
    { failure: 'cancelled' },
    { response_digest: 'a'.repeat(64) },
    { finished_at_ms: 0 },
    { latency_ms: null },
    { tool_name: 'other' },
    { invocation: {} },
    { submission: {} },
  ])
    assert.throws(() =>
      validate(
        row,
        change(row, (r) => Object.assign(r.audit, patch)),
      ),
    );
  validate(
    row,
    change(row, (r) => {
      r.audit = null;
    }),
  );
});

test('commands bind exact selection revisions, build IDs, candidate IDs and retry attempts', () => {
  for (const row of commands) {
    const operation = row.command.operation;
    if (operation === 'create_community_build') continue;
    const key =
      operation === 'process_community_one'
        ? 'receipt'
        : operation === 'select_community_build'
          ? 'selection'
          : null;
    const fields =
      operation === 'select_community_build'
        ? ['requested_build_id', 'revision']
        : operation === 'activate_community_build'
          ? ['build_id', 'selection_revision']
          : operation === 'retry_community'
            ? ['build_id', 'candidate_id', 'attempt']
            : ['build_id'];
    for (const field of fields)
      assert.throws(() =>
        validate(
          row,
          change(row, (r) => {
            const target = key ? r[key] : r;
            target[field] =
              typeof target[field] === 'number'
                ? target[field] + 1
                : field === 'candidate_id'
                  ? 'b'.repeat(64)
                  : 'other';
          }),
        ),
      );
  }
});

test('all community actions use the existing capability getter and commands require observed scope', async () => {
  let calls = 0,
    current;
  const original = globalThis.fetch;
  globalThis.fetch = async (url) => {
    calls++;
    if (String(url).endsWith('/context')) return json({ contract_version: '1.0.0', scope: native });
    return json(current.response);
  };
  const cap = {
    ...capability,
    authority_revision: native.context_revision,
    scope: {
      ...capability.scope,
      tenant_id: scope.tenantId,
      project_id: scope.projectId,
    },
    allowed_actions: cases.map((c) => op(c).operation),
  };
  const cfg = {
    ...config,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  };
  try {
    for (const row of cases) {
      current = row;
      const invoke = (a, options = { expectedScope: native }) =>
        (row.query ? a.queryProcessing : a.executeProcessing)(op(row), options);
      calls = 0;
      const adapter = create(cfg, scope, () => cap);
      assert.deepEqual(await invoke(adapter), row.response);
      assert.equal(calls, 3);
      calls = 0;
      await assert.rejects(
        invoke(
          create(cfg, scope, () => ({
            ...cap,
            allowed_actions: cap.allowed_actions.filter((action) => action !== op(row).operation),
          })),
        ),
        (e) => e.status === 501,
      );
      assert.equal(calls, 0);
      if (row.command) {
        await assert.rejects(
          invoke(adapter, {}),
          (e) => e.message === 'native_knowledge_expected_scope_required',
        );
        assert.equal(calls, 0);
      }
    }
  } finally {
    globalThis.fetch = original;
  }
});
