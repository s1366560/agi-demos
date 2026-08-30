import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const boundary = source('src/plugins/DesktopRendererSessionWorkspaceV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const surface = source('src/plugins/DesktopSessionWorkspaceSurfaceV2.tsx');
const workbench = source('src/plugins/DesktopWorkbenchSurfaceV2.tsx');
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

test('session workspace is selected from one typed V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopSessionWorkspaceCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\} thread=\{thread\}\s*\/>/u);
  assert.match(boundary, /data-session-workspace-state=\{composition\.status\}/u);
  assert.match(boundary, /data-reason-code=\{loading \? undefined : composition\.reasonCode\}/u);
  assert.doesNotMatch(
    boundary,
    /features\/session\/SessionWorkspace|children|fallback|use(?:Layout)?Effect|useState|useReducer|useMemo/u,
  );

  assert.match(surface, /export type DesktopSessionWorkspaceInputV2/u);
  assert.match(surface, /export interface DesktopSessionWorkspaceSurfacePropsV2/u);
  assert.match(surface, /<SessionWorkspace \{\.\.\.input\} thread=\{thread\}\s*\/>/u);

  assert.match(workbench, /DesktopRendererSessionWorkspaceV2/u);
  assert.match(workbench, /DesktopSessionWorkspaceInputV2/u);
  assert.match(
    workbench,
    /<DesktopRendererSessionWorkspaceV2[\s\S]*input=\{viewModel\.session\}[\s\S]*thread=\{[\s\S]*<section className=\{viewModel\.paneStageClassName\}>\{view\}<\/section>[\s\S]*\}[\s\S]*\/>/u,
  );
  assert.doesNotMatch(
    workbench,
    /ComponentProps<typeof SessionWorkspace>|<SessionWorkspace\b|features\/session\/SessionWorkspace/u,
  );
  assert.doesNotMatch(app, /<SessionWorkspace\b/u);
});

test('session workspace resolver validates the exact slot contract and fails closed', () => {
  assert.match(compositionPort, /DESKTOP_SESSION_WORKSPACE_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveSessionWorkspaceSurface/u);
  assert.match(compositionPort, /projectDesktopSessionWorkspaceCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_session_workspace_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_session_workspace_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_session_workspace_module_unavailable/u);
  assert.match(composition, /import \{ DesktopSessionWorkspaceSurfaceV2 \}/u);
  assert.match(composition, /validSessionWorkspaceDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'session_workspace_surface'/u);
  assert.match(composition, /definition\.id === 'session-workspace'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-session-workspace-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_SESSION_WORKSPACE_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.session-workspace'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'session_workspace_surface'/u);
  assert.match(sharedSlotTypes, /\| 'session_workspace_surface'/u);
});

test('session workspace is ordered after workbench and before workspace collaboration', () => {
  assert.match(
    artifactCatalog,
    /DESKTOP_SESSION_WORKSPACE_SURFACE_ARTIFACT_ID_V2\s*=\s*'desktop\.ui-slots\.session-workspace-surface\.v1'/u,
  );
  assert.match(artifactCatalog, /slot:\s*'session_workspace_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-session-workspace-surface'/u);

  const workbenchIndex = profile.indexOf('entry_id: builtin-desktop-workbench-surface');
  const sessionWorkspaceIndex = profile.indexOf('entry_id: builtin-desktop-session-workspace-surface');
  const collaborationIndex = profile.indexOf(
    'entry_id: builtin-desktop-workspace-collaboration-surface',
  );
  assert.ok(workbenchIndex >= 0);
  assert.ok(sessionWorkspaceIndex > workbenchIndex);
  assert.ok(collaborationIndex > sessionWorkspaceIndex);
  const sessionWorkspaceEntry = profile.slice(sessionWorkspaceIndex, collaborationIndex);
  assert.match(sessionWorkspaceEntry, /id:\s*desktop\.session-workspace-surface/u);
  assert.match(sessionWorkspaceEntry, /order:\s*91/u);
  assert.match(sessionWorkspaceEntry, /desktop\.ui-slots\.session-workspace-surface\.v1/u);

  const sessionWorkspaceBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-session-workspace-surface',
  );
  assert.deepEqual(sessionWorkspaceBootstrap?.config, {
    id: 'desktop.session-workspace-surface',
    kind: 'ui-slot',
    order: 91,
    payload: {
      artifact_refs: ['desktop.ui-slots.session-workspace-surface.v1'],
      schema_version: 1,
    },
  });
});
