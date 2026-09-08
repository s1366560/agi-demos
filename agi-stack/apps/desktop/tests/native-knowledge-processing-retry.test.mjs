import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { setImmediate } from 'node:timers/promises';
import { nativeScope, projectScope } from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const dist = process.env.I5_DIAGNOSTICS_DIST ?? '/tmp/agistack-project-knowledge-test-dist';
const { createNativeKnowledgeProcessingRetryController } = require(
  `${dist}/src/features/project-knowledge/nativeKnowledgeProcessingRetryController.js`,
);
const { createNativeKnowledgeDiagnosticsController } = require(
  `${dist}/src/features/project-knowledge/nativeKnowledgeDiagnosticsController.js`,
);
const {
  prepareNativeKnowledgeProcessingQuery,
  prepareNativeKnowledgeProcessingCommand,
  requireNativeKnowledgeProcessingQueryResponse,
  requireNativeKnowledgeProcessingCommandResponse,
} = require(`${dist}/src/features/project-knowledge/nativeKnowledgeProcessingValidation.js`);
const source = {
  tenant_id: nativeScope.tenant_id,
  project_id: nativeScope.project_id,
  memory_id: 'failed-source',
  revision: 3,
  change_sequence: 9,
};
const selection = {
  scope: nativeScope,
  failure: { source, attempt: 2, failure: 'provider_unavailable' },
};
const command = { operation: 'retry_processing', source, expected_attempt: 2 };
const authority = {
  scope: projectScope,
  userId: 'user',
  sessionId: 'session',
  contextRevision: nativeScope.context_revision,
  generationDigest: nativeScope.digest,
  available: true,
  allowedActions: ['failed_processing', 'processing_task', 'retry_processing'],
};
const response = (operation, result) => ({
  contract_version: '1.0.0',
  scope: nativeScope,
  result,
});
function fixture(options = {}) {
  let state = {
    source,
    current: true,
    task: { state: 'failed', attempt: 2, failure: 'provider_unavailable' },
  };
  const queries = [],
    writes = [],
    notifications = [];
  const queryClient = {
    query: async (scope, query, request) => {
      queries.push({ scope, query, request });
      const custom = await options.query?.(query, request, queries.length);
      return custom ?? response(query.operation, structuredClone(state));
    },
  };
  const commandClient = {
    execute: async (scope, cmd, request) => {
      writes.push({ scope, command: cmd, request });
      await options.write?.(cmd, request);
      state = {
        source,
        current: true,
        task: { state: 'pending', attempt: 2, failure: null },
      };
      return response(cmd.operation, {
        accepted: true,
        source: cmd.source,
        attempt: cmd.expected_attempt,
      });
    },
  };
  const controller = createNativeKnowledgeProcessingRetryController({
    queryClient,
    commandClient,
    authority: options.authority ?? authority,
    onRefresh: () => notifications.push(true),
  });
  return {
    controller,
    queries,
    writes,
    notifications,
    queryClient,
    setState: (value) => {
      state = structuredClone(value);
    },
  };
}
async function reviewed(f) {
  await f.controller.select(selection);
  await f.controller.review();
}

test('select, review and confirm each recheck exact task; only explicit confirm writes pending CAS', async () => {
  const f = fixture();
  await f.controller.select(selection);
  assert.equal(f.controller.getSnapshot().phase, 'selected');
  assert.ok(Object.isFrozen(f.controller.getSnapshot().selection.failure.source));
  await f.controller.confirm();
  assert.equal(f.writes.length, 0);
  await f.controller.review();
  assert.equal(f.controller.getSnapshot().phase, 'reviewing');
  assert.equal(f.writes.length, 0);
  await f.controller.confirm();
  await setImmediate();
  assert.equal(f.queries.length, 3);
  assert.equal(f.writes.length, 1);
  assert.deepEqual(f.writes[0].command, command);
  assert.deepEqual(f.writes[0].request.expectedScope, nativeScope);
  assert.equal(f.controller.getSnapshot().phase, 'accepted');
  assert.equal(f.notifications.length, 1);
  await f.controller.confirm();
  assert.equal(f.writes.length, 1);
});

