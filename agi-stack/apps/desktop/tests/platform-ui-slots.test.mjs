import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { UiSlotRegistry, UiSlotRegistrationError } =
  require('/tmp/agistack-desktop-test-dist/src/plugins/uiSlotRegistry.js');

const definition = {
  pluginId: 'builtin-ui',
  slot: 'tool_result_renderer',
  id: 'custom-renderer',
  moduleRef: 'builtin:custom-renderer',
  permission: 'ui.render.custom',
  sandbox: true,
};

test('builtin sandboxed frontend slot registers and disposes exactly once', () => {
  const registry = new UiSlotRegistry();
  const dispose = registry.register(definition, {
    trust: 'builtin',
    runtime: 'frontend',
  });

  assert.deepEqual(registry.list('tool_result_renderer'), [
    { ...definition, trust: 'builtin', runtime: 'frontend' },
  ]);
  dispose();
  assert.deepEqual(registry.list('tool_result_renderer'), []);
});

test('ui slot registry rejects external code and unsandboxed renderers', () => {
  const registry = new UiSlotRegistry();

  assert.throws(
    () =>
      registry.register(definition, {
        trust: 'tenant-approved',
        runtime: 'frontend',
      }),
    /External frontend modules/,
  );
  assert.throws(
    () =>
      registry.register(
        { ...definition, sandbox: false },
        { trust: 'builtin', runtime: 'frontend' },
      ),
    /sandbox/,
  );
  assert.throws(
    () =>
      registry.register(
        { ...definition, moduleRef: 'https://example.test/module.js' },
        { trust: 'builtin', runtime: 'frontend' },
      ),
    /builtin or signed frontend modules/,
  );
});
