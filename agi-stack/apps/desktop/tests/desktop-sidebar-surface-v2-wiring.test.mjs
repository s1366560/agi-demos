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
const boundary = source('src/plugins/DesktopRendererSidebarV2.tsx');
const chromeStyles = source('src/styles/chrome.css');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const resizeHandle = source('src/components/ResizeHandle.tsx');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const sidebar = source('src/features/navigation/DesktopSidebar.tsx');
const sidebarStyles = source('src/features/navigation/DesktopSidebar.css');
const surface = source('src/plugins/DesktopSidebarSurfaceV2.tsx');
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

test('sidebar is selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopSidebarCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /<aside\s+className="desktop-design-sidebar"/u);
  assert.match(boundary, /data-sidebar-state=\{composition\.status\}/u);
  assert.match(boundary, /data-reason-code=\{loading \? undefined : composition\.reasonCode\}/u);
  assert.doesNotMatch(
    boundary,
    /features\/navigation\/DesktopSidebar|components\/ResizeHandle|WorkspaceDock|fallback|acquireOperationLease|meta\.digest|generation(?:Digest|Version)|\bkey=/u,
  );
  assert.doesNotMatch(boundary, /use(?:Layout)?Effect|useState|useReducer|useMemo/u);

  assert.match(surface, /export interface DesktopSidebarInputV2/u);
  assert.match(surface, /export interface DesktopSidebarSurfacePropsV2/u);
  assert.match(surface, /props:\s*Omit<ComponentProps<typeof DesktopSidebar>, 'resizeHandle'>/u);
  assert.match(surface, /kind:\s*'hidden'/u);
  assert.match(surface, /kind:\s*'visible'/u);
  assert.match(surface, /<ResizeHandle \{\.\.\.input\.resizeHandle\.props\}\s*\/>/u);
  assert.match(
    surface,
    /<DesktopSidebar \{\.\.\.input\.props\} resizeHandle=\{resizeHandle\}\s*\/>/u,
  );
  assert.doesNotMatch(surface, /useDesktopRendererGenerationV2|acquireOperationLease/u);
  assert.doesNotMatch(surface, /\bkey=|use(?:Layout)?Effect|useState|useReducer|useMemo/u);

  assert.match(shell, /DesktopRendererSidebarV2/u);
  assert.match(shell, /sidebar:\s*DesktopSidebarInputV2/u);
  assert.match(shell, /<DesktopRendererSidebarV2 input=\{surfaces\.sidebar\}\s*\/>/u);
  assert.doesNotMatch(shell, /<DesktopSidebar\b|<ResizeHandle\b/u);
  assert.doesNotMatch(shell, /features\/navigation\/DesktopSidebar|components\/ResizeHandle/u);
  assert.doesNotMatch(app, /<DesktopSidebar\b|<ResizeHandle\b/u);
});

test('sidebar resolver validates the exact builtin same-realm slot contract', () => {
  assert.match(compositionPort, /DESKTOP_SIDEBAR_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveSidebarSurface/u);
  assert.match(compositionPort, /projectDesktopSidebarCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_sidebar_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_sidebar_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_sidebar_module_unavailable/u);
  assert.match(composition, /import \{ DesktopSidebarSurfaceV2 \}/u);
  assert.match(composition, /validSidebarDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'sidebar_surface'/u);
  assert.match(composition, /definition\.id === 'sidebar'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-sidebar-surface'/u);
  assert.match(composition, /definition\.moduleRef === DESKTOP_SIDEBAR_SURFACE_MODULE_REF_V2/u);
  assert.match(composition, /permission === 'ui\.sidebar'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'sidebar_surface'/u);
  assert.match(sharedSlotTypes, /\| 'sidebar_surface'/u);
});

test('sidebar contribution occupies the reserved order 99 shell seam', () => {
  const artifactDeclaration = new RegExp(
    String.raw`DESKTOP_SIDEBAR_SURFACE_ARTIFACT_ID_V2\s*=\s*\n?\s*` +
      String.raw`'desktop\.ui-slots\.sidebar-surface\.v1'`,
    'u',
  );
  assert.match(artifactCatalog, artifactDeclaration);
  assert.match(artifactCatalog, /slot:\s*'sidebar_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-sidebar-surface'/u);

  const toolResultIndex = profile.indexOf('entry_id: builtin-desktop-tool-result-renderer');
  const sidebarIndex = profile.indexOf('entry_id: builtin-desktop-sidebar-surface');
  const routesIndex = profile.indexOf('entry_id: builtin-desktop-tenant-creation-routes');
  assert.ok(toolResultIndex >= 0);
  assert.ok(sidebarIndex > toolResultIndex);
  assert.ok(routesIndex > sidebarIndex);
  const sidebarEntry = profile.slice(sidebarIndex, routesIndex);
  assert.match(sidebarEntry, /id:\s*desktop\.sidebar-surface/u);
  assert.match(sidebarEntry, /order:\s*99/u);
  assert.match(sidebarEntry, /desktop\.ui-slots\.sidebar-surface\.v1/u);

  const sidebarBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-sidebar-surface',
  );
  assert.deepEqual(sidebarBootstrap?.config, {
    id: 'desktop.sidebar-surface',
    kind: 'ui-slot',
    order: 99,
    payload: {
      artifact_refs: ['desktop.ui-slots.sidebar-surface.v1'],
      schema_version: 1,
    },
  });
});

