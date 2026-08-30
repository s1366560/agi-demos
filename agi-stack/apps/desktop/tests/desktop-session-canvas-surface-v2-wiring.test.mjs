import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const boundary = source('src/plugins/DesktopRendererSessionCanvasV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const rightSidebar = source('src/features/chrome/DesktopRightSidebar.tsx');
const surface = source('src/plugins/DesktopSessionCanvasSurfaceV2.tsx');
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

test('session canvas is selected from one typed V2 surface without a React callback seam', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopSessionCanvasCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\} controls=\{controls\}\s*\/>/u);
  assert.doesNotMatch(boundary, /ReactNode|children|renderCanvas/u);

  assert.match(surface, /export interface DesktopSessionCanvasInputV2/u);
  assert.match(surface, /readonly state:/u);
  assert.match(surface, /readonly actions:/u);
  assert.match(surface, /readonly meta:/u);
  assert.match(surface, /<WorkspaceReviewPanel/u);
  assert.match(surface, /sessionControls=\{controls\}/u);

  assert.match(rightSidebar, /DesktopRendererSessionCanvasV2/u);
  assert.match(rightSidebar, /canvas\.kind === 'available'/u);
  assert.doesNotMatch(rightSidebar, /ReactNode|renderCanvas/u);
  assert.doesNotMatch(
    app,
    /\bWorkspaceReviewPanel\b|SessionCanvasControls|renderWorkspaceReviewPanel|renderCanvas/u,
  );
});

test('session canvas resolver validates the exact slot contract and fails closed in the boundary', () => {
  assert.match(compositionPort, /DESKTOP_SESSION_CANVAS_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveSessionCanvasSurface/u);
  assert.match(compositionPort, /projectDesktopSessionCanvasCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_session_canvas_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_session_canvas_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_session_canvas_module_unavailable/u);
  assert.match(composition, /import \{ DesktopSessionCanvasSurfaceV2 \}/u);
  assert.match(composition, /validSessionCanvasDefinitionV2/u);
  assert.match(composition, /slot === 'session_canvas_surface'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-session-canvas-surface'/u);
  assert.match(composition, /permission === 'ui\.session-canvas'/u);
});

test('session canvas is an ordered production artifact between shell and workbench', () => {
  assert.match(
    artifactCatalog,
    /DESKTOP_SESSION_CANVAS_SURFACE_ARTIFACT_ID_V2\s*=\s*'desktop\.ui-slots\.session-canvas-surface\.v1'/u,
  );
  assert.match(artifactCatalog, /slot:\s*'session_canvas_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-session-canvas-surface'/u);

  const shellIndex = profile.indexOf('entry_id: builtin-desktop-authenticated-shell-surface');
  const canvasIndex = profile.indexOf('entry_id: builtin-desktop-session-canvas-surface');
  const workbenchIndex = profile.indexOf('entry_id: builtin-desktop-workbench-surface');
  assert.ok(shellIndex >= 0);
  assert.ok(canvasIndex > shellIndex);
  assert.ok(workbenchIndex > canvasIndex);
  const canvasEntry = profile.slice(canvasIndex, workbenchIndex);
  assert.match(canvasEntry, /id:\s*desktop\.session-canvas-surface/u);
  assert.match(canvasEntry, /order:\s*85/u);
  assert.match(canvasEntry, /desktop\.ui-slots\.session-canvas-surface\.v1/u);

  const canvasBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-canvas-surface',
  );
  assert.deepEqual(canvasBootstrap.config, {
    id: 'desktop.session-canvas-surface',
    kind: 'ui-slot',
    order: 85,
    payload: {
      artifact_refs: ['desktop.ui-slots.session-canvas-surface.v1'],
      schema_version: 1,
    },
  });
});
