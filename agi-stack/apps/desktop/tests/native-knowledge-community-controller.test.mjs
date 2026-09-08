import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { setImmediate } from 'node:timers/promises';
import { nativeScope, projectScope } from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const dist = process.env.COMMUNITY_UI_DIST ?? '/tmp/agistack-desktop-test-dist';
const { createNativeKnowledgeCommunityController } = require(
  `${dist}/src/features/project-knowledge/nativeKnowledgeCommunityController.js`,
);
const actions = [
  'community_active',
  'community_build',
  'community_audit',
  'create_community_build',
  'select_community_build',
  'process_community_one',
  'retry_community',
  'activate_community_build',
  'community_builds',
];
const response = (result, scope = nativeScope) => ({
  contract_version: '1.0.0',
  scope,
  result,
});
const deferred = () => {
  let resolve;
  const promise = new Promise((a) => {
    resolve = a;
  });
  return { promise, resolve };
};
function fixture(options = {}) {
  const state = {
    active: {
      selection: {
        requested_build_id: 'build',
        active_build_id: null,
        revision: 1,
      },
      current_status: null,
      stale_build_id: null,
    },
    page: {
      build: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        build_id: 'build',
        graph_digest: 'graph',
        candidate_count: 21,
        state: 'pending',
        created_at_ms: 100,
      },
      status: {
        build_id: 'build',
        state: 'failed',
        candidate_count: 21,
        ready_count: 0,
        insufficient_evidence_count: 0,
        failed_count: 1,
      },
      current_graph: true,
      items: [
        {
          candidate_id: 'candidate',
          member_count: 2,
          job: {
            build_id: 'build',
            candidate_id: 'candidate',
            state: 'failed',
            attempt: 2,
            failure: 'execution_failed',
          },
          result: null,
          audit: null,
        },
      ],
      offset: 0,
      limit: 20,
      total: 21,
    },
    workspaces: [{ id: 'workspace', name: 'Explicit workspace' }],
  };
  const writes = [],
    reads = [],
    inputReads = [];
  const binding = {
    authority: {
      scope: projectScope,
      userId: 'user',
      sessionId: 'session',
      contextRevision: 7,
      generationDigest: 'native-digest',
      available: true,
      allowedActions: actions,
      ...options.authority,
    },
    processingClient: {
      query: async (scope, query, request) => {
        reads.push({ scope, query, request });
        const custom = await options.query?.(query, request);
        if (custom) return custom;
        if (query.operation === 'community_active') return response(structuredClone(state.active));
        if (query.operation === 'community_builds')
          return response({
            page: {
              items: [{ ...state.page.build, build_id: 'orphan' }],
              total: 21,
              offset: query.offset,
              limit: query.limit,
            },
          });
        if (query.operation === 'community_build')
          return response({
            page: {
              ...structuredClone(state.page),
              offset: query.offset,
              build: { ...state.page.build, build_id: query.build_id },
            },
          });
        return response({
          audit: {
            build_id: query.build_id,
            candidate_id: query.candidate_id,
            attempt: query.attempt,
            status: 'failed',
            agent_id: 'agent',
            model_id: 'model',
            provider_id: 'provider',
            latency_ms: 4,
          },
        });
      },
    },
    processingCommandClient: {
      execute: async (scope, command, request) => {
        writes.push({ scope, command, request });
        const custom = await options.write?.(command, request);
        if (custom) return custom;
        if (command.operation === 'create_community_build')
          return response({
            build: { ...state.page.build, build_id: 'created' },
          });
        if (command.operation === 'activate_community_build')
          return response({
            activated: false,
            build_id: command.build_id,
            selection_revision: 1,
          });
        if (command.operation === 'process_community_one') return response({ receipt: null });
        return response({ accepted: true });
      },
    },
    processingInputsClient: {
      load: async (scope, request) => {
        inputReads.push({ scope, request });
        return {
          scope: nativeScope,
          embeddingModels: { availability: 'unavailable', items: [] },
          workspaces: {
            availability: 'available',
            items: structuredClone(state.workspaces),
          },
        };
      },
    },
  };
  return {
    c: createNativeKnowledgeCommunityController(binding),
    writes,
    reads,
    inputReads,
    state,
  };
}

