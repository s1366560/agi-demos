import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  applyA2UISurfaceMessages,
  componentsForA2UIRenderer,
  createA2UIActionCommand,
  createEmptyA2UISurfaceState,
  isSupportedActionContext,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/a2uiSurfaceModel.js');

function surface(context) {
  const messages = [
    JSON.stringify({ beginRendering: { surfaceId: 'surface-1', root: 'button-1' } }),
    JSON.stringify({
      surfaceUpdate: {
        surfaceId: 'surface-1',
        components: [
          {
            id: 'button-1',
            component: {
              Button: {
                child: 'label-1',
                action: { name: 'approve', context },
              },
            },
          },
          {
            id: 'label-1',
            component: { Text: { text: { literalString: 'Release approval' } } },
          },
        ],
      },
    }),
  ].join('\n');
  return applyA2UISurfaceMessages(createEmptyA2UISurfaceState(), messages);
}

function rendererContext(action) {
  const resolved = {};
  for (const item of action.context) {
    const value = item.value;
    resolved[item.key] =
      value.path ?? value.literalString ?? value.literalNumber ?? value.literalBoolean;
  }
  return resolved;
}

function commandFromRenderer(context) {
  const state = surface(context);
  const rendered = componentsForA2UIRenderer(state.components);
  const action = rendered['button-1'].component.Button.action;
  const resolved = rendererContext(action);
  return {
    iterable: Array.isArray(action.context),
    resolved,
    result: createA2UIActionCommand({
      requestId: 'request-1',
      surfaceId: 'surface-1',
      sourceComponentId: 'button-1',
      actionName: 'approve',
      authorityRevision: 1,
      idempotencyKey: 'idem-1234',
      allowedActions: [{ source_component_id: 'button-1', action_name: 'approve' }],
      context: resolved,
    }),
  };
}

test('v0.8 context maps become renderer arrays and keep key values', () => {
  const observed = commandFromRenderer({
    approved: { literalBoolean: true },
    release: { literalString: '2026.07' },
    attempt: { literalNumber: 2 },
    choice: { path: '/choice' },
  });
  assert.equal(observed.iterable, true);
  assert.deepEqual(observed.resolved, {
    approved: true,
    release: '2026.07',
    attempt: 2,
    choice: '/choice',
  });
  assert.equal(observed.result.ok, true);
  assert.equal(observed.result.command.action_name, 'approve');
  assert.deepEqual(observed.result.command.context.choice, '/choice');
});

test('array context stays iterable and reaches the same command callback', () => {
  const observed = commandFromRenderer([
    { key: 'approved', value: { literalBoolean: true } },
    { key: 'choice', value: { path: '/choice' } },
  ]);
  assert.equal(observed.iterable, true);
  assert.equal(observed.result.ok, true);
  assert.deepEqual(observed.result.command.context, {
    approved: true,
    choice: '/choice',
  });
});

test('a non-iterable context is rejected without throwing in the renderer loop', () => {
  for (const context of [12, 'approve']) {
    const state = surface(context);
    const rendered = componentsForA2UIRenderer(state.components);
    const action = rendered['button-1'].component.Button.action;
    assert.equal(Array.isArray(action.context), true);
    assert.doesNotThrow(() => rendererContext(action));
    assert.equal(isSupportedActionContext(context), false);
    const result = createA2UIActionCommand({
      requestId: 'request-1',
      surfaceId: 'surface-1',
      sourceComponentId: 'button-1',
      actionName: 'approve',
      authorityRevision: 1,
      idempotencyKey: 'idem-1234',
      allowedActions: [{ source_component_id: 'button-1', action_name: 'approve' }],
      context,
    });
    assert.equal(result.ok, false);
    assert.equal(result.reasonCode, 'a2ui_action_context_invalid');
  }
});

test('an unsafe context key is rejected before a command is built', () => {
  const state = surface({ constructor: { literalString: 'no' } });
  assert.equal(state.status, 'invalid');
  assert.equal(state.errorCode, 'a2ui_payload_unsafe');
});
