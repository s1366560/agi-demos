import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import {
  nativeScope,
  projectScope,
  source,
  results,
} from './nativeKnowledgeProcessingFixtures.mjs';
const require = createRequire(import.meta.url);
const dist = process.env.GRAPH_SOURCE_DIST ?? '/tmp/agistack-desktop-test-dist';
const { createNativeKnowledgeGraphController } = require(
  `${dist}/src/features/project-knowledge/nativeKnowledgeGraphController.js`,
);
const validation = require(
  `${dist}/src/features/project-knowledge/nativeKnowledgeProcessingValidation.js`,
);
const graph = () => ({
  source,
  audit_attempt: 1,
  title: 'Title',
  content: 'Source',
  entities: [
    { name: 'Same', kind: 'concept' },
    { name: 'Same', kind: 'concept' },
  ],
  relationships: [
    {
      source_index: 0,
      target_index: 1,
      relation_type: 'LINK',
      fact: 'Same links Same',
      score: 0.8,
    },
  ],
});
const envelope = (result) => ({ contract_version: '1.0.0', scope: nativeScope, result });
const query = { operation: 'graph_source', source, expected_audit_attempt: 1 };
function fixture(handler) {
  const calls = [];
  const binding = {
    authority: {
      available: true,
      scope: projectScope,
      userId: 'actor',
      sessionId: 'session',
      contextRevision: nativeScope.context_revision,
      generationDigest: nativeScope.digest,
      allowedActions: ['entities', 'graph_source'],
    },
    processingClient: {
      query: async (scope, command, options) => {
        calls.push({ scope, command, options });
        return handler
          ? handler(command, options)
          : envelope(command.operation === 'entities' ? results.entities : graph());
      },
    },
  };
  return { binding, calls, controller: createNativeKnowledgeGraphController(binding) };
}
test('graph controller opens one observed source attempt with expected scope and keeps same-name nodes', async () => {
  const { controller, calls } = fixture();
  await controller.refresh();
  await controller.open(controller.getSnapshot().sources[0]);
  assert.equal(controller.getSnapshot().graph.entities.length, 2);
  assert.equal(controller.getSnapshot().graph.relationships[0].target_index, 1);
  assert.deepEqual(calls[1].command, query);
  assert.deepEqual(calls[1].options.expectedScope, nativeScope);
  controller.selectNode(1);
  assert.equal(controller.getSnapshot().selectedNode, 1);
  controller.selectNode(9);
  assert.equal(controller.getSnapshot().selectedNode, 1);
  assert.deepEqual(
    calls.map((c) => c.command.operation),
    ['entities', 'graph_source'],
  );
});
test('graph controller rejects stale audit, source and generation replies, clears old data', async () => {
  for (const mutate of [
    (g) => {
      g.result.audit_attempt = 2;
    },
    (g) => {
      g.result.source = { ...source, revision: 2 };
    },
    (g) => {
      g.scope = { ...nativeScope, generation: nativeScope.generation + 1 };
    },
  ]) {
    const { controller } = fixture((command) => {
      const r = envelope(command.operation === 'entities' ? results.entities : graph());
      if (command.operation === 'graph_source') mutate(r);
      return r;
    });
    await controller.refresh();
    await controller.open(controller.getSnapshot().sources[0]);
    assert.equal(controller.getSnapshot().phase, 'error');
    assert.equal(controller.getSnapshot().graph, null);
  }
});
test('graph controller fences late replies and never calls unavailable operations', async () => {
  let resolve;
  const { controller } = fixture(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const pending = controller.refresh();
  controller.stop();
  resolve(envelope(results.entities));
  await pending;
  assert.equal(controller.getSnapshot().sources.length, 0);
  const f = fixture();
  f.binding.authority.allowedActions = ['entities'];
  const denied = createNativeKnowledgeGraphController(f.binding);
  await denied.refresh();
  assert.equal(f.calls.length, 0);
});
test('graph response validates projection indexes, exact identity, empty success and whole UTF-8 budget', () => {
  const valid = (value) =>
    validation.requireNativeKnowledgeProcessingQueryResponse(
      value,
      query,
      projectScope,
      nativeScope,
    );
  assert.deepEqual(valid(envelope(graph())).result, graph());
  assert.doesNotThrow(() => valid(envelope({ ...graph(), entities: [], relationships: [] })));
  for (const mutate of [
    (g) => {
      g.audit_attempt = 2;
    },
    (g) => {
      g.source = { ...source, revision: 2 };
    },
    (g) => {
      g.relationships[0].target_index = 2;
    },
    (g) => {
      g.relationships[0].score = 2;
    },
  ]) {
    const g = graph();
    mutate(g);
    assert.throws(() => valid(envelope(g)));
  }
  const bounded = envelope(graph());
  bounded.result.content = '';
  const overhead = new TextEncoder().encode(JSON.stringify(bounded)).byteLength;
  bounded.result.content = 'x'.repeat(2 * 1024 * 1024 - overhead);
  assert.doesNotThrow(() => valid(bounded));
  bounded.result.content += 'x';
  assert.throws(
    () => valid(bounded),
    (e) => e.status === 413,
  );
  bounded.result.content = '界'.repeat((2 * 1024 * 1024) / 3);
  assert.throws(
    () => valid(bounded),
    (e) => e.status === 413,
  );
});

test('graph page presents exact source completeness, separate node indexes and source text', async () => {
  const { createElement: h } = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { I18nProvider } = require(`${dist}/src/i18n.js`);
  const { NativeKnowledgeGraphPage } = require(
    `${dist}/src/features/project-knowledge/NativeKnowledgeGraphPage.js`,
  );
  const { controller } = fixture();
  await controller.refresh();
  await controller.open(controller.getSnapshot().sources[0]);
  const html = renderToStaticMarkup(
    h(
      I18nProvider,
      null,
      h(NativeKnowledgeGraphPage, { model: controller.getSnapshot(), controller }),
    ),
  );
  assert.match(html, /data-native-knowledge-graph="true"/);
  assert.match(html, /#0 Same/);
  assert.match(html, /#1 Same/);
  assert.match(html, /<svg/);
  assert.match(html, /<input/);
  assert.match(html, /Source/);
  assert.doesNotMatch(html, /nativeGraph\./);
});

test('graph literal filters and adjacency preserve same-name structural nodes', () => {
  const { nativeKnowledgeGraphPresentation: present } = require(
    `${dist}/src/features/project-knowledge/nativeKnowledgeGraphPresentation.js`,
  );
  const g = graph();
  g.entities.push({ name: 'Other', kind: 'concept' });
  assert.deepEqual(present(g, 'Same', null).visibleIndexes, [0, 1]);
  assert.deepEqual(present(g, 'same', null).visibleIndexes, []);
  assert.deepEqual(present(g, 'LINK', null).visibleIndexes, [0, 1]);
  assert.equal(present(g, 'LINK', null).visibleEdges.length, 1);
  assert.deepEqual(present(g, '', 2).visibleIndexes, [2]);
  assert.equal(present(g, '', 2).visibleEdges.length, 0);
  assert.deepEqual(present(g, '', 0).visibleIndexes, [0, 1]);
});
