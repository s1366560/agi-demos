import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2,
  projectDesktopWorkbenchCompositionV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererCompositionPortV2.js');

const workbenchSlot = Object.freeze({
  pluginId: 'builtin-shell',
  slot: 'workbench_surface',
  id: 'workbench',
  contract: 'ui-builtin:desktop-workbench-surface',
  moduleRef: DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2,
  permission: 'ui.workbench',
  sandbox: true,
});

function authority(status = 'ready', slotDefinitions = [workbenchSlot]) {
  return Object.freeze({ status, slotDefinitions });
}

function composition(resolved = WorkbenchSurface) {
  return Object.freeze({
    createAuthenticationRouteRegistry() {
      throw new Error('not used');
    },
    createRouteRegistry() {
      throw new Error('not used');
    },
    resolveWorkbenchSurface(definition) {
      return definition.moduleRef === DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2 ? resolved : null;
    },
  });
}

function WorkbenchSurface() {
  return null;
}

test('workbench composition resolves only one explicit active V2 surface contribution', () => {
  assert.deepEqual(
    projectDesktopWorkbenchCompositionV2(authority(), composition()),
    Object.freeze({ status: 'ready', Surface: WorkbenchSurface }),
  );
  assert.deepEqual(
    projectDesktopWorkbenchCompositionV2(authority('loading', []), composition()),
    Object.freeze({ status: 'loading' }),
  );
});

test('workbench composition fails closed when the contribution is absent or ambiguous', () => {
  assert.deepEqual(
    projectDesktopWorkbenchCompositionV2(authority('ready', []), composition()),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_workbench_contribution_missing',
    }),
  );
  assert.deepEqual(
    projectDesktopWorkbenchCompositionV2(
      authority('ready', [workbenchSlot, { ...workbenchSlot, id: 'duplicate' }]),
      composition(),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_workbench_contribution_ambiguous',
    }),
  );
  assert.deepEqual(
    projectDesktopWorkbenchCompositionV2(authority(), composition(null)),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_workbench_module_unavailable',
    }),
  );
});

test('workbench composition preserves generation failure without exposing static children', () => {
  assert.deepEqual(
    projectDesktopWorkbenchCompositionV2(authority('unavailable', []), composition()),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_generation_unavailable',
    }),
  );
  assert.deepEqual(
    projectDesktopWorkbenchCompositionV2(authority('disabled', []), composition()),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_generation_disabled',
    }),
  );
});
