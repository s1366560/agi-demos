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
const boundary = source('src/plugins/DesktopRendererWorkbenchTabBarV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const surface = source('src/plugins/DesktopWorkbenchTabBarSurfaceV2.tsx');
const tabBar = source('src/features/chrome/WorkbenchTabBar.tsx');
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

test('workbench tab bar is selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopWorkbenchTabBarCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /className="workbench-tab-bar"/u);
  assert.match(boundary, /data-workbench-tab-bar-state=\{composition\.status\}/u);
  assert.doesNotMatch(
    boundary,
    /features\/chrome\/WorkbenchTabBar|fallback|acquireOperationLease|meta\.digest/u,
  );
  assert.doesNotMatch(boundary, /\bkey=|use(?:Layout)?Effect|useState|useReducer|useMemo/u);

  assert.match(surface, /export type DesktopWorkbenchTabBarInputV2/u);
  assert.match(surface, /export interface DesktopWorkbenchTabBarSurfacePropsV2/u);
  assert.match(surface, /<WorkbenchTabBar \{\.\.\.input\}\s*\/>/u);
  assert.doesNotMatch(surface, /useDesktopRendererGenerationV2|acquireOperationLease/u);
  assert.doesNotMatch(surface, /use(?:Layout)?Effect|useState|useReducer/u);

  assert.match(shell, /DesktopRendererWorkbenchTabBarV2/u);
  assert.match(shell, /tabBar:\s*DesktopWorkbenchTabBarInputV2/u);
  assert.match(shell, /<DesktopRendererWorkbenchTabBarV2 input=\{surfaces\.tabBar\}\s*\/>/u);
  assert.doesNotMatch(shell, /<WorkbenchTabBar\b/u);
  assert.doesNotMatch(shell, /features\/chrome\/WorkbenchTabBar/u);
  assert.doesNotMatch(app, /<WorkbenchTabBar\b/u);
});

test('workbench tab bar resolver validates the exact builtin same-realm slot contract', () => {
  assert.match(compositionPort, /DESKTOP_WORKBENCH_TAB_BAR_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveWorkbenchTabBarSurface/u);
  assert.match(compositionPort, /projectDesktopWorkbenchTabBarCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_workbench_tab_bar_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_workbench_tab_bar_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_workbench_tab_bar_module_unavailable/u);
  assert.match(composition, /import \{ DesktopWorkbenchTabBarSurfaceV2 \}/u);
  assert.match(composition, /validWorkbenchTabBarDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'workbench_tab_bar_surface'/u);
  assert.match(composition, /definition\.id === 'workbench-tab-bar'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-workbench-tab-bar-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_WORKBENCH_TAB_BAR_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.workbench-tabs'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'workbench_tab_bar_surface'/u);
  assert.match(sharedSlotTypes, /\| 'workbench_tab_bar_surface'/u);
});

test('workbench tab bar contribution occupies the order 89 shell seam', () => {
  const artifactDeclaration = new RegExp(
    String.raw`DESKTOP_WORKBENCH_TAB_BAR_SURFACE_ARTIFACT_ID_V2\s*=\s*\n?\s*` +
      String.raw`'desktop\.ui-slots\.workbench-tab-bar-surface\.v1'`,
    'u',
  );
  assert.match(artifactCatalog, artifactDeclaration);
  assert.match(artifactCatalog, /slot:\s*'workbench_tab_bar_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-workbench-tab-bar-surface'/u);

  const workspaceSettingsIndex = profile.indexOf(
    'entry_id: builtin-desktop-workspace-settings-surface',
  );
  const tabBarIndex = profile.indexOf('entry_id: builtin-desktop-workbench-tab-bar-surface');
  const workbenchIndex = profile.indexOf('entry_id: builtin-desktop-workbench-surface');
  assert.ok(workspaceSettingsIndex >= 0);
  assert.ok(tabBarIndex > workspaceSettingsIndex);
  assert.ok(workbenchIndex > tabBarIndex);
  const tabBarEntry = profile.slice(tabBarIndex, workbenchIndex);
  assert.match(tabBarEntry, /id:\s*desktop\.workbench-tab-bar-surface/u);
  assert.match(tabBarEntry, /order:\s*89/u);
  assert.match(tabBarEntry, /desktop\.ui-slots\.workbench-tab-bar-surface\.v1/u);

  const tabBarBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workbench-tab-bar-surface',
  );
  assert.deepEqual(tabBarBootstrap?.config, {
    id: 'desktop.workbench-tab-bar-surface',
    kind: 'ui-slot',
    order: 89,
    payload: {
      artifact_refs: ['desktop.ui-slots.workbench-tab-bar-surface.v1'],
      schema_version: 1,
    },
  });
});

test('workbench tab bar projection rejects malformed, duplicate, and inactive generations', () => {
  const {
    DESKTOP_WORKBENCH_TAB_BAR_SURFACE_MODULE_REF_V2,
    projectDesktopWorkbenchTabBarCompositionV2,
  } = require(compiledPlugin('desktopRendererCompositionPortV2.js'));
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'workbench_tab_bar_surface',
    id: 'workbench-tab-bar',
    contract: 'ui-builtin:desktop-workbench-tab-bar-surface',
    moduleRef: DESKTOP_WORKBENCH_TAB_BAR_SURFACE_MODULE_REF_V2,
    permission: 'ui.workbench-tabs',
    sandbox: true,
  });
  function WorkbenchTabBarSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveWorkbenchTabBarSurface: (definition) =>
      definition.moduleRef === DESKTOP_WORKBENCH_TAB_BAR_SURFACE_MODULE_REF_V2
        ? WorkbenchTabBarSurface
        : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  const ready = projectDesktopWorkbenchTabBarCompositionV2(authority('ready', [slot]), port);
  assert.deepEqual(ready, Object.freeze({ status: 'ready', Surface: WorkbenchTabBarSurface }));
  const unrelated = projectDesktopWorkbenchTabBarCompositionV2(
    authority('ready', [slot, { ...slot, slot: 'workbench_surface', id: 'unrelated' }]),
    port,
  );
  assert.equal(unrelated.status, 'ready');
  assert.deepEqual(
    projectDesktopWorkbenchTabBarCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_workbench_tab_bar_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_workbench_tab_bar_contribution_ambiguous',
    ],
    [
      authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-workbench-tab-bar' }]),
      'desktop_renderer_workbench_tab_bar_module_unavailable',
    ],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopWorkbenchTabBarCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopWorkbenchTabBarCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ resolveWorkbenchTabBarSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_workbench_tab_bar_module_unavailable',
    }),
  );
});

test('hidden tab bar preserves its input interface and App ownership', () => {
  assert.match(tabBar, /return null/u);
  assert.doesNotMatch(tabBar, /role="tablist"|tabs\.map/u);
  assert.match(tabBar, /onActivate: \(tab: WorkbenchTab\) => void/u);
  assert.match(tabBar, /onClose: \(tab: WorkbenchTab\) => void/u);

  const inputStart = app.indexOf('tabBar: {');
  const inputEnd = app.indexOf('router: {', inputStart);
  const input = app.slice(inputStart, inputEnd);
  assert.match(input, /tabs:\s*openTabs/u);
  assert.match(input, /activeTabKey:\s*activeWorkbenchTabKey/u);
  assert.match(input, /onActivate:\s*activateWorkbenchTab/u);
  assert.match(input, /onClose:\s*closeWorkbenchTab/u);
});
