import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  DESKTOP_ACTIVITY_INBOX_SURFACE_MODULE_REF_V2,
  DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2,
  DESKTOP_SESSION_CANVAS_SURFACE_MODULE_REF_V2,
  DESKTOP_WORKBENCH_SURFACE_MODULE_REF_V2,
  projectDesktopActivityInboxCompositionV2,
  projectDesktopAuthenticatedShellCompositionV2,
  projectDesktopSessionCanvasCompositionV2,
  projectDesktopWorkbenchCompositionV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererCompositionPortV2.js');

const activityInboxSlot = Object.freeze({
  pluginId: 'builtin-shell',
  slot: 'activity_inbox_surface',
  id: 'activity-inbox',
  contract: 'ui-builtin:desktop-activity-inbox-surface',
  moduleRef: DESKTOP_ACTIVITY_INBOX_SURFACE_MODULE_REF_V2,
  permission: 'ui.activity-inbox',
  sandbox: true,
});

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
const sessionCanvasSlot = Object.freeze({
  pluginId: 'builtin-shell',
  slot: 'session_canvas_surface',
  id: 'session-canvas',
  contract: 'ui-builtin:desktop-session-canvas-surface',
  moduleRef: DESKTOP_SESSION_CANVAS_SURFACE_MODULE_REF_V2,
  permission: 'ui.session-canvas',
  sandbox: true,
});

function authority(status = 'ready', slotDefinitions = [workbenchSlot]) {
  return Object.freeze({ status, slotDefinitions });
}

function composition({
  activityInbox = ActivityInboxSurface,
  sessionCanvas = SessionCanvasSurface,
  shell = AuthenticatedShellSurface,
  workbench = WorkbenchSurface,
} = {}) {
  return Object.freeze({
    createAuthenticationRouteRegistry() {
      throw new Error('not used');
    },
    createRouteRegistry() {
      throw new Error('not used');
    },
    resolveActivityInboxSurface(definition) {
      return definition.moduleRef === DESKTOP_ACTIVITY_INBOX_SURFACE_MODULE_REF_V2
        ? activityInbox
        : null;
    },
    resolveAuthenticatedShellSurface(definition) {
      return definition.moduleRef === DESKTOP_AUTHENTICATED_SHELL_SURFACE_MODULE_REF_V2
        ? shell
        : null;
    },
    resolveSessionCanvasSurface(definition) {
      return definition.moduleRef === DESKTOP_SESSION_CANVAS_SURFACE_MODULE_REF_V2
        ? sessionCanvas
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

function ActivityInboxSurface() {
  return null;
}

function SessionCanvasSurface() {
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

test('session canvas composition resolves one explicit active V2 surface contribution', () => {
  assert.deepEqual(
    projectDesktopSessionCanvasCompositionV2(
      authority('ready', [sessionCanvasSlot]),
      composition(),
    ),
    Object.freeze({ status: 'ready', Surface: SessionCanvasSurface }),
  );
  assert.deepEqual(
    projectDesktopSessionCanvasCompositionV2(authority('loading', []), composition()),
    Object.freeze({ status: 'loading' }),
  );
});

test('session canvas composition fails closed for missing, ambiguous, and wrong modules', () => {
  assert.deepEqual(
    projectDesktopSessionCanvasCompositionV2(authority('ready', []), composition()),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_session_canvas_contribution_missing',
    }),
  );
  assert.deepEqual(
    projectDesktopSessionCanvasCompositionV2(
      authority('ready', [sessionCanvasSlot, { ...sessionCanvasSlot, id: 'duplicate' }]),
      composition(),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_session_canvas_contribution_ambiguous',
    }),
  );
  assert.deepEqual(
    projectDesktopSessionCanvasCompositionV2(
      authority('ready', [{ ...sessionCanvasSlot, moduleRef: 'builtin:wrong-session-canvas' }]),
      composition(),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_session_canvas_module_unavailable',
    }),
  );
  assert.deepEqual(
    projectDesktopSessionCanvasCompositionV2(
      authority('ready', [sessionCanvasSlot]),
      composition({ sessionCanvas: null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_session_canvas_module_unavailable',
    }),
  );
});

test('session canvas composition preserves generation failure without static fallback', () => {
  assert.deepEqual(
    projectDesktopSessionCanvasCompositionV2(authority('unavailable', []), composition()),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_generation_unavailable',
    }),
  );
  assert.deepEqual(
    projectDesktopSessionCanvasCompositionV2(authority('disabled', []), composition()),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_generation_disabled',
    }),
  );
});

test('activity inbox composition resolves one explicit active V2 surface contribution', () => {
  assert.deepEqual(
    projectDesktopActivityInboxCompositionV2(
      authority('ready', [activityInboxSlot]),
      composition(),
    ),
    Object.freeze({ status: 'ready', Surface: ActivityInboxSurface }),
  );
  assert.deepEqual(
    projectDesktopActivityInboxCompositionV2(authority('loading', []), composition()),
    Object.freeze({ status: 'loading' }),
  );
});

test('activity inbox composition fails closed for missing, ambiguous, and wrong modules', () => {
  assert.deepEqual(
    projectDesktopActivityInboxCompositionV2(authority('ready', []), composition()),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_activity_inbox_contribution_missing',
    }),
  );
  assert.deepEqual(
    projectDesktopActivityInboxCompositionV2(
      authority('ready', [activityInboxSlot, { ...activityInboxSlot, id: 'duplicate' }]),
      composition(),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_activity_inbox_contribution_ambiguous',
    }),
  );
  assert.deepEqual(
    projectDesktopActivityInboxCompositionV2(
      authority('ready', [{ ...activityInboxSlot, moduleRef: 'builtin:wrong-activity-inbox' }]),
      composition(),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_activity_inbox_module_unavailable',
    }),
  );
  assert.deepEqual(
    projectDesktopActivityInboxCompositionV2(
      authority('ready', [activityInboxSlot]),
      composition({ activityInbox: null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_activity_inbox_module_unavailable',
    }),
  );
});

test('activity inbox composition preserves generation failure without static fallback', () => {
  assert.deepEqual(
    projectDesktopActivityInboxCompositionV2(authority('unavailable', []), composition()),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_generation_unavailable',
    }),
  );
  assert.deepEqual(
    projectDesktopActivityInboxCompositionV2(authority('disabled', []), composition()),
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
