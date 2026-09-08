import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { nativeScope, projectScope } from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const dist = process.env.I5_DIAGNOSTICS_DIST ?? '/tmp/agistack-project-knowledge-test-dist';
const { createNativeKnowledgeDiagnosticsController } = require(
  `${dist}/src/features/project-knowledge/nativeKnowledgeDiagnosticsController.js`,
);
const { createNativeKnowledgeProcessingController } = require(
  `${dist}/src/features/project-knowledge/nativeKnowledgeProcessingController.js`,
);
const {
  prepareNativeKnowledgeProcessingQuery,
  requireNativeKnowledgeProcessingQueryResponse,
} = require(`${dist}/src/features/project-knowledge/nativeKnowledgeProcessingValidation.js`);
const configuration = {
  revision: 8,
  build_id: 'build',
  provider_id: 'provider',
  provider_revision: 1,
  model_id: 'model',
  dimensions: 2,
  input_contract_version: 1,
  normalization_version: 1,
};
const source = {
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  memory_id: 'memory',
  revision: 2,
  change_sequence: 3,
};
const failure = {
  input: { source, audit_attempt: 1, input_digest: 'ab'.repeat(32) },
  attempt: 4,
  failure: 'provider_unavailable',
};
const snapshot = {
  configuration,
  active_build_id: null,
  processing: {
    current_sources: 1,
    applied_sources: 1,
    pending_sources: 0,
    failed_sources: 0,
  },
  index: { current_sources: 1, completed_sources: 0, failed_sources: 1 },
};
const audit = {
  source,
  attempt: 1,
  agent_id: 'agent',
  provider_id: 'provider',
  model_id: 'model',
  tool_name: 'submit_projection',
  contract_version: 1,
  started_at_ms: 100,
  finished_at_ms: 101,
  latency_ms: 1,
  status: 'failed',
  failure: 'provider_unavailable',
};
const authority = {
  scope: projectScope,
  userId: 'user-1',
  sessionId: 'session-1',
  contextRevision: 7,
  generationDigest: 'renderer',
  available: true,
  allowedActions: [
    'configuration',
    'failed_processing',
    'failed_index',
    'processing_audits',
    'retry_index',
  ],
};
function fixture(options = {}) {
  const queries = [],
    writes = [];
  const client = {
    query: async (scope, command, request) => {
      queries.push({ scope, command, request });
      if (options.query) {
        const response = await options.query(command, queries);
        if (response) return response;
      }
      return {
        contract_version: '1.0.0',
        scope: nativeScope,
        result: structuredClone(
          command.operation === 'configuration'
            ? snapshot
            : {
                items:
                  command.operation === 'failed_index'
                    ? [failure]
                    : command.operation === 'failed_processing'
                      ? [
                          {
                            source,
                            attempt: 1,
                            failure: 'provider_unavailable',
                          },
                        ]
                      : [audit],
                next_cursor: null,
              },
        ),
      };
    },
  };
  const controller = createNativeKnowledgeDiagnosticsController({
    client,
    authority: { ...authority, ...options.authority },
  });
  const processing = createNativeKnowledgeProcessingController({
    authority,
    queryClient: client,
    commandClient: {
      execute: async (scope, command, request) => {
        writes.push({ scope, command, request });
        return {
          contract_version: '1.0.0',
          scope: nativeScope,
          result: {
            accepted: true,
            input: command.input,
            attempt: command.expected_attempt,
          },
        };
      },
    },
  });
  return { controller, processing, queries, writes };
}

test('persisted index failure can be rediscovered, selected and retried only through existing review and confirm', async () => {
  const f = fixture();
  await f.controller.refresh('failed_index');
  const selection = f.controller.selection(0);
  assert.deepEqual(selection.failure, failure);
  assert(Object.isFrozen(selection.failure.input.source));
  await f.processing.selectDiagnosticFailure(selection);
  assert.equal(f.processing.getSnapshot().failedTask.receipt.attempt, 4);
  assert.equal(f.writes.length, 0);
  await f.processing.review('retry_index');
  assert.equal(f.writes.length, 0);
  await f.processing.confirm();
  assert.equal(f.writes.length, 1);
  assert.deepEqual(f.writes[0].command, {
    operation: 'retry_index',
    build_id: 'build',
    config_revision: 8,
    input: failure.input,
    expected_attempt: 4,
  });
  assert.deepEqual(f.writes[0].request.expectedScope, nativeScope);
  const reopened = fixture();
  await reopened.controller.refresh('failed_index');
  assert.deepEqual(reopened.controller.selection(0).failure, failure);
});

test('diagnostics are capability gated, source audit selection is restricted to the current page', async () => {
  const denied = fixture({ authority: { allowedActions: ['view'] } });
  await denied.controller.refresh();
  assert.equal(denied.queries.length, 0);
  assert.equal(denied.controller.getSnapshot().phase, 'unavailable');
  const f = fixture({
    authority: { allowedActions: ['failed_processing', 'processing_audits'] },
  });
  await f.controller.refresh();
  await f.controller.inspect({ ...source, memory_id: 'foreign' });
  assert.equal(f.queries.length, 1);
  await f.controller.inspect(source);
  assert.equal(f.queries.length, 2);
  assert.deepEqual(f.queries[1].command.source, source);
  assert.deepEqual(f.queries[1].request.expectedScope, nativeScope);
  assert.equal(f.controller.getSnapshot().audits.items.length, 1);
  assert.equal(f.controller.selection(0), null);
  assert.equal(f.writes.length, 0);
});