test('community refresh is read-only and paginates the viewed build', async () => {
  const f = fixture();
  await f.c.refresh();
  await f.c.refresh('build', 20);
  assert.equal(f.c.getSnapshot().page.offset, 20);
  assert.equal(f.writes.length, 0);
  assert.equal(f.reads.at(-1).request.expectedScope.profile_id, nativeScope.profile_id);
});
test('create needs explicit review and confirm, accepts schema upper bound', async () => {
  const f = fixture();
  await f.c.refresh();
  await f.c.review('create_community_build', { minSize: 4096 });
  const command = f.c.getSnapshot().command;
  assert.equal(command.min_community_size, 4096);
  assert.equal(f.writes.length, 0);
  await f.c.confirm();
  assert.deepEqual(f.writes[0].command, command);
  assert.equal(f.c.getSnapshot().page.build.build_id, 'created');
  assert.equal(f.c.getSnapshot().recoveredUnknown, false);
  assert.equal(f.c.getSnapshot().outcome, 'accepted');
});
test('selection CAS is rechecked immediately before write', async () => {
  const f = fixture();
  await f.c.refresh();
  await f.c.review('select_community_build');
  assert.equal(f.c.getSnapshot().command.expected_selection_revision, 1);
  f.state.active.selection.revision = 2;
  await f.c.confirm();
  assert.equal(f.writes.length, 0);
  assert.equal(f.c.getSnapshot().error, 'conflict');
});
test('retry is fenced to the exact failed candidate attempt', async () => {
  const f = fixture();
  await f.c.refresh();
  await f.c.review('retry_community', { candidateId: 'candidate' });
  assert.equal(f.c.getSnapshot().command.expected_attempt, 2);
  f.state.page.items[0].job.attempt = 3;
  await f.c.confirm();
  assert.equal(f.writes.length, 0);
  assert.equal(f.c.getSnapshot().error, 'conflict');
});
test('retry acceptance never dispatches a provider', async () => {
  const f = fixture();
  await f.c.refresh();
  await f.c.review('retry_community', { candidateId: 'candidate' });
  await f.c.confirm();
  assert.deepEqual(
    f.writes.map((call) => call.command.operation),
    ['retry_community'],
  );
});
test('processing requires explicit workspace from fresh authorized directory', async () => {
  const f = fixture();
  await f.c.refresh();
  await f.c.review('process_community_one');
  assert.equal(f.c.getSnapshot().command, null);
  assert.equal(f.writes.length, 0);
  await f.c.review('process_community_one', { workspaceId: 'forged' });
  assert.equal(f.c.getSnapshot().command, null);
  await f.c.review('process_community_one', { workspaceId: 'workspace' });
  f.state.workspaces = [];
  await f.c.confirm();
  assert.equal(f.writes.length, 0);
  assert.equal(f.c.getSnapshot().error, 'conflict');
  assert.ok(f.inputReads.every((call) => call.request.operation === 'process_community_one'));
});
test('one-candidate process reports no work without automatic retry', async () => {
  const f = fixture();
  await f.c.refresh();
  await f.c.review('process_community_one', { workspaceId: 'workspace' });
  await f.c.confirm();
  assert.equal(f.writes.length, 1);
  assert.equal(f.c.getSnapshot().outcome, 'noWork');
});
test('activation requires completed current selected build and reports false receipt', async () => {
  const f = fixture();
  await f.c.refresh();
  await f.c.review('activate_community_build');
  assert.equal(f.c.getSnapshot().command, null);
  f.state.page.status.state = 'completed';
  await f.c.refresh();
  await f.c.review('activate_community_build');
  await f.c.confirm();
  assert.equal(f.writes.length, 1);
  assert.equal(f.c.getSnapshot().outcome, 'notActivated');
});
test('stale graph remains readable but cannot be selected', async () => {
  const f = fixture();
  f.state.page.current_graph = false;
  await f.c.refresh();
  await f.c.review('select_community_build');
  assert.equal(f.c.getSnapshot().command, null);
  assert.equal(f.c.getSnapshot().page.current_graph, false);
  assert.equal(f.writes.length, 0);
});
test('uncertain write blocks commands until refresh without replay', async () => {
  const f = fixture({
    write: async () => {
      throw Error('connection_lost');
    },
  });
  await f.c.refresh();
  await f.c.review('select_community_build');
  await f.c.confirm();
  assert.equal(f.c.getSnapshot().recoveryRequired, true);
  await f.c.review('create_community_build');
  await f.c.confirm();
  assert.equal(f.writes.length, 1);
  await f.c.refresh();
  assert.equal(f.c.getSnapshot().recoveryRequired, false);
  assert.equal(f.c.getSnapshot().recoveredUnknown, true);
  assert.equal(f.writes.length, 1);
});
test('post-write refresh failure blocks commands but keeps known accepted receipt', async () => {
  let written = false;
  const f = fixture({
    write: async () => {
      written = true;
    },
    query: async () => {
      if (written) throw Error('offline');
    },
  });
  await f.c.refresh();
  await f.c.review('select_community_build');
  await f.c.confirm();
  assert.equal(f.c.getSnapshot().recoveryRequired, true);
  written = false;
  await f.c.refresh();
  assert.equal(f.c.getSnapshot().recoveredUnknown, false);
  assert.equal(f.writes.length, 1);
});
test('generation mismatch clears private data and disables obsolete binding', async () => {
  let foreign = false;
  const f = fixture({
    query: async () => (foreign ? response({}, { ...nativeScope, generation: 5 }) : undefined),
  });
  await f.c.refresh();
  foreign = true;
  await f.c.refresh();
  assert.equal(f.c.getSnapshot().phase, 'unavailable');
  assert.equal(f.c.getSnapshot().page, null);
  foreign = false;
  await f.c.refresh();
  await f.c.review('create_community_build');
  assert.equal(f.c.getSnapshot().phase, 'unavailable');
  assert.equal(f.writes.length, 0);
});
test('stop fences late reads and allows a clean activation', async () => {
  const gate = deferred();
  let delayed = true;
  const f = fixture({
    query: async () => (delayed ? gate.promise : undefined),
  });
  const pending = f.c.refresh();
  await setImmediate();
  f.c.stop();
  delayed = false;
  f.c.activate();
  await f.c.refresh();
  gate.resolve(
    response({
      selection: {
        requested_build_id: 'late',
        active_build_id: null,
        revision: 9,
      },
    }),
  );
  await pending;
  assert.equal(f.c.getSnapshot().page.build.build_id, 'build');
});
test('stop during write fences late publication and requires refresh after activation', async () => {
  const gate = deferred();
  const f = fixture({ write: async () => gate.promise });
  await f.c.refresh();
  await f.c.review('select_community_build');
  const pending = f.c.confirm();
  await setImmediate();
  f.c.stop();
  gate.resolve(response({ accepted: true }));
  await pending;
  assert.equal(f.c.getSnapshot().page, null);
  assert.equal(f.c.getSnapshot().recoveryRequired, true);
  f.c.activate();
  await f.c.refresh();
  assert.equal(f.c.getSnapshot().recoveredUnknown, true);
  assert.equal(f.writes.length, 1);
});
test('audit uses displayed candidate and exact attempt; read-only authority cannot write', async () => {
  const f = fixture({ authority: { allowedActions: actions.slice(0, 3) } });
  await f.c.refresh();
  await f.c.loadAudit('forged', 2);
  assert.equal(f.c.getSnapshot().audit, null);
  await f.c.loadAudit('candidate', 2);
  assert.equal(f.c.getSnapshot().audit.attempt, 2);
  await f.c.review('retry_community', { candidateId: 'candidate' });
  assert.equal(f.writes.length, 0);
});
test('missing session fails closed before any read', async () => {
  const f = fixture({ authority: { sessionId: null } });
  await f.c.refresh();
  assert.equal(f.c.getSnapshot().phase, 'unavailable');
  assert.equal(f.reads.length, 0);
});

