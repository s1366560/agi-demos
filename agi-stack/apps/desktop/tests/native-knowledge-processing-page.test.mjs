import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  NativeKnowledgeProcessingPanel,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-knowledge/NativeKnowledgeProcessingPanel.js');
const h = React.createElement;
const noop = () => {};
const controller = { refresh: noop, review: noop, confirm: noop, cancelReview: noop };
const model = {
  phase: 'idle',
  allowedActions: [
    'configuration',
    'index_one',
    'retry_index',
    'promote_index',
    'select_embedding',
    'configure_embedding',
    'process_one',
  ],
  snapshot: null,
  selection: null,
  failedTask: null,
  outcome: null,
  recoveryRequired: false,
  error: null,
  notice: null,
};
const render = (m) =>
  renderToStaticMarkup(
    h(I18nProvider, null, h(NativeKnowledgeProcessingPanel, { model: m, controller })),
  );

test('only declared actions appear and missing trusted provider/workspace context is explicit', () => {
  const html = render(model);
  assert.match(html, /Review one indexing task/);
  assert.match(html, /trusted provider and model selection/);
  assert.match(html, /trusted workspace selection/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>Review failed indexing task retry/);
  assert.doesNotMatch(html, /<input|<select|Rebuild all|Run extraction<|Configure provider</);
  const only = render({ ...model, allowedActions: ['configuration', 'index_one'] });
  assert.doesNotMatch(
    only,
    /Review index promotion|Review failed indexing task retry|trusted provider/,
  );
  assert.equal(render({ ...model, allowedActions: ['view'] }), '');
});
test('missing command client is unavailable rather than a write button', () => {
  const html = render({ ...model, phase: 'unavailable' });
  assert.match(html, /admitted command client/);
  assert.doesNotMatch(html, /<button/);
});
test('unknown result locks all writes and only exposes state refresh without replay promise', () => {
  const html = render({ ...model, phase: 'uncertain', recoveryRequired: true });
  assert.match(html, /outcome is unknown/);
  assert.match(html, /previous request will not be sent again/);
  assert.match(html, /<button type="button">Refresh processing state/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>Review one indexing task/);
  assert.doesNotMatch(html, /Confirm one action|Retry same request|server confirmed/);
  const refreshed = render({ ...model, notice: 'recoveredUnknown' });
  assert.match(refreshed, /does not confirm the outcome of the previous action/);
});
test('null worker receipt and retry acknowledgement never claim all processing completed', () => {
  const empty = render({
    ...model,
    phase: 'accepted',
    outcome: { operation: 'index_one', result: { receipt: null } },
  });
  assert.match(empty, /No available task was claimed/);
  assert.match(empty, /Other tasks may still be pending or running/);
  assert.doesNotMatch(empty, /All tasks completed|100%|Ready/);
  const queued = render({
    ...model,
    phase: 'accepted',
    outcome: { operation: 'retry_index', result: { accepted: true, input: {}, attempt: 3 } },
  });
  assert.match(queued, /queued again/);
  assert.match(queued, /execution is not yet confirmed/);
});
test('review shows exact target and failed task provenance with translated typed failure', () => {
  const receipt = {
    input: { source: { memory_id: 'exact-source', revision: 3 }, input_digest: 'private-digest' },
    attempt: 4,
    status: 'failed',
    failure: 'invalid_embedding',
  };
  const html = render({
    ...model,
    phase: 'reviewing',
    selection: { operation: 'retry_index', build_id: 'exact-build' },
    failedTask: { receipt },
  });
  assert.match(html, /exact-source/);
  assert.match(html, /exact-build/);
  assert.match(html, /Task attempt<\/dt><dd>4/);
  assert.match(html, /Invalid embedding returned/);
  assert.match(html, /does not execute the task or retry other failures/);
  assert.doesNotMatch(html, /private-digest/);
});

test('trusted embedding choices show declared models and CAS review without manual scope inputs', () => {
  const inputs = {
    embeddingModels: {
      availability: 'available',
      items: [
        {
          providerId: 'provider-1',
          providerRevision: 3,
          providerName: 'Provider One',
          modelId: 'embedding-1',
        },
      ],
    },
    workspaces: { availability: 'unavailable', items: [] },
  };
  const chosen = {
    ...model,
    inputsAvailable: true,
    inputs,
    inputOperation: 'configure_embedding',
    embeddingChoice: inputs.embeddingModels.items[0],
  };
  const html = render(chosen);
  assert.match(html, /<select/);
  assert.match(html, /Provider One · embedding-1/);
  assert.doesNotMatch(html, /<input|api_key|credential|workspaceRoot/);
  const review = render({
    ...chosen,
    phase: 'reviewing',
    selection: {
      operation: 'configure_embedding',
      build_id: 'new-build',
      provider_id: 'provider-1',
      provider_revision: 3,
      model_id: 'embedding-1',
      expected_config_revision: 8,
    },
  });
  assert.match(review, /Expected previous configuration revision<\/dt><dd>8/);
  assert.match(review, /Provider revision<\/dt><dd>3/);
  assert.match(review, /new-build/);
});

test('workspace selection and extraction receipt expose exact action and failed source', () => {
  const inputs = {
    embeddingModels: { availability: 'unavailable', items: [] },
    workspaces: {
      availability: 'available',
      items: [{ id: 'workspace-1', name: 'Workspace One' }],
    },
  };
  const html = render({
    ...model,
    inputsAvailable: true,
    inputs,
    inputOperation: 'process_one',
    workspaceChoice: inputs.workspaces.items[0],
    selection: { operation: 'process_one', workspace_id: 'workspace-1' },
  });
  assert.match(html, /Workspace One · workspace-1/);
  assert.match(html, /configured agent and provider/);
  const failed = render({
    ...model,
    outcome: {
      operation: 'process_one',
      result: {
        receipt: {
          source: { memory_id: 'source-1', revision: 4 },
          attempt: 2,
          status: 'failed',
          failure: 'invalid_extraction',
        },
      },
    },
  });
  assert.match(failed, /Observed extraction task receipt/);
  assert.match(failed, /source-1/);
  assert.match(failed, /Invalid extraction returned/);
  assert.doesNotMatch(failed, /server confirmed|All tasks completed/);
  const empty = render({
    ...model,
    outcome: { operation: 'process_one', result: { receipt: null } },
  });
  assert.match(empty, /No available task was claimed/);
});
