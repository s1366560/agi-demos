import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = '/tmp/agistack-desktop-test-dist/src';
const { I18nProvider } = require(`${root}/i18n.js`);
const { NativeKnowledgeConfigurationPanel } = require(
  `${root}/features/project-knowledge/NativeKnowledgeConfigurationPanel.js`,
);
const { NativeKnowledgeRetrievalPanel, NativeKnowledgeRetrievalUnavailable } = require(
  `${root}/features/project-knowledge/NativeKnowledgeRetrievalPanel.js`,
);
const h = React.createElement;
const render = (element) => renderToStaticMarkup(h(I18nProvider, null, element));
const noop = () => {};
const controller = {
  refreshConfiguration: noop,
  setMode: noop,
  setDraft: noop,
  submit: noop,
  nextPage: noop,
  viewSource: noop,
};
const source = {
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  memory_id: 'memory-1',
  revision: 1,
  change_sequence: 7,
};
const configuration = {
  configuration: {
    revision: 8,
    build_id: 'desired-B',
    provider_id: 'provider-1',
    provider_revision: 3,
    model_id: 'embedding-model',
    dimensions: 3,
    input_contract_version: 1,
    normalization_version: 1,
  },
  active_build_id: 'active-A',
  processing: { current_sources: 5, applied_sources: 2, pending_sources: 2, failed_sources: 1 },
  index: { current_sources: 2, completed_sources: 2, failed_sources: 0 },
};
const model = {
  phase: 'idle',
  allowedActions: ['configuration', 'text', 'semantic', 'entities', 'relationships', 'view'],
  mode: 'text',
  draft: '',
  configuration,
  result: null,
  source: null,
  sourceState: 'idle',
  error: null,
};
const config = (m) => render(h(NativeKnowledgeConfigurationPanel, { model: m, controller }));
const retrieval = (m) => render(h(NativeKnowledgeRetrievalPanel, { model: m, controller }));

test('configuration separates desired from active build and extraction failures from vector coverage', () => {
  const html = config(model);
  assert.match(html, /desired-B/);
  assert.match(html, /active-A/);
  assert.match(html, /Failed extractions<\/th><td>1/);
  assert.match(html, /Failed index jobs<\/th><td>0/);
  assert.match(html, /2 \/ 2 \(100\.0%\)/);
  assert.match(html, /Pending or failed extraction is shown separately/);
  assert.match(html, /Per-job failure details and retry actions are not available yet/);
  assert.doesNotMatch(html, /Ready|Healthy|Retry<|Rebuild<|Promote</);
});

test('zero eligible sources never becomes a fabricated 100 percent ready verdict', () => {
  const html = config({
    ...model,
    configuration: {
      ...configuration,
      index: { current_sources: 0, completed_sources: 0, failed_sources: 0 },
    },
  });
  assert.match(html, /No extracted sources to measure/);
  assert.doesNotMatch(html, /100|NaN|Infinity/);
  const absent = config({
    ...model,
    configuration: { ...configuration, configuration: null, active_build_id: null, index: null },
  });
  assert.match(absent, /No desired embedding configuration/);
  assert.match(absent, /No active index build/);
});

test('operation declarations control each explicit retrieval mode and unavailable client state is visible', () => {
  const html = retrieval({ ...model, allowedActions: ['text'] });
  assert.match(html, /Literal text match/);
  assert.doesNotMatch(html, /Semantic similarity|Extracted entities|Extracted relationships/);
  assert.equal(config({ ...model, allowedActions: ['view'] }), '');
  assert.equal(retrieval({ ...model, allowedActions: ['view'] }), '');
  assert.match(
    render(h(NativeKnowledgeRetrievalUnavailable)),
    /not available for the current context/,
  );
});

test('semantic scores are numeric and unfiltered with exact source revisions; no false semantic pagination', () => {
  const html = retrieval({
    ...model,
    mode: 'semantic',
    phase: 'results',
    result: {
      operation: 'semantic',
      result: {
        configuration: configuration.configuration,
        processing: configuration.processing,
        index: configuration.index,
        hits: [
          { input: { source, audit_attempt: 2, input_digest: 'private-digest' }, score: -0.25 },
        ],
      },
    },
  });
  assert.match(html, /Cosine similarity: -0\.2500/);
  assert.match(html, /Scores are not quality verdicts/);
  assert.match(html, /Source revision<\/dt><dd>1/);
  assert.match(html, /View matching source revision/);
  assert.doesNotMatch(html, /Load next page|private-digest|Relevant|Irrelevant/);
});

test('source revision changes show an explicit stale result notice without showing replacement content', () => {
  const html = retrieval({
    ...model,
    phase: 'results',
    sourceState: 'changed',
    result: {
      operation: 'text',
      result: {
        items: [
          {
            source,
            audit_attempt: 1,
            title: 'Original title',
            content: 'Original literal content',
          },
        ],
        next_cursor: null,
      },
    },
  });
  assert.match(html, /Original literal content/);
  assert.match(html, /source changed after this result was produced/);
  assert.doesNotMatch(html, /replacement body/);
});

test('entity and relationship browsing labels do not describe semantic matching', () => {
  const entities = retrieval({ ...model, mode: 'entities', allowedActions: ['entities'] });
  assert.match(entities, /Browse current extracted entities/);
  assert.doesNotMatch(entities, /Query text|Cosine similarity/);
  const relationships = retrieval({
    ...model,
    mode: 'relationships',
    allowedActions: ['relationships'],
  });
  assert.match(relationships, /exact source references/);
  assert.doesNotMatch(relationships, /Query text|Cosine similarity/);
});
