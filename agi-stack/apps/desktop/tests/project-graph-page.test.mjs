import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { scope, episode, relation, snapshot } from './projectGraphProvenanceFixtures.mjs';
const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = '/tmp/agistack-desktop-test-dist/src';
const { I18nProvider } = require(root + '/i18n.js');
const { ProjectGraphPage } = require(root + '/features/project-knowledge/ProjectGraphPage.js');
const { buildProjectGraphPresentation } = require(
  root + '/features/project-knowledge/projectGraphPresentationModel.js',
);
const noop = () => {};
const controller = { retry: noop, selectNode: noop, selectEdge: noop, openSource: noop };
const render = (model) =>
  renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(ProjectGraphPage, { model, controller }),
    ),
  );
test('dedicated graph surface exposes directed endpoint navigation and exact source identities', () => {
  const model = {
    ...buildProjectGraphPresentation({ kind: 'snapshot', snapshot: snapshot() }),
    selection: { kind: 'edge', id: relation.id },
  };
  const html = render(model);
  assert.match(html, /Knowledge graph/);
  assert.match(html, /<table/);
  assert.match(html, /<th>From<\/th>/);
  assert.match(html, /<th>To<\/th>/);
  assert.match(html, /A recorded relationship/);
  assert.match(html, /episode-uuid/);
  assert.match(html, /missing-episode/);
  assert.match(html, /Neighbor and source lists may be incomplete/);
  assert.match(html, /Community membership alone is not source evidence/);
  assert.doesNotMatch(html, /<iframe|<webview|Open in browser/);
});
test('captured content is separate from an explicit current-memory read and absent sources remain honest', () => {
  const base = buildProjectGraphPresentation({ kind: 'snapshot', snapshot: snapshot() });
  const model = {
    ...base,
    selection: { kind: 'edge', id: relation.id },
    source: episode,
    sourceUuid: episode.uuid,
    sourceState: 'ready',
  };
  const html = render(model);
  assert.match(html, /Captured episode content/);
  assert.match(html, /Captured source text/);
  assert.match(html, /No original memory revision was stored/);
  assert.match(html, /Current linked memory/);
  assert.match(html, /Its content or revision may differ/);
  assert.doesNotMatch(html, /Save memory|Delete|source_url/);
  assert.match(render({ ...model, source: null }), /This source could not be read/);
  const unavailable = render(
    buildProjectGraphPresentation({
      kind: 'failure',
      scope: { ...scope, authority: 'local' },
      state: 'unavailable',
      reasonCode: 'local_project_graph_authority_unavailable',
      retryable: false,
    }),
  );
  assert.doesNotMatch(unavailable, /<table/);
  assert.match(unavailable, /unavailable for this project or account/);
});
