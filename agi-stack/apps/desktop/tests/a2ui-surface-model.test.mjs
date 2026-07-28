import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  applyA2UISurfaceMessages,
  createA2UIActionCommand,
  createEmptyA2UISurfaceState,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/a2uiSurfaceModel.js');

function line(value) {
  return JSON.stringify(value);
}

function initialSurface() {
  return [
    line({ beginRendering: { surfaceId: 'surface-1', root: 'root' } }),
    line({
      surfaceUpdate: {
        surfaceId: 'surface-1',
        components: [
          {
            id: 'root',
            component: {
              Column: { children: { explicitList: ['title', 'choice', 'submit'] } },
            },
          },
          {
            id: 'title',
            component: { Text: { text: { literalString: 'Release approval' } } },
          },
          {
            id: 'choice',
            component: {
              Select: {
                options: [
                  { label: 'Ship', value: 'ship' },
                  { label: 'Hold', value: 'hold' },
                ],
              },
            },
          },
          {
            id: 'submit',
            component: {
              Button: {
                child: 'title',
                action: {
                  name: 'approve',
                  context: {
                    confirmed: { literalBoolean: true },
                    channel: { literalString: 'stable' },
                  },
                },
              },
            },
          },
        ],
      },
    }),
    line({
      dataModelUpdate: {
        surfaceId: 'surface-1',
        path: '/form',
        contents: { choice: 'ship' },
      },
    }),
  ].join('\n');
}

test('applies A2UI v0.8 begin, incremental surface, and data-model updates', () => {
  const created = applyA2UISurfaceMessages(createEmptyA2UISurfaceState(), initialSurface());
  assert.equal(created.status, 'ready');
  assert.equal(created.surfaceId, 'surface-1');
  assert.equal(created.rootId, 'root');
  assert.deepEqual(Object.keys(created.components).sort(), ['choice', 'root', 'submit', 'title']);
  assert.deepEqual(created.dataModel, { form: { choice: 'ship' } });

  const updated = applyA2UISurfaceMessages(
    created,
    line({
      surfaceUpdate: {
        surfaceId: 'surface-1',
        components: [
          {
            id: 'title',
            component: { Badge: { text: { literalString: 'Approved' } } },
          },
        ],
      },
    }),
  );

  assert.equal(updated.status, 'ready');
  assert.deepEqual(updated.components.title.component, {
    Badge: { text: { literalString: 'Approved' } },
  });
  assert.deepEqual(updated.components.submit.component.Button.action.context, {
    confirmed: { literalBoolean: true },
    channel: { literalString: 'stable' },
  });
});

test('supports the complete Desktop registry and normalizes renderer aliases', () => {
  const kinds = [
    'Text',
    'Button',
    'Card',
    'Column',
    'List',
    'Row',
    'TextField',
    'Divider',
    'Image',
    'Checkbox',
    'Select',
    'Radio',
    'Badge',
    'Tabs',
    'Modal',
    'Table',
    'Progress',
  ];
  const aliases = [
    { id: 'checkbox-alias', component: { CheckBox: {} } },
    { id: 'select-alias', component: { MultipleChoice: {} } },
  ];
  const components = [
    {
      id: 'root',
      component: {
        Column: {
          children: {
            explicitList: [...kinds.map((kind) => kind.toLowerCase()), ...aliases.map(({ id }) => id)],
          },
        },
      },
    },
    ...kinds.map((kind) => ({
      id: kind.toLowerCase(),
      component: { [kind]: {} },
    })),
    ...aliases,
  ];

  const state = applyA2UISurfaceMessages(
    createEmptyA2UISurfaceState(),
    [
      line({ beginRendering: { surfaceId: 'registry', root: 'root' } }),
      line({ surfaceUpdate: { surfaceId: 'registry', components } }),
    ].join('\n'),
  );

  assert.equal(state.status, 'ready', state.errorCode ?? undefined);
  assert.ok(state.components.checkbox.component.Checkbox);
  assert.ok(state.components.select.component.Select);
  assert.ok(state.components['checkbox-alias'].component.Checkbox);
  assert.ok(state.components['select-alias'].component.Select);
});

test('fails closed for mixed surfaces, unsupported components, and dangerous keys', () => {
  const mixed = applyA2UISurfaceMessages(
    createEmptyA2UISurfaceState(),
    `${initialSurface()}\n${line({
      surfaceUpdate: { surfaceId: 'surface-2', components: [] },
    })}`,
  );
  assert.equal(mixed.status, 'invalid');
  assert.equal(mixed.errorCode, 'a2ui_surface_mismatch');
  assert.deepEqual(mixed.components, {});

  const unsupported = applyA2UISurfaceMessages(
    createEmptyA2UISurfaceState(),
    [
      line({ beginRendering: { surfaceId: 'surface-1', root: 'root' } }),
      line({
        surfaceUpdate: {
          surfaceId: 'surface-1',
          components: [{ id: 'root', component: { Script: { source: 'alert(1)' } } }],
        },
      }),
    ].join('\n'),
  );
  assert.equal(unsupported.status, 'invalid');
  assert.equal(unsupported.errorCode, 'a2ui_component_unsupported');

  const dangerous = applyA2UISurfaceMessages(
    createEmptyA2UISurfaceState(),
    '{"beginRendering":{"surfaceId":"surface-1","root":"root"},"constructor":{"polluted":true}}',
  );
  assert.equal(dangerous.status, 'invalid');
  assert.equal(dangerous.errorCode, 'a2ui_payload_unsafe');
});