test('sidebar projection rejects malformed, duplicate, and inactive generations', () => {
  const { DESKTOP_SIDEBAR_SURFACE_MODULE_REF_V2, projectDesktopSidebarCompositionV2 } = require(
    compiledPlugin('desktopRendererCompositionPortV2.js'),
  );
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'sidebar_surface',
    id: 'sidebar',
    contract: 'ui-builtin:desktop-sidebar-surface',
    moduleRef: DESKTOP_SIDEBAR_SURFACE_MODULE_REF_V2,
    permission: 'ui.sidebar',
    sandbox: true,
  });
  function SidebarSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveSidebarSurface: (definition) =>
      definition.moduleRef === DESKTOP_SIDEBAR_SURFACE_MODULE_REF_V2 ? SidebarSurface : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  const ready = projectDesktopSidebarCompositionV2(authority('ready', [slot]), port);
  assert.deepEqual(ready, Object.freeze({ status: 'ready', Surface: SidebarSurface }));
  const unrelated = projectDesktopSidebarCompositionV2(
    authority('ready', [slot, { ...slot, slot: 'workbench_surface', id: 'unrelated' }]),
    port,
  );
  assert.equal(unrelated.status, 'ready');
  assert.equal(unrelated.Surface, ready.Surface);
  assert.deepEqual(
    projectDesktopSidebarCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_sidebar_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_sidebar_contribution_ambiguous',
    ],
    [
      authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-sidebar' }]),
      'desktop_renderer_sidebar_module_unavailable',
    ],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopSidebarCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopSidebarCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ resolveSidebarSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_sidebar_module_unavailable',
    }),
  );
});

test('sidebar seam preserves owner state, local lifecycles, and failure layout', () => {
  assert.match(app, /const \[sidebarCollapsed, setSidebarCollapsed\] = useState\(false\)/u);
  assert.match(app, /useResizablePanelWidth\(/u);
  assert.match(app, /sidebarPreferredWidth:\s*sidebarPanelWidth\.width/u);
  assert.match(app, /sidebar:\s*\{[\s\S]*props:\s*\{[\s\S]*onNavigate:/u);
  assert.match(app, /resizeHandle:\s*sidebarCollapsed\s*\?/u);
  assert.match(app, /onResize:\s*sidebarPanelWidth\.resize/u);
  assert.match(app, /onReset:\s*sidebarPanelWidth\.reset/u);

  assert.match(sidebar, /const \[profileOpen, setProfileOpen\] = useState\(false\)/u);
  assert.match(sidebar, /document\.addEventListener\('pointerdown', handlePointerDown\)/u);
  assert.match(sidebar, /document\.removeEventListener\('pointerdown', handlePointerDown\)/u);
  assert.match(sidebar, /<WorkspaceDock\b/u);
  assert.match(sidebar, /\{resizeHandle\}/u);
  assert.match(resizeHandle, /window\.addEventListener\('pointermove', trackPointer\)/u);
  assert.match(resizeHandle, /window\.removeEventListener\('pointermove', trackPointer\)/u);

  assert.match(
    boundary,
    /role=\{loading \? 'status' : 'alert'\}[\s\S]*aria-live="polite"/u,
  );
  assert.doesNotMatch(boundary, /<DesktopSidebar\b|<WorkspaceDock\b|<ResizeHandle\b|fallback/u);
  assert.match(
    sidebarStyles,
    /\.desktop-design-sidebar\s*\{[\s\S]*?grid-column:\s*1;[\s\S]*?grid-row:\s*2;[\s\S]*?overflow:\s*hidden;[\s\S]*?border-right:[\s\S]*?background:/u,
  );
  assert.match(
    chromeStyles,
    /--desktop-sidebar-width:\s*var\(--desktop-sidebar-preferred-width, 220px\)/u,
  );
  assert.match(
    chromeStyles,
    /\.app-shell\.sidebar-collapsed\s*\{[\s\S]*?grid-template-columns:\s*44px/u,
  );
});
