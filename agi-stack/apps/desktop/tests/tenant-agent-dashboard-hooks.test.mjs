import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  buildEditableRuntimeHooks,
  createCustomRuntimeHook,
  parseRuntimeHookSettings,
  serializeRuntimeHooks,
  validateRuntimeHook,
} =
  await import('/tmp/agistack-desktop-test-dist/src/features/tenant/tenantAgentDashboardHooks.js');

test('Agent Dashboard builds catalog hooks and preserves unmanaged custom hooks', () => {
  const result = buildEditableRuntimeHooks(
    [
      hook({ enabled: false, priority: 25, settings: { redact: true } }),
      hook({
        hookName: 'custom_audit',
        pluginName: '',
        executorKind: 'script',
        sourceRef: 'workspace/hooks.py',
        entrypoint: 'run',
      }),
    ],
    [catalog()],
  );

  assert.equal(result.managed.length, 1);
  assert.equal(result.managed[0].enabled, false);
  assert.equal(result.managed[0].priority, 25);
  assert.deepEqual(result.managed[0].settings, { redact: true });
  assert.equal(result.custom.length, 1);
  assert.equal(result.custom[0].hookName, 'custom_audit');
});

test('Agent Dashboard serializes customized catalog hooks and custom hooks', () => {
  const built = buildEditableRuntimeHooks([], [catalog()]);
  const managed = [
    {
      ...built.managed[0],
      enabled: false,
      priority: 40,
      settings: { redact: false },
    },
  ];
  const custom = [
    {
      ...createCustomRuntimeHook(),
      hookName: 'custom_audit',
      sourceRef: 'workspace/hooks.py',
      entrypoint: 'run',
      settings: { level: 'strict' },
    },
  ];

  assert.deepEqual(serializeRuntimeHooks(managed, custom, [catalog()]), [managed[0], custom[0]]);
});

test('Agent Dashboard validates custom hook identity and JSON settings structurally', () => {
  assert.deepEqual(parseRuntimeHookSettings('{"redact":true}'), {
    settings: { redact: true },
    reasonCode: null,
  });
  assert.equal(
    parseRuntimeHookSettings('[]').reasonCode,
    'tenant_agent_dashboard_hook_settings_object_required',
  );
  assert.equal(
    parseRuntimeHookSettings('{').reasonCode,
    'tenant_agent_dashboard_hook_settings_json_invalid',
  );
  assert.deepEqual(validateRuntimeHook(createCustomRuntimeHook()), [
    'tenant_agent_dashboard_hook_name_required',
    'tenant_agent_dashboard_hook_source_required',
  ]);
});

function catalog() {
  return {
    key: 'audit.before_tool',
    hookName: 'before_tool',
    pluginName: 'audit',
    hookFamily: 'policy',
    displayName: 'Before tool',
    description: 'Audit before tool execution',
    defaultPriority: 10,
    defaultEnabled: true,
    defaultExecutorKind: 'plugin',
    defaultSourceRef: 'audit',
    defaultEntrypoint: 'before_tool',
    defaultSettings: { redact: true },
    settingsSchema: {
      properties: {
        redact: { type: 'boolean', title: 'Redact' },
      },
    },
  };
}

function hook(overrides = {}) {
  return {
    hookName: 'before_tool',
    pluginName: 'audit',
    hookFamily: 'policy',
    executorKind: 'plugin',
    sourceRef: 'audit',
    entrypoint: 'before_tool',
    enabled: true,
    priority: 10,
    settings: { redact: true },
    ...overrides,
  };
}
