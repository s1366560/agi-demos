import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);

function compiledPlugin(fileName) {
  const nested = `/tmp/agistack-desktop-test-dist/apps/desktop/src/plugins/${fileName}`;
  return existsSync(nested) ? nested : `/tmp/agistack-desktop-test-dist/src/plugins/${fileName}`;
}

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const boundary = source('src/plugins/DesktopRendererTitlebarV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const surface = source('src/plugins/DesktopTitlebarSurfaceV2.tsx');
const titlebar = source('src/features/chrome/DesktopTitlebar.tsx');
const windowControls = source('src/features/chrome/WindowControls.tsx');
const profile = readFileSync(
  new URL(
    '../../../../config/plugin-profiles/memstack-production-target-hosts.v2.yaml',
    import.meta.url,
  ),
  'utf8',
);
const bootstrap = JSON.parse(
  readFileSync(
    new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
    'utf8',
  ),
);

test('native titlebar is selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopTitlebarCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /input\.kind === 'hidden'/u);
  assert.match(boundary, /className="desktop-titlebar"/u);
  assert.match(boundary, /data-titlebar-state=\{composition\.status\}/u);
  assert.doesNotMatch(
    boundary,
    /features\/chrome\/DesktopTitlebar|fallback|acquireOperationLease|meta\.digest/u,
  );
  assert.doesNotMatch(boundary, /\bkey=|use(?:Layout)?Effect|useState|useReducer|useMemo/u);

  assert.match(surface, /export type DesktopTitlebarInputV2/u);
  assert.match(surface, /export interface DesktopTitlebarSurfacePropsV2/u);
  assert.match(surface, /input\.kind === 'hidden'/u);
  assert.match(surface, /<DesktopTitlebar \{\.\.\.input\.props\}\s*\/>/u);
  assert.doesNotMatch(surface, /useDesktopRendererGenerationV2|acquireOperationLease/u);
  assert.doesNotMatch(surface, /use(?:Layout)?Effect|useState|useReducer/u);

  assert.match(shell, /DesktopRendererTitlebarV2/u);
  assert.match(shell, /titlebar:\s*DesktopTitlebarInputV2/u);
  assert.match(shell, /<DesktopRendererTitlebarV2 input=\{surfaces\.titlebar\}\s*\/>/u);
  assert.doesNotMatch(shell, /<DesktopTitlebar\b/u);
  assert.doesNotMatch(shell, /features\/chrome\/DesktopTitlebar/u);
  assert.doesNotMatch(app, /<DesktopTitlebar\b/u);
});

test('titlebar resolver validates the exact builtin same-realm slot contract', () => {
  assert.match(compositionPort, /DESKTOP_TITLEBAR_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveTitlebarSurface/u);
  assert.match(compositionPort, /projectDesktopTitlebarCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_titlebar_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_titlebar_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_titlebar_module_unavailable/u);
  assert.match(composition, /import \{ DesktopTitlebarSurfaceV2 \}/u);
  assert.match(composition, /validTitlebarDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'titlebar_surface'/u);
  assert.match(composition, /definition\.id === 'titlebar'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-titlebar-surface'/u);
  assert.match(composition, /definition\.moduleRef === DESKTOP_TITLEBAR_SURFACE_MODULE_REF_V2/u);
  assert.match(composition, /permission === 'ui\.titlebar'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'titlebar_surface'/u);
  assert.match(sharedSlotTypes, /\| 'titlebar_surface'/u);
});

test('titlebar contribution occupies the reserved order 88 shell seam', () => {
  const artifactDeclaration = new RegExp(
    String.raw`DESKTOP_TITLEBAR_SURFACE_ARTIFACT_ID_V2\s*=\s*\n?\s*` +
      String.raw`'desktop\.ui-slots\.titlebar-surface\.v1'`,
    'u',
  );
  assert.match(artifactCatalog, artifactDeclaration);
  assert.match(artifactCatalog, /slot:\s*'titlebar_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-titlebar-surface'/u);

  const workspaceSettingsIndex = profile.indexOf(
    'entry_id: builtin-desktop-workspace-settings-surface',
  );
  const titlebarIndex = profile.indexOf('entry_id: builtin-desktop-titlebar-surface');
  const tabBarIndex = profile.indexOf('entry_id: builtin-desktop-workbench-tab-bar-surface');
  assert.ok(workspaceSettingsIndex >= 0);
  assert.ok(titlebarIndex > workspaceSettingsIndex);
  assert.ok(tabBarIndex > titlebarIndex);
  const titlebarEntry = profile.slice(titlebarIndex, tabBarIndex);
  assert.match(titlebarEntry, /id:\s*desktop\.titlebar-surface/u);
  assert.match(titlebarEntry, /order:\s*88/u);
  assert.match(titlebarEntry, /desktop\.ui-slots\.titlebar-surface\.v1/u);

  const titlebarBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-titlebar-surface',
  );
  assert.deepEqual(titlebarBootstrap?.config, {
    id: 'desktop.titlebar-surface',
    kind: 'ui-slot',
    order: 88,
    payload: {
      artifact_refs: ['desktop.ui-slots.titlebar-surface.v1'],
      schema_version: 1,
    },
  });
});

