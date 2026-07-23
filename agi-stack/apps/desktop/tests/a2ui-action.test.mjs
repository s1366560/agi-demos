import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { markA2UIActionAnswered, resolveA2UIActionView } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/a2uiAction.js'
);

const components = [
  JSON.stringify({ beginRendering: { surfaceId: 'surface-1', root: 'root-1' } }),
  JSON.stringify({
    surfaceUpdate: {
      surfaceId: 'surface-1',
      components: [
        {
          id: 'root-1',
          component: { Column: { children: { explicitList: ['button-1'] } } },
        },
        {
          id: 'button-1',
          component: { Button: { child: 'label-1', action: { name: 'approve' } } },
        },
        {
          id: 'label-1',
          component: { Text: { text: { literalString: 'Approve' } } },
        },
      ],
    },
  }),
].join('\n');

function asked(overrides = {}) {
  return {
    id: 'asked-1',
    type: 'a2ui_action_asked',
    eventTimeUs: 2,
    eventCounter: 0,
    request_id: 'request-1',
    block_id: 'block-1',
    payload: {
      request_id: 'request-1',
      block_id: 'block-1',
      surface_data: {
        components,
        context: {},
        allowed_actions: [{ source_component_id: 'button-1', action_name: 'approve' }],
      },
    },
    ...overrides,
  };
}

test('resolves a live stateless button only when the server allow-list matches', () => {
  assert.deepEqual(resolveA2UIActionView(asked(), []), {
    actions: [
      {
        actionName: 'approve',
        sourceComponentId: 'button-1',
        label: 'Approve',
      },
    ],
    reason: null,
  });

  const mismatch = asked();
  mismatch.payload.surface_data.allowed_actions[0].action_name = 'reject';
  assert.deepEqual(resolveA2UIActionView(mismatch, []).actions, []);
});

test('resolves allowlisted static A2UI action context without exposing request metadata', () => {
  const contextual = asked();
  contextual.payload.surface_data.context = { internal_trace: 'do-not-submit' };
  contextual.payload.surface_data.components = components.replace(
    '"action":{"name":"approve"}',
    '"action":{"name":"approve","context":{"approved":{"literalBoolean":true},"release":{"literalString":"2026.07"},"attempt":{"literalNumber":2}}}',
  );

  assert.deepEqual(resolveA2UIActionView(contextual, []).actions, [
    {
      actionName: 'approve',
      sourceComponentId: 'button-1',
      label: 'Approve',
      context: { approved: true, release: '2026.07', attempt: 2 },
    },
  ]);
});

test('restores a history action from its prior canvas block and persisted allow-list', () => {
  const canvas = {
    id: 'canvas-1',
    type: 'canvas_updated',
    eventTimeUs: 1,
    eventCounter: 0,
    payload: {
      block_id: 'block-1',
      block: { id: 'block-1', content: components },
    },
  };
  const historyAsked = asked({
    payload: {
      request_id: 'request-1',
      block_id: 'block-1',
      allowed_actions: [{ source_component_id: 'button-1', action_name: 'approve' }],
    },
  });

  const restored = resolveA2UIActionView(historyAsked, [canvas, historyAsked]);
  assert.equal(restored.actions[0]?.label, 'Approve', restored.reason ?? undefined);
});

test('a deleted or malformed latest canvas revision cannot restore a stale action', () => {
  const created = {
    id: 'canvas-created',
    type: 'canvas_updated',
    eventTimeUs: 1,
    eventCounter: 0,
    payload: {
      action: 'created',
      block_id: 'block-1',
      block: { id: 'block-1', content: components },
    },
  };
  const deleted = {
    id: 'canvas-deleted',
    type: 'canvas_updated',
    eventTimeUs: 1.5,
    eventCounter: 1,
    payload: { action: 'deleted', block_id: 'block-1', block: null },
  };
  const malformedUpdate = {
    ...deleted,
    id: 'canvas-malformed-update',
    payload: { action: 'updated', block_id: 'block-1', block: null },
  };
  const historyAsked = asked({
    payload: {
      request_id: 'request-1',
      block_id: 'block-1',
      allowed_actions: [{ source_component_id: 'button-1', action_name: 'approve' }],
    },
  });

  assert.deepEqual(resolveA2UIActionView(historyAsked, [created, deleted, historyAsked]).actions, []);
  assert.deepEqual(
    resolveA2UIActionView(historyAsked, [created, malformedUpdate, historyAsked]).actions,
    [],
  );
});

