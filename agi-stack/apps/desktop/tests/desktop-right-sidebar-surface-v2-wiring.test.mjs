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
const boundary = source('src/plugins/DesktopRendererRightSidebarV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const rightSidebar = source('src/features/chrome/DesktopRightSidebar.tsx');
const rightSidebarStyles = source('src/features/chrome/DesktopRightSidebar.css');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const surface = source('src/plugins/DesktopRightSidebarSurfaceV2.tsx');
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

test('right sidebar is selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopRightSidebarCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /<aside\s+className="desktop-right-sidebar"/u);
  assert.match(boundary, /data-right-sidebar-state=\{composition\.status\}/u);
  assert.match(boundary, /data-reason-code=\{loading \? undefined : composition\.reasonCode\}/u);
  assert.match(boundary, /style=\{\{ width: 320 \}\}/u);
  assert.doesNotMatch(
    boundary,
    /features\/chrome\/DesktopRightSidebar|SessionContextRail|BrowserPanel|ResizeHandle|fallback|acquireOperationLease|meta\.digest|generation(?:Digest|Version)|\bkey=/u,
  );
  assert.doesNotMatch(boundary, /use(?:Layout)?Effect|useState|useReducer|useMemo|useRef/u);

  assert.match(surface, /export type DesktopRightSidebarInputV2/u);
  assert.match(surface, /ComponentProps<typeof DesktopRightSidebar>/u);
  assert.match(surface, /export interface DesktopRightSidebarSurfacePropsV2/u);
  assert.match(surface, /<DesktopRightSidebar \{\.\.\.input\}\s*\/>/u);
  assert.doesNotMatch(surface, /useDesktopRendererGenerationV2|acquireOperationLease/u);
  assert.doesNotMatch(surface, /\bkey=|use(?:Layout)?Effect|useState|useReducer|useMemo|useRef/u);

  assert.match(shell, /DesktopRendererRightSidebarV2/u);
  assert.match(
    shell,
    /rightSidebar:\s*DesktopAuthenticatedShellOptionalOutletV2<\s*DesktopRightSidebarInputV2\s*>/u,
  );
  assert.match(
    shell,
    /surfaces\.rightSidebar\.kind === 'visible'[\s\S]*<DesktopRendererRightSidebarV2\s+input=\{surfaces\.rightSidebar\.props\}/u,
  );
  assert.doesNotMatch(shell, /<DesktopRightSidebar\b/u);
  assert.doesNotMatch(shell, /features\/chrome\/DesktopRightSidebar/u);
  assert.doesNotMatch(app, /<DesktopRightSidebar\b/u);
});

test('right sidebar resolver validates the exact builtin same-realm slot contract', () => {
  assert.match(compositionPort, /DESKTOP_RIGHT_SIDEBAR_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveRightSidebarSurface/u);
  assert.match(compositionPort, /projectDesktopRightSidebarCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_right_sidebar_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_right_sidebar_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_right_sidebar_module_unavailable/u);
  assert.match(composition, /import \{ DesktopRightSidebarSurfaceV2 \}/u);
  assert.match(composition, /validRightSidebarDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'right_sidebar_surface'/u);
  assert.match(composition, /definition\.id === 'right-sidebar'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-right-sidebar-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_RIGHT_SIDEBAR_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.right-sidebar'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'right_sidebar_surface'/u);
  assert.match(sharedSlotTypes, /\| 'right_sidebar_surface'/u);
});

test('right sidebar contribution is declared after the left sidebar and before routes', () => {
  const artifactDeclaration = new RegExp(
    String.raw`DESKTOP_RIGHT_SIDEBAR_SURFACE_ARTIFACT_ID_V2\s*=\s*\n?\s*` +
      String.raw`'desktop\.ui-slots\.right-sidebar-surface\.v1'`,
    'u',
  );
  assert.match(artifactCatalog, artifactDeclaration);
  assert.match(artifactCatalog, /slot:\s*'right_sidebar_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-right-sidebar-surface'/u);

  const sidebarIndex = profile.indexOf('entry_id: builtin-desktop-sidebar-surface');
  const rightSidebarIndex = profile.indexOf('entry_id: builtin-desktop-right-sidebar-surface');
  const routesIndex = profile.indexOf('entry_id: builtin-desktop-tenant-creation-routes');
  assert.ok(sidebarIndex >= 0);
  assert.ok(rightSidebarIndex > sidebarIndex);
  assert.ok(routesIndex > rightSidebarIndex);
  const rightSidebarEntry = profile.slice(rightSidebarIndex, routesIndex);
  assert.match(rightSidebarEntry, /id:\s*desktop\.right-sidebar-surface/u);
  assert.match(rightSidebarEntry, /order:\s*100/u);
  assert.match(rightSidebarEntry, /desktop\.ui-slots\.right-sidebar-surface\.v1/u);

  const rightSidebarBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-right-sidebar-surface',
  );
  assert.deepEqual(rightSidebarBootstrap?.config, {
    id: 'desktop.right-sidebar-surface',
    kind: 'ui-slot',
    order: 100,
    payload: {
      artifact_refs: ['desktop.ui-slots.right-sidebar-surface.v1'],
      schema_version: 1,
    },
  });
});