test('uncertain create retains the same idempotency key for explicit recovery, refresh cannot lose it', async () => {
  let first = true;
  const f = fixture({
    write: async () => {
      if (first) {
        first = false;
        throw Error('receipt_lost_after_commit');
      }
    },
  });
  await f.c.refresh();
  await f.c.review('create_community_build', { minSize: 3 });
  const command = f.c.getSnapshot().command;
  await f.c.confirm();
  assert.equal(f.c.getSnapshot().recoverableCreate, true);
  await f.c.refresh();
  assert.equal(f.c.getSnapshot().recoveryRequired, true);
  await f.c.review('create_community_build', { minSize: 4 });
  assert.equal(f.c.getSnapshot().command, null);
  assert.equal(f.writes.length, 1);
  await f.c.recoverCreate();
  assert.deepEqual(
    f.writes.map((call) => call.command),
    [command, command],
  );
  assert.equal(f.c.getSnapshot().page.build.build_id, 'created');
  assert.equal(f.c.getSnapshot().recoveryRequired, false);
  assert.equal(f.c.getSnapshot().recoverableCreate, false);
});
test('uncertain create recovery rejects scope drift without replay', async () => {
  let drift = false;
  const f = fixture({
    write: async () => {
      throw Error('lost');
    },
    query: async () => (drift ? response({}, { ...nativeScope, digest: 'changed' }) : undefined),
  });
  await f.c.refresh();
  await f.c.review('create_community_build');
  await f.c.confirm();
  drift = true;
  await f.c.recoverCreate();
  assert.equal(f.writes.length, 1);
  assert.equal(f.c.getSnapshot().phase, 'unavailable');
});
test('retry review rejects attempt changed since the displayed selection', async () => {
  const f = fixture();
  await f.c.refresh();
  f.state.page.items[0].job.attempt = 3;
  await f.c.review('retry_community', { candidateId: 'candidate' });
  assert.equal(f.c.getSnapshot().command, null);
  assert.equal(f.c.getSnapshot().error, 'conflict');
});

