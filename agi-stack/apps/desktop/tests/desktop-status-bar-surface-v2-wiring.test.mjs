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
const boundary = source('src/plugins/DesktopRendererStatusBarV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const statusBar = source('src/features/chrome/DesktopStatusBar.tsx');
const surface = source('src/plugins/DesktopStatusBarSurfaceV2.tsx');
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

test('status bar is selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopStatusBarCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /<footer\s+className="desktop-status-bar"/u);
  assert.match(boundary, /data-status-bar-state=\{composition\.status\}/u);
  assert.match(boundary, /data-reason-code=\{loading \? undefined : composition\.reasonCode\}/u);
  assert.doesNotMatch(
    boundary,
    /features\/chrome\/DesktopStatusBar|fallback|acquireOperationLease|meta\.digest|\bkey=/u,
  );
  assert.doesNotMatch(boundary, /use(?:Layout)?Effect|useState|useReducer|useMemo/u);

  assert.match(surface, /export type DesktopStatusBarInputV2/u);
  assert.match(surface, /export interface DesktopStatusBarSurfacePropsV2/u);
  assert.match(surface, /<DesktopStatusBar \{\.\.\.input\}\s*\/>/u);
  assert.doesNotMatch(
    surface,
    /useDesktopRendererGenerationV2|acquireOperationLease|meta\.digest/u,
  );
  assert.doesNotMatch(surface, /generation(?:Digest|Version)/u);
  assert.doesNotMatch(surface, /\bkey=|use(?:Layout)?Effect|useState|useReducer/u);
  assert.doesNotMatch(surface, /ReactNode|children/u);

  assert.match(shell, /DesktopRendererStatusBarV2/u);
  assert.match(shell, /statusBar:\s*DesktopStatusBarInputV2/u);
  assert.match(shell, /<DesktopRendererStatusBarV2 input=\{surfaces\.statusBar\}\s*\/>/u);
  assert.doesNotMatch(shell, /ComponentProps<typeof DesktopStatusBar>|<DesktopStatusBar\b/u);
  assert.doesNotMatch(shell, /features\/chrome\/DesktopStatusBar/u);
  assert.doesNotMatch(app, /<DesktopStatusBar\b/u);
});

test('status bar resolver validates the exact builtin same-realm slot contract', () => {
  assert.match(compositionPort, /DESKTOP_STATUS_BAR_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveStatusBarSurface/u);
  assert.match(compositionPort, /projectDesktopStatusBarCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_status_bar_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_status_bar_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_status_bar_module_unavailable/u);
  assert.match(composition, /import \{ DesktopStatusBarSurfaceV2 \}/u);
  assert.match(composition, /validStatusBarDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'status_bar_surface'/u);
  assert.match(composition, /definition\.id === 'status-bar'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-status-bar-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_STATUS_BAR_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.status-bar'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'status_bar_surface'/u);
  assert.match(sharedSlotTypes, /\| 'status_bar_surface'/u);
});

test('status bar contribution is ordered after shortcuts and before session canvas', () => {
  const artifactDeclaration = new RegExp(
    String.raw`DESKTOP_STATUS_BAR_SURFACE_ARTIFACT_ID_V2\s*=\s*\n?\s*` +
      String.raw`'desktop\.ui-slots\.status-bar-surface\.v1'`,
    'u',
  );
  assert.match(artifactCatalog, artifactDeclaration);
  assert.match(artifactCatalog, /slot:\s*'status_bar_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-status-bar-surface'/u);

  const shortcutsIndex = profile.indexOf('entry_id: builtin-desktop-keyboard-shortcuts-surface');
  const statusBarIndex = profile.indexOf('entry_id: builtin-desktop-status-bar-surface');
  const sessionCanvasIndex = profile.indexOf('entry_id: builtin-desktop-session-canvas-surface');
  assert.ok(shortcutsIndex >= 0);
  assert.ok(statusBarIndex > shortcutsIndex);
  assert.ok(sessionCanvasIndex > statusBarIndex);
  const statusBarEntry = profile.slice(statusBarIndex, sessionCanvasIndex);
  assert.match(statusBarEntry, /id:\s*desktop\.status-bar-surface/u);
  assert.match(statusBarEntry, /order:\s*83/u);
  assert.match(statusBarEntry, /desktop\.ui-slots\.status-bar-surface\.v1/u);

  const statusBarBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-status-bar-surface',
  );
  assert.deepEqual(statusBarBootstrap?.config, {
    id: 'desktop.status-bar-surface',
    kind: 'ui-slot',
    order: 83,
    payload: {
      artifact_refs: ['desktop.ui-slots.status-bar-surface.v1'],
      schema_version: 1,
    },
  });
});

test('status bar projection rejects malformed, duplicate, and inactive generations', () => {
  const {
    DESKTOP_STATUS_BAR_SURFACE_MODULE_REF_V2,
    projectDesktopStatusBarCompositionV2,
  } = require(compiledPlugin('desktopRendererCompositionPortV2.js'));
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'status_bar_surface',
    id: 'status-bar',
    contract: 'ui-builtin:desktop-status-bar-surface',
    moduleRef: DESKTOP_STATUS_BAR_SURFACE_MODULE_REF_V2,
    permission: 'ui.status-bar',
    sandbox: true,
  });
  function StatusBarSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveStatusBarSurface: (definition) =>
      definition.moduleRef === DESKTOP_STATUS_BAR_SURFACE_MODULE_REF_V2
        ? StatusBarSurface
        : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  const ready = projectDesktopStatusBarCompositionV2(authority('ready', [slot]), port);
  assert.deepEqual(ready, Object.freeze({ status: 'ready', Surface: StatusBarSurface }));
  const unrelatedReplacement = projectDesktopStatusBarCompositionV2(
    authority('ready', [slot, { ...slot, slot: 'settings_page', id: 'unrelated' }]),
    port,
  );
  assert.equal(unrelatedReplacement.status, 'ready');
  assert.equal(unrelatedReplacement.Surface, ready.Surface);
  assert.deepEqual(
    projectDesktopStatusBarCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_status_bar_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_status_bar_contribution_ambiguous',
    ],
    [authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-status-bar' }]),
      'desktop_renderer_status_bar_module_unavailable'],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopStatusBarCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopStatusBarCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ ...port, resolveStatusBarSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_status_bar_module_unavailable',
    }),
  );
});

test('status bar input and failure boundary preserve the production footer contract', () => {
  assert.match(statusBar, /title=\{liveError \?\? undefined\}/u);
  assert.match(statusBar, /\{tenantName\} · \{projectName\}/u);
  assert.match(statusBar, /liveError \? 'error' : liveConnected \? 'ready' : 'idle'/u);
  assert.match(boundary, /<footer\s+className="desktop-status-bar"/u);
  assert.doesNotMatch(boundary, /<DesktopStatusBar\b|fallback/u);
  const statusBarInput = new RegExp(
    [
      String.raw`statusBar:\s*\{\s*connection,`,
      String.raw`\s*liveConnected:\s*socket\.connected,`,
      String.raw`\s*liveError:\s*socket\.error,`,
      String.raw`\s*tenantName:\s*activeTenantName,`,
      String.raw`\s*projectName:\s*activeProjectName,\s*\}`,
    ].join(''),
    'u',
  );
  assert.match(app, statusBarInput);
});