test('stale source, changed failure attempt and applied task cannot be confirmed or retried', async () => {
  const states = [
    { source, current: false, task: null },
    {
      source,
      current: true,
      task: { state: 'failed', attempt: 3, failure: 'cancelled' },
    },
    {
      source,
      current: true,
      task: { state: 'completed', attempt: 2, failure: null },
    },
    {
      source,
      current: true,
      task: { state: 'pending', attempt: 2, failure: null },
    },
  ];
  for (const snapshot of states) {
    const f = fixture();
    await reviewed(f);
    f.setState(snapshot);
    await f.controller.confirm();
    assert.equal(f.writes.length, 0);
    assert.equal(f.controller.getSnapshot().error, 'conflict');
    assert.equal(f.controller.getSnapshot().command, null);
    await f.controller.select(selection);
    assert.equal(f.controller.getSnapshot().phase, 'idle');
  }
});

test('review must recheck after selection; source writes invalidate an unconfirmed decision', async () => {
  const f = fixture();
  await f.controller.select(selection);
  f.setState({ source, current: false, task: null });
  await f.controller.review();
  assert.equal(f.controller.getSnapshot().error, 'conflict');
  assert.equal(f.writes.length, 0);
  const g = fixture();
  await reviewed(g);
  g.controller.invalidateSources();
  await g.controller.confirm();
  assert.equal(g.controller.getSnapshot().phase, 'idle');
  assert.equal(g.writes.length, 0);
});

test('unknown write reads exact current state without resend or attributing another change to itself', async () => {
  for (const snapshot of [
    { source, current: false, task: null },
    {
      source,
      current: true,
      task: { state: 'pending', attempt: 2, failure: null },
    },
    {
      source,
      current: true,
      task: { state: 'completed', attempt: 3, failure: null },
    },
    {
      source,
      current: true,
      task: { state: 'failed', attempt: 3, failure: 'cancelled' },
    },
  ]) {
    const f = fixture({
      write: () => {
        throw Error('connection_closed');
      },
    });
    await reviewed(f);
    await f.controller.confirm();
    assert.equal(f.controller.getSnapshot().recoveryRequired, true);
    f.controller.invalidateSources();
    await f.controller.select(selection);
    await f.controller.confirm();
    assert.equal(f.writes.length, 1);
    assert.equal(f.controller.getSnapshot().recoveryRequired, true);
    f.setState(snapshot);
    await f.controller.recover();
    const model = f.controller.getSnapshot();
    assert.equal(model.phase, 'idle');
    assert.equal(model.recoveredUnknown, true);
    assert.deepEqual(model.snapshot, snapshot);
    assert.equal(model.command, null);
    assert.equal(model.recoveryRequired, false);
    assert.equal(f.writes.length, 1);
    await f.controller.confirm();
    assert.equal(f.writes.length, 1);
  }
});

test('failed recovery keeps lock and only a successful current observation unlocks', async () => {
  let failRead = false;
  const f = fixture({
    write: () => {
      throw Error('connection_closed');
    },
    query: () => {
      if (failRead) throw Error('offline');
    },
  });
  await reviewed(f);
  await f.controller.confirm();
  failRead = true;
  await f.controller.recover();
  assert.equal(f.controller.getSnapshot().recoveryRequired, true);
  assert.equal(f.controller.getSnapshot().phase, 'uncertain');
  failRead = false;
  await f.controller.recover();
  assert.equal(f.controller.getSnapshot().recoveryRequired, false);
  assert.equal(f.controller.getSnapshot().recoveredUnknown, true);
  assert.equal(f.writes.length, 1);
});

test('explicit write rejection is not accepted and clears old selection', async () => {
  const f = fixture({
    write: () => {
      throw Object.assign(Error('knowledge_revision_conflict'), {
        status: 409,
      });
    },
  });
  await reviewed(f);
  await f.controller.confirm();
  assert.equal(f.controller.getSnapshot().error, 'conflict');
  assert.equal(f.controller.getSnapshot().recoveryRequired, false);
  await f.controller.confirm();
  assert.equal(f.writes.length, 1);
});