test('known create receipt keeps its build ID when the following read fails', async () => {
  let written = false;
  const f = fixture({
    write: async () => {
      written = true;
    },
    query: async () => {
      if (written) throw Error('offline');
    },
  });
  await f.c.refresh();
  await f.c.review('create_community_build');
  await f.c.confirm();
  assert.equal(f.c.getSnapshot().viewedBuildId, 'created');
  assert.equal(f.c.getSnapshot().page, null);
  written = false;
  await f.c.refresh();
  assert.equal(f.c.getSnapshot().page.build.build_id, 'created');
  assert.equal(f.writes.length, 1);
  assert.equal(f.c.getSnapshot().recoveredUnknown, false);
});

test('new controller discovers unselected durable builds without selecting or executing', async () => {
  const f = fixture();
  f.state.active.selection = { requested_build_id: null, active_build_id: null, revision: 0 };
  await f.c.refresh();
  assert.equal(f.c.getSnapshot().page, null);
  await f.c.loadHistory();
  assert.equal(f.c.getSnapshot().history.items[0].build_id, 'orphan');
  assert.equal(f.c.getSnapshot().page, null);
  assert.equal(f.writes.length, 0);
  await f.c.loadHistory(20);
  assert.equal(f.c.getSnapshot().history.offset, 20);
  await f.c.refresh('orphan');
  assert.equal(f.c.getSnapshot().page.build.build_id, 'orphan');
  assert.equal(f.c.getSnapshot().active.selection.requested_build_id, null);
  assert.equal(f.writes.length, 0);
});
test('history failure preserves open build and an uncertain write fence', async () => {
  const f = fixture({
    write: async () => {
      throw Error('lost');
    },
    query: async (query) => {
      if (query.operation === 'community_builds') throw Error('history_unavailable');
    },
  });
  await f.c.refresh();
  await f.c.review('select_community_build');
  await f.c.confirm();
  await f.c.loadHistory();
  assert.equal(f.c.getSnapshot().page.build.build_id, 'build');
  assert.equal(f.c.getSnapshot().recoveryRequired, true);
  assert.equal(f.writes.length, 1);
});
test('history response with foreign tenant invalidates the obsolete binding', async () => {
  const f = fixture({
    query: async (query) =>
      query.operation === 'community_builds'
        ? response({
            page: {
              items: [{ tenant_id: 'foreign', project_id: 'project-1' }],
              offset: 0,
              limit: 20,
              total: 1,
            },
          })
        : undefined,
  });
  await f.c.refresh();
  await f.c.loadHistory();
  assert.equal(f.c.getSnapshot().phase, 'unavailable');
  assert.equal(f.c.getSnapshot().page, null);
});

test('reactivation cannot restore an invalidated authority binding', async () => {
  const f = fixture({ query: async () => response({}, { ...nativeScope, project_id: 'other' }) });
  await f.c.refresh();
  f.c.stop();
  f.c.activate();
  await f.c.refresh();
  assert.equal(f.c.getSnapshot().phase, 'unavailable');
  assert.deepEqual(f.c.getSnapshot().allowedActions, []);
});