test('titlebar projection rejects malformed, duplicate, and inactive generations', () => {
  const { DESKTOP_TITLEBAR_SURFACE_MODULE_REF_V2, projectDesktopTitlebarCompositionV2 } = require(
    compiledPlugin('desktopRendererCompositionPortV2.js'),
  );
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'titlebar_surface',
    id: 'titlebar',
    contract: 'ui-builtin:desktop-titlebar-surface',
    moduleRef: DESKTOP_TITLEBAR_SURFACE_MODULE_REF_V2,
    permission: 'ui.titlebar',
    sandbox: true,
  });
  function TitlebarSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveTitlebarSurface: (definition) =>
      definition.moduleRef === DESKTOP_TITLEBAR_SURFACE_MODULE_REF_V2 ? TitlebarSurface : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  const ready = projectDesktopTitlebarCompositionV2(authority('ready', [slot]), port);
  assert.deepEqual(ready, Object.freeze({ status: 'ready', Surface: TitlebarSurface }));
  const unrelated = projectDesktopTitlebarCompositionV2(
    authority('ready', [slot, { ...slot, slot: 'workbench_surface', id: 'unrelated' }]),
    port,
  );
  assert.equal(unrelated.status, 'ready');
  assert.equal(unrelated.Surface, ready.Surface);
  assert.deepEqual(
    projectDesktopTitlebarCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_titlebar_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_titlebar_contribution_ambiguous',
    ],
    [
      authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-titlebar' }]),
      'desktop_renderer_titlebar_module_unavailable',
    ],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopTitlebarCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopTitlebarCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ resolveTitlebarSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_titlebar_module_unavailable',
    }),
  );
});

test('titlebar keeps App state authority and native bridge lifecycle without fallback', () => {
  assert.match(app, /titlebar:\s*runsInNativeDesktop\s*\?/u);
  assert.match(app, /contextTitle:\s*currentDesktopRouteLabel \? t\(currentDesktopRouteLabel\) : activeSection === 'chat' \? sessionTitle/u);
  assert.match(app, /sidebarCollapsed,/u);
  assert.match(app, /rightSidebarOpen,/u);
  assert.match(app, /onToggleSidebar:\s*\(\) =>/u);
  assert.match(app, /onToggleRightSidebar:\s*toggleRightSidebar/u);

  const projectionIndex = boundary.indexOf('projectDesktopTitlebarCompositionV2');
  const hiddenIndex = boundary.indexOf("input.kind === 'hidden'");
  assert.ok(projectionIndex >= 0);
  assert.ok(hiddenIndex > projectionIndex);
  assert.match(boundary, /desktop-titlebar-traffic-pad/u);
  assert.doesNotMatch(boundary, /<DesktopTitlebar\b|<WindowControls\b/u);

  assert.match(titlebar, /platform === 'darwin'/u);
  assert.match(titlebar, /desktop-titlebar-traffic-pad/u);
  assert.match(titlebar, /platform !== 'darwin' \? <WindowControls\s*\/>/u);
  assert.match(windowControls, /bridge\.isMaximized\(\)/u);
  assert.match(windowControls, /let cancelled = false/u);
  assert.match(windowControls, /cancelled = true/u);
  assert.match(windowControls, /bridge\.minimize\(\)/u);
  assert.match(windowControls, /bridge\.toggleMaximize\(\)/u);
  assert.match(windowControls, /bridge\.close\(\)/u);
});