test('configuration or context change while selecting a persisted failure clears selection without commands', async () => {
  for (const kind of ['configuration', 'scope']) {
    let changed = false;
    const f = fixture({
      query: (command) =>
        changed && command.operation === 'configuration'
          ? {
              contract_version: '1.0.0',
              scope: kind === 'scope' ? { ...nativeScope, generation: 999 } : nativeScope,
              result:
                kind === 'configuration'
                  ? {
                      ...snapshot,
                      configuration: { ...configuration, revision: 9 },
                    }
                  : snapshot,
            }
          : null,
    });
    await f.controller.refresh('failed_index');
    const selection = f.controller.selection(0);
    changed = true;
    await f.processing.selectDiagnosticFailure(selection);
    assert.equal(f.processing.getSnapshot().failedTask, null);
    assert.notEqual(f.processing.getSnapshot().error, null);
    assert.equal(f.writes.length, 0);
  }
});

test('late responses after stop and scope mismatches never restore diagnostic records', async () => {
  let release;
  const f = fixture({
    query: () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  });
  const pending = f.controller.refresh();
  f.controller.stop();
  release({
    contract_version: '1.0.0',
    scope: nativeScope,
    result: {
      items: [{ source, attempt: 1, failure: 'cancelled' }],
      next_cursor: null,
    },
  });
  await pending;
  assert.equal(f.controller.getSnapshot().processing, null);
  const mismatch = fixture({
    query: () => ({
      contract_version: '1.0.0',
      scope: { ...nativeScope, context_revision: 999 },
      result: { items: [], next_cursor: null },
    }),
  });
  await mismatch.controller.refresh();
  assert.equal(mismatch.controller.getSnapshot().error, 'contextChanged');
  assert.equal(mismatch.controller.getSnapshot().processing, null);
});

test('changed configuration refuses continuation cursors and old pages are cleared', async () => {
  let version = 8;
  const f = fixture({
    query: (command) => ({
      contract_version: '1.0.0',
      scope: nativeScope,
      result:
        command.operation === 'configuration'
          ? {
              ...snapshot,
              configuration: { ...configuration, revision: version },
            }
          : { items: [failure], next_cursor: 'cursor' },
    }),
  });
  await f.controller.refresh('failed_index');
  version = 9;
  await f.controller.next();
  assert.equal(f.controller.getSnapshot().phase, 'error');
  assert.equal(f.controller.getSnapshot().index, null);
  assert.equal(f.queries.filter((q) => q.command.operation === 'failed_index').length, 1);
});

test('generated diagnostic validation rejects foreign sources, leaked prompt fields and incoherent outcomes', () => {
  const query = {
    operation: 'processing_audits',
    source,
    request: { limit: 1 },
  };
  assert.deepEqual(prepareNativeKnowledgeProcessingQuery(query, projectScope), query);
  assert.throws(() =>
    prepareNativeKnowledgeProcessingQuery(
      { ...query, source: { ...source, tenant_id: 'foreign' } },
      projectScope,
    ),
  );
  assert.throws(() =>
    prepareNativeKnowledgeProcessingQuery({ ...query, request: { limit: 101 } }, projectScope),
  );
  const envelope = (item) => ({
    contract_version: '1.0.0',
    scope: nativeScope,
    result: { items: [item], next_cursor: null },
  });
  assert.deepEqual(
    requireNativeKnowledgeProcessingQueryResponse(envelope(audit), query, projectScope, nativeScope)
      .result.items,
    [audit],
  );
  for (const item of [
    { ...audit, input: { content: 'private' } },
    { ...audit, source: { ...source, revision: 3 } },
    { ...audit, status: 'applied' },
    { ...audit, finished_at_ms: 99 },
    { ...audit, status: 'running', finished_at_ms: null, latency_ms: null },
  ]) {
    assert.throws(() =>
      requireNativeKnowledgeProcessingQueryResponse(
        envelope(item),
        query,
        projectScope,
        nativeScope,
      ),
    );
  }
});

test('diagnostic panel renders source revision, failure and audit metadata with gated retry selection', async () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require(`${dist}/src/i18n.js`);
  const { NativeKnowledgeDiagnosticsPanel } = require(
    `${dist}/src/features/project-knowledge/NativeKnowledgeDiagnosticsPanel.js`,
  );
  const f = fixture();
  await f.controller.refresh('failed_index');
  await f.controller.inspect(source);
  const render = (model) =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(NativeKnowledgeDiagnosticsPanel, {
          model,
          controller: f.controller,
          onSelectIndexFailure: () => {},
        }),
      ),
    );
  const html = render(f.controller.getSnapshot());
  assert.match(html, /memory/);
  assert.match(html, /Revision.*2/);
  assert.match(html, /Attempt.*4/);
  assert.match(html, /Select for index retry review/);
  assert.match(html, /Extraction audit metadata/);
  assert.match(html, /agent.*provider.*model/);
  assert.doesNotMatch(html, /nativeDiagnostics\.|credential|Content/);
  assert.doesNotMatch(
    render({
      ...f.controller.getSnapshot(),
      allowedActions: ['failed_index', 'processing_audits'],
    }),
    /Select for index retry review/,
  );
});