test('missing read/write declarations and foreign generation prevent work', async () => {
  for (const omitted of ['processing_task', 'retry_processing']) {
    const f = fixture({
      authority: {
        ...authority,
        allowedActions: authority.allowedActions.filter((a) => a !== omitted),
      },
    });
    await reviewed(f);
    await f.controller.confirm();
    assert.equal(f.queries.length, 0);
    assert.equal(f.writes.length, 0);
  }
  const f = fixture();
  await f.controller.select({
    ...selection,
    scope: { ...nativeScope, digest: 'other' },
  });
  assert.equal(f.queries.length, 0);
  assert.equal(f.controller.getSnapshot().error, 'contextChanged');
  const g = fixture({
    query: () => ({
      ...response('processing_task', {}),
      scope: { ...nativeScope, generation: 900 },
    }),
  });
  await g.controller.select(selection);
  assert.equal(g.controller.getSnapshot().error, 'contextChanged');
});

test('stop discards late query and acknowledged write without callbacks', async () => {
  let finishRead;
  const f = fixture({
    query: () =>
      new Promise((resolve) => {
        finishRead = resolve;
      }),
  });
  const loading = f.controller.select(selection);
  await setImmediate();
  f.controller.stop();
  finishRead(
    response('processing_task', {
      source,
      current: true,
      task: { state: 'failed', attempt: 2, failure: 'cancelled' },
    }),
  );
  await loading;
  assert.equal(f.controller.getSnapshot().selection, null);
  let finishWrite;
  const g = fixture({
    write: () =>
      new Promise((resolve) => {
        finishWrite = resolve;
      }),
  });
  await reviewed(g);
  const writing = g.controller.confirm();
  await setImmediate();
  g.controller.stop();
  finishWrite();
  await writing;
  await setImmediate();
  assert.equal(g.notifications.length, 0);
  assert.notEqual(g.controller.getSnapshot().phase, 'accepted');
});

test('diagnostics only selects a current observed failure with both retry permissions', async () => {
  const client = {
    query: async () =>
      response('failed_processing', {
        items: [selection.failure],
        next_cursor: null,
      }),
  };
  const c = createNativeKnowledgeDiagnosticsController({ client, authority });
  assert.equal(c.processingSelection(0), null);
  await c.refresh();
  assert.deepEqual(c.processingSelection(0), selection);
  assert.equal(c.processingSelection(1), null);
  c.stop();
  assert.equal(c.processingSelection(0), null);
  const viewer = createNativeKnowledgeDiagnosticsController({
    client,
    authority: {
      ...authority,
      allowedActions: ['failed_processing', 'processing_task'],
    },
  });
  await viewer.refresh();
  assert.equal(viewer.processingSelection(0), null);
});

test('wire validation binds retry acknowledgements and task observations to exact scoped source', () => {
  const q = { operation: 'processing_task', source };
  assert.deepEqual(prepareNativeKnowledgeProcessingQuery(q, projectScope), q);
  assert.deepEqual(prepareNativeKnowledgeProcessingCommand(command, projectScope), command);
  assert.throws(() =>
    prepareNativeKnowledgeProcessingCommand({ ...command, expected_attempt: 0 }, projectScope),
  );
  assert.throws(() =>
    prepareNativeKnowledgeProcessingCommand(
      { ...command, source: { ...source, tenant_id: 'other' } },
      projectScope,
    ),
  );
  const accepted = response('retry_processing', {
    accepted: true,
    source,
    attempt: 2,
  });
  requireNativeKnowledgeProcessingCommandResponse(accepted, command, projectScope, nativeScope);
  assert.throws(() =>
    requireNativeKnowledgeProcessingCommandResponse(
      { ...accepted, result: { ...accepted.result, attempt: 3 } },
      command,
      projectScope,
      nativeScope,
    ),
  );
  const task = response('processing_task', {
    source,
    current: false,
    task: null,
  });
  requireNativeKnowledgeProcessingQueryResponse(task, q, projectScope, nativeScope);
  for (const result of [
    { source, current: true, task: null },
    {
      source,
      current: true,
      task: { state: 'failed', attempt: 2, failure: null },
    },
    { source: { ...source, revision: 4 }, current: false, task: null },
  ])
    assert.throws(() =>
      requireNativeKnowledgeProcessingQueryResponse(
        { ...task, result },
        q,
        projectScope,
        nativeScope,
      ),
    );
});

