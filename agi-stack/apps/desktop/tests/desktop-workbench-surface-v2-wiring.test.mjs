import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const authenticationRouter = source('src/plugins/DesktopRendererAuthenticationRouterV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const productionRouter = source('src/plugins/DesktopRendererProductionRouterV2.tsx');
const surface = source('src/plugins/DesktopWorkbenchSurfaceV2.tsx');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const profile = readFileSync(
  new URL(
    '../../../../config/plugin-profiles/memstack-production-target-hosts.v2.yaml',
    import.meta.url,
  ),
  'utf8',
);

test('the production workbench boundary accepts only a typed view model', () => {
  assert.match(productionRouter, /readonly viewModel:\s*DesktopWorkbenchSurfaceViewModelV2/u);
  assert.match(productionRouter, /<Surface viewModel=\{viewModel\}\s*\/>/u);
  assert.doesNotMatch(productionRouter, /childrenAuthority|ReactNode|readonly children/u);
  assert.match(compositionPort, /readonly viewModel:\s*DesktopWorkbenchSurfaceViewModelV2/u);
  assert.doesNotMatch(
    compositionPort.match(
      /export interface DesktopRendererWorkbenchSurfacePropsV2[\s\S]*?\n\}/u,
    )?.[0] ?? '',
    /ReactNode|render[A-Z]|children/u,
  );
});

test('authentication keeps its React child seam outside the business workbench router', () => {
  assert.match(authenticationRouter, /export function DesktopRendererAuthenticationRouterV2/u);
  assert.match(authenticationRouter, /readonly children:\s*ReactNode/u);
  assert.doesNotMatch(authenticationRouter, /projectDesktopWorkbenchCompositionV2|viewModel/u);
  assert.match(
    app,
    /<DesktopRendererAuthenticationRouterV2[\s\S]*<LoginScreen[\s\S]*<\/DesktopRendererAuthenticationRouterV2>/u,
  );
  assert.doesNotMatch(app, /childrenAuthority/u);
});

test('the V2 module owns every workbench business surface and App passes data only', () => {
  assert.match(composition, /import \{ DesktopWorkbenchSurfaceV2 \}/u);
  assert.match(
    composition,
    /validWorkbenchDefinitionV2\(definition\) \? DesktopWorkbenchSurfaceV2/u,
  );
  for (const component of [
    'ChatPanel',
    'WorkspaceOverview',
    'WorkspaceCollaborationCanvas',
    'MyWorkQueue',
    'ActivityInbox',
    'NewThreadComposer',
    'SessionWorkspace',
  ]) {
    assert.match(surface, new RegExp(`<${component}\\b`, 'u'));
    assert.doesNotMatch(app, new RegExp(`<${component}\\b`, 'u'));
  }
  assert.match(surface, /type DesktopWorkbenchViewV2\s*=/u);
  assert.match(surface, /kind:\s*'workspace'/u);
  assert.match(surface, /kind:\s*'chat'/u);
  assert.match(surface, /kind:\s*'board'/u);
  assert.match(surface, /kind:\s*'activity'/u);
  assert.match(surface, /kind:\s*'home'/u);
  assert.doesNotMatch(surface, /viewModel[^;{]*ReactNode|render[A-Z][A-Za-z]+\??:/u);
  assert.match(app, /viewModel=\{desktopWorkbenchSurfaceViewModelV2\}/u);
  assert.doesNotMatch(
    app,
    /<DesktopRendererProductionRouterV2[\s\S]*?<\/DesktopRendererProductionRouterV2>/u,
  );
});

test('the workbench artifact revision identifies the de-passthrough contract', () => {
  assert.match(
    artifactCatalog,
    /DESKTOP_WORKBENCH_SURFACE_ARTIFACT_ID_V2\s*=\s*'desktop\.ui-slots\.workbench-surface\.v2'/u,
  );
  const workbenchEntry = profile.slice(
    profile.indexOf('entry_id: builtin-desktop-workbench-surface'),
  );
  assert.match(workbenchEntry, /desktop\.ui-slots\.workbench-surface\.v2/u);
  assert.doesNotMatch(workbenchEntry.split('\n    - entry_id:', 1)[0], /workbench-surface\.v1/u);
});
