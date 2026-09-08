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
  processing: {
    current_sources: 5,
    applied_sources: 2,
    pending_sources: 2,
    failed_sources: 1,
  },
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
  assert.match(html, /Historical task failures cannot be listed or retried here/);
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
    configuration: {
      ...configuration,
      configuration: null,
      active_build_id: null,
      index: null,
    },
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
          {
            input: { source, audit_attempt: 2, input_digest: 'private-digest' },
            score: -0.25,
          },
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
  const entities = retrieval({
    ...model,
    mode: 'entities',
    allowedActions: ['entities'],
  });
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

// A saved raw memory is not yet an eligible retrieval source.
test('literal help and an empty result explain manual extraction of the current revision', () => {
  const html = retrieval({
    ...model,
    phase: 'results',
    result: { operation: 'text', result: { items: [], next_cursor: null } },
  });
  assert.match(
    html,
    /title or content of current source revisions with successfully applied extraction/,
  );
  assert.match(html, /New or edited memories must be extracted manually/);
  assert.match(html, /No matching records were returned/);
  assert.match(html, /Check extraction status/);
});

test('source navigation identifies its exact revision and marks referenced entities without hiding other records', () => {
  const reference = { source, entity_index: 1 };
  const html = retrieval({
    ...model,
    mode: 'entities',
    phase: 'results',
    navigation: reference,
    result: {
      operation: 'entities',
      result: {
        items: [0, 1].map((index) => ({
          reference: { source, entity_index: index },
          audit_attempt: 1,
          entity: { name: `Entity ${index}`, kind: 'topic' },
        })),
        next_cursor: null,
      },
    },
  });
  assert.match(html, /Browsing this exact source revision/);
  assert.match(html, /Clear source filter/);
  assert.match(html, /Entity 0/);
  assert.match(html, /Entity 1/);
  assert.equal((html.match(/Selected entity reference/g) ?? []).length, 1);
  assert.equal((html.match(/Browse relationships from this source/g) ?? []).length, 2);
  const restricted = retrieval({
    ...model,
    mode: 'entities',
    allowedActions: ['entities'],
    result: {
      operation: 'entities',
      result: {
        items: [
          {
            reference,
            audit_attempt: 1,
            entity: { name: 'Entity', kind: 'topic' },
          },
        ],
        next_cursor: null,
      },
    },
  });
  assert.doesNotMatch(
    restricted,
    /Browse relationships from this source|View matching source revision/,
  );
});

test('relationship endpoints offer entity navigation and preserve visible reference identities', () => {
  const html = retrieval({
    ...model,
    mode: 'relationships',
    navigation: { source, entity_index: 1 },
    result: {
      operation: 'relationships',
      result: {
        next_cursor: null,
        items: [
          {
            source,
            audit_attempt: 1,
            relationship_index: 0,
            source_entity: { source, entity_index: 0 },
            target_entity: { source, entity_index: 1 },
            relationship: { relation_type: 'related', fact: 'A declared fact' },
          },
        ],
      },
    },
  });
  assert.equal((html.match(/Browse referenced entity/g) ?? []).length, 2);
  assert.match(html, /References the selected entity/);
  assert.match(html, /memory-1 \/ 0/);
  assert.match(html, /memory-1 \/ 1/);
});