test('rendered retry panel describes exact queued work and preserves unknown attribution', async () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require(`${dist}/src/i18n.js`);
  const { NativeKnowledgeProcessingRetryPanel } = require(
    `${dist}/src/features/project-knowledge/NativeKnowledgeProcessingRetryPanel.js`,
  );
  const render = (f) =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(NativeKnowledgeProcessingRetryPanel, {
          model: f.controller.getSnapshot(),
          controller: f.controller,
        }),
      ),
    );
  const f = fixture();
  await reviewed(f);
  const review = render(f);
  assert.match(review, /failed-source/);
  assert.match(review, /Change sequence/);
  assert.match(review, /Confirm: restore this task to pending/);
  assert.match(review, /explicitly run one task afterward/);
  await f.controller.confirm();
  assert.match(render(f), /Extraction has not been started/);
  const g = fixture({
    write: () => {
      throw Error('offline');
    },
  });
  await reviewed(g);
  await g.controller.confirm();
  assert.match(render(g), /Do not resend/);
  g.setState({ source, current: false, task: null });
  await g.controller.recover();
  const recovered = render(g);
  assert.match(recovered, /earlier retry result remains unconfirmed/);
  assert.match(recovered, /no longer current/);
  assert.doesNotMatch(recovered, /task was restored to pending/);
});

test('real route controller composition refreshes diagnostics and coverage after retry acknowledgement', async () => {
  const { createNativeMemoriesRouteControllers } = require(
    `${dist}/src/features/project-knowledge/nativeMemoriesRouteControllers.js`,
  );
  let failed = true;
  const writes = [];
  const binding = {
    authority: { ...authority, allowedActions: [...authority.allowedActions, 'configuration'] },
    client: {},
    listClient: {},
    processingClient: {
      query: async (_scope, query) => {
        if (query.operation === 'configuration')
          return response(query.operation, {
            configuration: null,
            active_build_id: null,
            index: null,
            processing: {
              current_sources: 1,
              applied_sources: 0,
              pending_sources: failed ? 0 : 1,
              failed_sources: failed ? 1 : 0,
            },
          });
        if (query.operation === 'failed_processing')
          return response(query.operation, {
            items: failed ? [selection.failure] : [],
            next_cursor: null,
          });
        return response(query.operation, {
          source,
          current: true,
          task: {
            state: failed ? 'failed' : 'pending',
            attempt: 2,
            failure: failed ? 'provider_unavailable' : null,
          },
        });
      },
    },
    processingCommandClient: {
      execute: async (_scope, command) => {
        writes.push(command);
        failed = false;
        return response(command.operation, { accepted: true, source, attempt: 2 });
      },
    },
  };
  const controllers = createNativeMemoriesRouteControllers(binding);
  await controllers.diagnostics.refresh();
  await controllers.processing.refresh();
  await controllers.processingRetry.select(controllers.diagnostics.processingSelection(0));
  await controllers.processingRetry.review();
  await controllers.processingRetry.confirm();
  await setImmediate();
  assert.equal(controllers.processingRetry.getSnapshot().phase, 'accepted');
  assert.equal(controllers.processing.getSnapshot().snapshot.processing.pending_sources, 1);
  assert.equal(controllers.diagnostics.getSnapshot().processing.items.length, 0);
  assert.deepEqual(writes, [command]);
  for (const controller of Object.values(controllers)) controller.stop();
});
