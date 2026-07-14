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

  assert.equal(resolveA2UIActionView(historyAsked, [canvas, historyAsked]).actions[0].label, 'Approve');
});

test('rejects orphan buttons and dynamic context instead of guessing response values', () => {
  const orphanComponents = components.replace('"explicitList":["button-1"]', '"explicitList":[]');
  const orphan = asked();
  orphan.payload.surface_data.components = orphanComponents;
  assert.deepEqual(resolveA2UIActionView(orphan, []).actions, []);

  const contextual = asked();
  contextual.payload.surface_data.context = { approved: true };
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
