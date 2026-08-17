import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { UiSlotRuntime } =
  require('/tmp/agistack-desktop-test-dist/src/plugins/uiSlotRuntime.js');
const { UiSlotRegistry } =
  require('/tmp/agistack-desktop-test-dist/src/plugins/uiSlotRegistry.js');
const { usePlatformPluginUiSlots } = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/usePlatformPluginUiSlots.js'
);
const { builtinUiFallbackSnapshot } = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/usePlatformPluginUiSlots.js'
);

const definition = {
  pluginId: 'builtin-ui',
  slot: 'settings_page',
  id: 'plugin-settings',
  moduleRef: 'builtin:plugin-settings',
  permission: 'ui.settings.plugins',
  sandbox: true,
};

test('ui slot runtime reconciles slots from a canonical plugin snapshot', () => {
  const runtime = new UiSlotRuntime(new UiSlotRegistry());
  const state = runtime.reconcile(
    {
      plugins: [
        {
          schema_version: 1,
          id: 'builtin-ui',
          version: '1.0.0',
          runtime: 'frontend',
          trust: 'builtin',
          provides: [],
          config: {},
        },
      ],
    },
    [definition],
  );

  assert.equal(state.slots.length, 1);

  const disabled = runtime.reconcile({ plugins: [] }, [definition]);
  assert.equal(disabled.slots.length, 0);
});

test('desktop settings hook exports a canonical-snapshot ui slot boundary', () => {
  assert.equal(typeof usePlatformPluginUiSlots, 'function');
});

test('builtin ui slots remain available when canonical snapshot is unavailable', () => {
  const runtime = new UiSlotRuntime(new UiSlotRegistry());
  const state = runtime.reconcile(builtinUiFallbackSnapshot(), [definition]);

  assert.equal(state.slots.length, 1);
  assert.equal(state.slots[0].moduleRef, 'builtin:plugin-settings');
});

test('signed canonical ui slots register with signed module trust', () => {
  const artifactDigest = 'a'.repeat(64);
  const runtime = new UiSlotRuntime(new UiSlotRegistry());
  const state = runtime.reconcile(
    {
      plugins: [
        {
          schema_version: 1,
          id: 'native-signed-ui',
          version: '1.0.0',
          runtime: 'frontend',
          trust: 'signed',
          provides: [],
          config: { artifact: { layer_sha256: artifactDigest } },
        },
      ],
    },
    [
      {
        pluginId: 'native-signed-ui',
        slot: 'tool_result_renderer',
        id: 'tool_result_renderer',
        moduleRef: `signed:${artifactDigest}`,
        permission: 'ui.render',
        sandbox: true,
      },
    ],
  );

  assert.equal(state.slots.length, 1);
  assert.equal(state.slots[0].trust, 'signed');
});