test('replays incremental canvas updates before restoring an A2UI action', () => {
  const created = {
    id: 'canvas-created',
    type: 'canvas_updated',
    eventTimeUs: 1,
    eventCounter: 0,
    payload: {
      action: 'created',
      block_id: 'block-1',
      block: { id: 'block-1', content: components },
    },
  };
  const updated = {
    id: 'canvas-updated',
    type: 'canvas_updated',
    eventTimeUs: 1.5,
    eventCounter: 1,
    payload: {
      action: 'updated',
      block_id: 'block-1',
      block: {
        id: 'block-1',
        content: JSON.stringify({
          surfaceUpdate: {
            surfaceId: 'surface-1',
            components: [
              {
                id: 'label-1',
                component: { Text: { text: { literalString: 'Ship verified release' } } },
              },
            ],
          },
        }),
      },
    },
  };
  const historyAsked = asked({
    payload: {
      request_id: 'request-1',
      block_id: 'block-1',
      allowed_actions: [{ source_component_id: 'button-1', action_name: 'approve' }],
    },
  });

  assert.deepEqual(
    resolveA2UIActionView(historyAsked, [created, updated, historyAsked]).actions,
    [
      {
        actionName: 'approve',
        sourceComponentId: 'button-1',
        label: 'Ship verified release',
      },
    ],
  );

  const crossSurfaceUpdate = structuredClone(updated);
  crossSurfaceUpdate.id = 'canvas-cross-surface-update';
  crossSurfaceUpdate.payload.block.content = updated.payload.block.content.replace(
    'surface-1',
    'surface-2',
  );
  assert.deepEqual(
    resolveA2UIActionView(historyAsked, [created, crossSurfaceUpdate, historyAsked]).actions,
    [],
  );
});

test('rejects orphan buttons and path-bound action context instead of guessing response values', () => {
  const orphanComponents = components.replace('"explicitList":["button-1"]', '"explicitList":[]');
  const orphan = asked();
  orphan.payload.surface_data.components = orphanComponents;
  assert.deepEqual(resolveA2UIActionView(orphan, []).actions, []);

  const contextual = asked();
  contextual.payload.surface_data.components = components.replace(
    '"action":{"name":"approve"}',
    '"action":{"name":"approve","context":{"approved":{"path":"/form/approved"}}}',
  );
  assert.deepEqual(resolveA2UIActionView(contextual, []).actions, []);
});

test('rejects dangerous object keys and multiple surface identities', () => {
  const dangerous = asked();
  dangerous.payload.surface_data.components = `${components}\n${JSON.stringify({
    surfaceUpdate: {
      surfaceId: 'surface-1',
      constructor: { prototype: { polluted: true } },
      components: [],
    },
  })}`;
  assert.deepEqual(resolveA2UIActionView(dangerous, []).actions, []);

  const multiple = asked();
  multiple.payload.surface_data.components = `${components}\n${JSON.stringify({
    beginRendering: { surfaceId: 'surface-2', root: 'other-root' },
  })}`;
  assert.deepEqual(resolveA2UIActionView(multiple, []).actions, []);
});

test('marks the matching request answered when another client submits the action', () => {
  const pending = asked();
  const unrelated = asked({ id: 'asked-2', request_id: 'request-2' });
  unrelated.payload.request_id = 'request-2';

  const updated = markA2UIActionAnswered([pending, unrelated], {
    type: 'a2ui_action_answered',
    data: { request_id: 'request-1', action_name: 'approve' },
  });

  assert.equal(updated[0].answered, true);
  assert.equal(updated[1].answered, undefined);
});