test('enforces payload, component count, and render-tree depth limits', () => {
  const oversized = applyA2UISurfaceMessages(
    createEmptyA2UISurfaceState(),
    ' '.repeat(128 * 1024 + 1),
  );
  assert.equal(oversized.errorCode, 'a2ui_payload_too_large');

  const tooManyComponents = Array.from({ length: 129 }, (_, index) => ({
    id: `node-${index}`,
    component: { Text: { text: { literalString: String(index) } } },
  }));
  const countLimited = applyA2UISurfaceMessages(
    createEmptyA2UISurfaceState(),
    [
      line({ beginRendering: { surfaceId: 'surface-1', root: 'node-0' } }),
      line({
        surfaceUpdate: { surfaceId: 'surface-1', components: tooManyComponents },
      }),
    ].join('\n'),
  );
  assert.equal(countLimited.errorCode, 'a2ui_component_limit_exceeded');

  const deepComponents = Array.from({ length: 34 }, (_, index) => ({
    id: `node-${index}`,
    component:
      index === 33
        ? { Text: { text: { literalString: 'leaf' } } }
        : { Column: { children: { explicitList: [`node-${index + 1}`] } } },
  }));
  const depthLimited = applyA2UISurfaceMessages(
    createEmptyA2UISurfaceState(),
    [
      line({ beginRendering: { surfaceId: 'surface-1', root: 'node-0' } }),
      line({
        surfaceUpdate: { surfaceId: 'surface-1', components: deepComponents },
      }),
    ].join('\n'),
  );
  assert.equal(depthLimited.errorCode, 'a2ui_tree_depth_exceeded');
});

test('deleteSurface clears prior state so stale controls cannot remain interactive', () => {
  const created = applyA2UISurfaceMessages(createEmptyA2UISurfaceState(), initialSurface());
  const deleted = applyA2UISurfaceMessages(
    created,
    line({ deleteSurface: { surfaceId: 'surface-1' } }),
  );

  assert.deepEqual(deleted, {
    status: 'deleted',
    surfaceId: 'surface-1',
    rootId: null,
    components: {},
    dataModel: {},
    errorCode: null,
  });
});

test('builds an authority-bound action command only from a persisted allow-list', () => {
  const result = createA2UIActionCommand({
    requestId: 'request-1',
    surfaceId: 'surface-1',
    sourceComponentId: 'submit',
    actionName: 'approve',
    authorityRevision: 7,
    idempotencyKey: 'idem-123',
    context: {
      confirmed: { literalBoolean: true },
      channel: { literalString: 'stable' },
      retries: { literalNumber: 2 },
    },
    allowedActions: [{ source_component_id: 'submit', action_name: 'approve' }],
  });

  assert.deepEqual(result, {
    ok: true,
    command: {
      contract_version: 1,
      request_id: 'request-1',
      surface_id: 'surface-1',
      source_component_id: 'submit',
      action_name: 'approve',
      authority_revision: 7,
      idempotency_key: 'idem-123',
      context: { confirmed: true, channel: 'stable', retries: 2 },
    },
  });

  const denied = createA2UIActionCommand({
    requestId: 'request-1',
    surfaceId: 'surface-1',
    sourceComponentId: 'submit',
    actionName: 'reject',
    authorityRevision: 7,
    idempotencyKey: 'idem-123',
    allowedActions: [{ source_component_id: 'submit', action_name: 'approve' }],
  });
  assert.deepEqual(denied, { ok: false, reasonCode: 'a2ui_action_not_allowed' });
});

test('rejects path-bound, nested, non-finite, and oversized action context', () => {
  const base = {
    requestId: 'request-1',
    surfaceId: 'surface-1',
    sourceComponentId: 'submit',
    actionName: 'approve',
    authorityRevision: 7,
    idempotencyKey: 'idem-123',
    allowedActions: [{ sourceComponentId: 'submit', actionName: 'approve' }],
  };

  assert.deepEqual(
    createA2UIActionCommand({ ...base, context: { secret: { path: '/env/API_KEY' } } }),
    { ok: false, reasonCode: 'a2ui_action_context_invalid' },
  );
  assert.deepEqual(
    createA2UIActionCommand({ ...base, context: { nested: { literal: { unsafe: true } } } }),
    { ok: false, reasonCode: 'a2ui_action_context_invalid' },
  );
  assert.deepEqual(
    createA2UIActionCommand({ ...base, context: { number: Number.POSITIVE_INFINITY } }),
    { ok: false, reasonCode: 'a2ui_action_context_invalid' },
  );
  assert.deepEqual(
    createA2UIActionCommand({ ...base, context: { large: 'x'.repeat(4097) } }),
    { ok: false, reasonCode: 'a2ui_action_context_invalid' },
  );
});