test('right sidebar projection rejects malformed, duplicate, and inactive generations', () => {
  const {
    DESKTOP_RIGHT_SIDEBAR_SURFACE_MODULE_REF_V2,
    projectDesktopRightSidebarCompositionV2,
  } = require(compiledPlugin('desktopRendererCompositionPortV2.js'));
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'right_sidebar_surface',
    id: 'right-sidebar',
    contract: 'ui-builtin:desktop-right-sidebar-surface',
    moduleRef: DESKTOP_RIGHT_SIDEBAR_SURFACE_MODULE_REF_V2,
    permission: 'ui.right-sidebar',
    sandbox: true,
  });
  function RightSidebarSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveRightSidebarSurface: (definition) =>
      definition.moduleRef === DESKTOP_RIGHT_SIDEBAR_SURFACE_MODULE_REF_V2
        ? RightSidebarSurface
        : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  const ready = projectDesktopRightSidebarCompositionV2(authority('ready', [slot]), port);
  assert.deepEqual(ready, Object.freeze({ status: 'ready', Surface: RightSidebarSurface }));
  const unrelated = projectDesktopRightSidebarCompositionV2(
    authority('ready', [slot, { ...slot, slot: 'workbench_surface', id: 'unrelated' }]),
    port,
  );
  assert.equal(unrelated.status, 'ready');
  assert.equal(unrelated.Surface, ready.Surface);
  assert.deepEqual(
    projectDesktopRightSidebarCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_right_sidebar_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_right_sidebar_contribution_ambiguous',
    ],
    [
      authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-right-sidebar' }]),
      'desktop_renderer_right_sidebar_module_unavailable',
    ],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopRightSidebarCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopRightSidebarCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ resolveRightSidebarSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_right_sidebar_module_unavailable',
    }),
  );
});

test('right sidebar seam preserves shell state, local lifecycles, and failure layout', () => {
  assert.match(app, /localStorage\.getItem\('agistack\.desktop\.rightSidebarOpen'\) === 'true'/u);
  assert.match(app, /const \[activeRightPanel, setActiveRightPanel\]/u);
  assert.match(app, /rightSidebarAvailable && rightSidebarOpen/u);
  assert.match(app, /activePanel:\s*activeRightPanel/u);
  assert.match(app, /onSelectPanel:\s*handleSelectRightPanel/u);
  assert.match(app, /onCloseCanvas:\s*handleCloseCanvas/u);

  assert.match(rightSidebar, /useResizablePanelWidth\(/u);
  assert.match(rightSidebar, /agistack\.desktop\.rightSidebarWidth/u);
  assert.match(rightSidebar, /useState<'split' \| 'focus'>\('split'\)/u);
  assert.match(rightSidebar, /useRef<string \| null>\(null\)/u);
  assert.match(rightSidebar, /document\.activeElement\.dataset\.sessionCanvasTrigger/u);
  assert.match(rightSidebar, /window\.requestAnimationFrame/u);
  assert.match(rightSidebar, /<DesktopRendererSessionCanvasV2/u);
  assert.match(rightSidebar, /<SessionContextRail/u);
  assert.match(rightSidebar, /<BrowserPanel/u);
  assert.match(rightSidebar, /canvas\.kind === 'available'/u);

  assert.match(
    boundary,
    /role=\{loading \? 'status' : 'alert'\}[\s\S]*aria-live="polite"/u,
  );
  assert.doesNotMatch(
    boundary,
    /<DesktopRightSidebar\b|<SessionContextRail\b|<BrowserPanel\b|<ResizeHandle\b|fallback/u,
  );
  assert.match(
    rightSidebarStyles,
    /\.desktop-right-sidebar\s*\{[\s\S]*?grid-column:\s*3;[\s\S]*?grid-row:\s*2;[\s\S]*?overflow:\s*hidden;[\s\S]*?border-left:[\s\S]*?background:/u,
  );
});
