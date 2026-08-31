import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const boundary = source('src/plugins/DesktopRendererWorkspaceCollaborationV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const surface = source('src/plugins/DesktopWorkspaceCollaborationSurfaceV2.tsx');
const workbench = source('src/plugins/DesktopWorkbenchSurfaceV2.tsx');
const clientProvider = source(
  'src/features/workspace/workspaceCollaborationClientProviderV2.ts',
);
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

test('workspace collaboration is selected from one typed V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopWorkspaceCollaborationCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /data-workspace-collaboration-state=\{composition\.status\}/u);
  assert.match(boundary, /data-reason-code=\{loading \? undefined : composition\.reasonCode\}/u);
  assert.doesNotMatch(
    boundary,
    /features\/workspace\/WorkspaceCollaborationCanvas|ReactNode|children|fallback|use(?:Layout)?Effect|useState|useReducer|useMemo/u,
  );

  assert.match(surface, /export type DesktopWorkspaceCollaborationInputV2/u);
  assert.match(surface, /export interface DesktopWorkspaceCollaborationSurfacePropsV2/u);
  assert.match(surface, /<WorkspaceCollaborationCanvas \{\.\.\.input\} \/>/u);

  assert.match(workbench, /DesktopRendererWorkspaceCollaborationV2/u);
  assert.match(workbench, /collaboration:\s*DesktopWorkspaceCollaborationInputV2 \| null/u);
  assert.match(
    workbench,
    /<DesktopRendererWorkspaceCollaborationV2 input=\{view\.collaboration\}\s*\/>/u,
  );
  assert.doesNotMatch(
    workbench,
    /ComponentProps<typeof WorkspaceCollaborationCanvas>|<WorkspaceCollaborationCanvas\b|features\/workspace\/WorkspaceCollaborationCanvas/u,
  );

  assert.match(app, /workspaceCollaborationClientProviderV2\.publish\(\{/u);
  assert.match(
    app,
    /capabilitySnapshot:\s*desktopCapabilityState\.snapshot/u,
  );
  assert.match(app, /workspaceId:\s*config\.workspaceId/u);
  assert.match(app, /client:\s*workspaceCollaborationClientV2\.client/u);
  assert.match(
    app,
    /authorityInvalidation:\s*workspaceCollaborationAuthorityInvalidation/u,
  );
  assert.doesNotMatch(app, /desktopCapability\(/u);
  assert.doesNotMatch(app, /createHttpWorkspaceCollaborationClient\(/u);
  assert.doesNotMatch(app, /createCapabilityWorkspaceCollaborationClient\(/u);
  assert.match(
    clientProvider,
    /desktopCapability\(input\.capabilitySnapshot, 'workspace_collaboration'\)/u,
  );
  assert.match(clientProvider, /createHttpWorkspaceCollaborationClient\(config\)/u);
  assert.match(clientProvider, /createCapabilityWorkspaceCollaborationClient\(/u);
  assert.doesNotMatch(app, /<WorkspaceCollaborationCanvas\b/u);
});

test('workspace collaboration resolver validates the exact slot contract and fails closed', () => {
  assert.match(compositionPort, /DESKTOP_WORKSPACE_COLLABORATION_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveWorkspaceCollaborationSurface/u);
  assert.match(compositionPort, /projectDesktopWorkspaceCollaborationCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_workspace_collaboration_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_workspace_collaboration_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_workspace_collaboration_module_unavailable/u);
  assert.match(composition, /import \{ DesktopWorkspaceCollaborationSurfaceV2 \}/u);
  assert.match(composition, /validWorkspaceCollaborationDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'workspace_collaboration_surface'/u);
  assert.match(composition, /definition\.id === 'workspace-collaboration'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-workspace-collaboration-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_WORKSPACE_COLLABORATION_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.workspace-collaboration'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'workspace_collaboration_surface'/u);
  assert.match(sharedSlotTypes, /\| 'workspace_collaboration_surface'/u);
});

test('workspace collaboration is ordered after workbench and before new-thread composer', () => {
  assert.match(
    artifactCatalog,
    /DESKTOP_WORKSPACE_COLLABORATION_SURFACE_ARTIFACT_ID_V2\s*=\s*'desktop\.ui-slots\.workspace-collaboration-surface\.v1'/u,
  );
  assert.match(artifactCatalog, /slot:\s*'workspace_collaboration_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-workspace-collaboration-surface'/u);

  const workbenchIndex = profile.indexOf('entry_id: builtin-desktop-workbench-surface');
  const collaborationIndex = profile.indexOf(
    'entry_id: builtin-desktop-workspace-collaboration-surface',
  );
  const composerIndex = profile.indexOf('entry_id: builtin-desktop-new-thread-composer-surface');
  assert.ok(workbenchIndex >= 0);
  assert.ok(collaborationIndex > workbenchIndex);
  assert.ok(composerIndex > collaborationIndex);
  const collaborationEntry = profile.slice(collaborationIndex, composerIndex);
  assert.match(collaborationEntry, /id:\s*desktop\.workspace-collaboration-surface/u);
  assert.match(collaborationEntry, /order:\s*92/u);
  assert.match(collaborationEntry, /desktop\.ui-slots\.workspace-collaboration-surface\.v1/u);

  const collaborationBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-collaboration-surface',
  );
  assert.deepEqual(collaborationBootstrap?.config, {
    id: 'desktop.workspace-collaboration-surface',
    kind: 'ui-slot',
    order: 92,
    payload: {
      artifact_refs: ['desktop.ui-slots.workspace-collaboration-surface.v1'],
      schema_version: 1,
    },
  });
});
