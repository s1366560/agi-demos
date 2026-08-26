import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2,
  DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2,
  projectDesktopAuthenticatedShellCompositionV2,
  projectDesktopWorkbenchCompositionV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererCompositionPortV2.js');

const authenticatedShellSlot = Object.freeze({
  pluginId: 'builtin-shell',
  slot: 'authenticated_shell_surface',
  id: 'authenticated-shell',
  contract: 'ui-builtin:desktop-authenticated-shell-surface',
  moduleRef: DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2,
  permission: 'ui.authenticated-shell',
  sandbox: true,
});
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

function composition({ shell = AuthenticatedShellSurface, workbench = WorkbenchSurface } = {}) {
  return Object.freeze({
    createAuthenticationRouteRegistry() {
      throw new Error('not used');
    },
    createRouteRegistry() {
      throw new Error('not used');
    },
    resolveAuthenticatedShellSurface(definition) {
      return definition.moduleRef === DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2
        ? shell
        : null;
    },
    resolveWorkbenchSurface(definition) {
      return definition.moduleRef === DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2 ? workbench : null;
    },
  });
}

function AuthenticatedShellSurface() {
  return null;
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
    projectDesktopWorkbenchCompositionV2(authority(), composition({ workbench: null })),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_workbench_module_unavailable',
    }),
  );
});

test('authenticated shell composition resolves one explicit active V2 surface contribution', () => {
  assert.deepEqual(
    projectDesktopAuthenticatedShellCompositionV2(
      authority('ready', [authenticatedShellSlot]),
      composition(),
    ),
    Object.freeze({ status: 'ready', Surface: AuthenticatedShellSurface }),
  );
  assert.deepEqual(
    projectDesktopAuthenticatedShellCompositionV2(authority('loading', []), composition()),
    Object.freeze({ status: 'loading' }),
  );
});

test('authenticated shell composition fails closed for missing and ambiguous contributions', () => {
  assert.deepEqual(
    projectDesktopAuthenticatedShellCompositionV2(authority('ready', []), composition()),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_authenticated_shell_contribution_missing',
    }),
  );
  assert.deepEqual(
    projectDesktopAuthenticatedShellCompositionV2(
      authority('ready', [authenticatedShellSlot, { ...authenticatedShellSlot, id: 'duplicate' }]),
      composition(),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_authenticated_shell_contribution_ambiguous',
    }),
  );
});

test('authenticated shell composition rejects unavailable and wrong modules', () => {
  assert.deepEqual(
    projectDesktopAuthenticatedShellCompositionV2(
      authority('ready', [
        {
          ...authenticatedShellSlot,
          moduleRef: 'builtin:wrong-authenticated-shell',
        },
      ]),
      composition(),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_authenticated_shell_module_unavailable',
    }),
  );
  assert.deepEqual(
    projectDesktopAuthenticatedShellCompositionV2(
      authority('ready', [authenticatedShellSlot]),
      composition({ shell: null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_authenticated_shell_module_unavailable',
    }),
  );
  assert.deepEqual(
    projectDesktopAuthenticatedShellCompositionV2(authority('unavailable', []), composition()),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_generation_unavailable',
    }),
  );
  assert.deepEqual(
    projectDesktopAuthenticatedShellCompositionV2(authority('disabled', []), composition()),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_generation_disabled',
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
