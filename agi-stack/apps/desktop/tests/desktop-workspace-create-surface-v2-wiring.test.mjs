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
const boundary = source('src/plugins/DesktopRendererWorkspaceCreateV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const dialog = source('src/features/workspace/WorkspaceCreateDialog.tsx');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const qa = source('src/qa/WorkspaceCreateQa.tsx');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const surface = source('src/plugins/DesktopWorkspaceCreateSurfaceV2.tsx');
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

test('workspace create is selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopWorkspaceCreateCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /if \(!input\.open\) return null/u);
  assert.match(boundary, /data-workspace-create-state=\{composition\.status\}/u);
  assert.ok(
    boundary.indexOf("workspaceCreate.status === 'ready'") <
      boundary.indexOf('if (!input.open) return null'),
    'the ready workspace-create surface remains mounted while closed',
  );
  assert.doesNotMatch(
    boundary,
    /features\/workspace\/WorkspaceCreateDialog|fallback|acquireOperationLease|meta\.digest/u,
  );
  assert.doesNotMatch(boundary, /\bkey=|use(?:Layout)?Effect|useState|useReducer|useMemo/u);

  assert.match(surface, /export type DesktopWorkspaceCreateInputV2/u);
  assert.match(surface, /export interface DesktopWorkspaceCreateSurfacePropsV2/u);
  assert.match(surface, /<WorkspaceCreateDialog \{\.\.\.input\}\s*\/>/u);
  assert.doesNotMatch(surface, /useDesktopRendererGenerationV2|acquireOperationLease/u);
  assert.doesNotMatch(surface, /AbortController|use(?:Layout)?Effect|useState|useReducer/u);

  assert.match(shell, /DesktopRendererWorkspaceCreateV2/u);
  assert.match(shell, /workspaceCreate:\s*DesktopWorkspaceCreateInputV2/u);
  assert.match(
    shell,
    /<DesktopRendererWorkspaceCreateV2 input=\{surfaces\.workspaceCreate\}\s*\/>/u,
  );
  assert.doesNotMatch(shell, /<WorkspaceCreateDialog\b/u);
  assert.doesNotMatch(shell, /features\/workspace\/WorkspaceCreateDialog/u);
  assert.doesNotMatch(app, /<WorkspaceCreateDialog\b/u);
});

test('workspace create resolver validates the exact builtin same-realm slot contract', () => {
  assert.match(compositionPort, /DESKTOP_WORKSPACE_CREATE_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveWorkspaceCreateSurface/u);
  assert.match(compositionPort, /projectDesktopWorkspaceCreateCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_workspace_create_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_workspace_create_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_workspace_create_module_unavailable/u);
  assert.match(composition, /import \{ DesktopWorkspaceCreateSurfaceV2 \}/u);
  assert.match(composition, /validWorkspaceCreateDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'workspace_create_surface'/u);
  assert.match(composition, /definition\.id === 'workspace-create'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-workspace-create-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_WORKSPACE_CREATE_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.workspace-create'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'workspace_create_surface'/u);
  assert.match(sharedSlotTypes, /\| 'workspace_create_surface'/u);
});

test('workspace create contribution occupies the order 86 shell seam', () => {
  const artifactDeclaration = new RegExp(
    String.raw`DESKTOP_WORKSPACE_CREATE_SURFACE_ARTIFACT_ID_V2\s*=\s*\n?\s*` +
      String.raw`'desktop\.ui-slots\.workspace-create-surface\.v1'`,
    'u',
  );
  assert.match(artifactCatalog, artifactDeclaration);
  assert.match(artifactCatalog, /slot:\s*'workspace_create_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-workspace-create-surface'/u);

  const sessionCanvasIndex = profile.indexOf('entry_id: builtin-desktop-session-canvas-surface');
  const workspaceCreateIndex = profile.indexOf(
    'entry_id: builtin-desktop-workspace-create-surface',
  );
  const workbenchIndex = profile.indexOf('entry_id: builtin-desktop-workbench-surface');
  assert.ok(sessionCanvasIndex >= 0);
  assert.ok(workspaceCreateIndex > sessionCanvasIndex);
  assert.ok(workbenchIndex > workspaceCreateIndex);
  const workspaceCreateEntry = profile.slice(workspaceCreateIndex, workbenchIndex);
  assert.match(workspaceCreateEntry, /id:\s*desktop\.workspace-create-surface/u);
  assert.match(workspaceCreateEntry, /order:\s*86/u);
  assert.match(workspaceCreateEntry, /desktop\.ui-slots\.workspace-create-surface\.v1/u);

  const workspaceCreateBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-create-surface',
  );
  assert.deepEqual(workspaceCreateBootstrap?.config, {
    id: 'desktop.workspace-create-surface',
    kind: 'ui-slot',
    order: 86,
    payload: {
      artifact_refs: ['desktop.ui-slots.workspace-create-surface.v1'],
      schema_version: 1,
    },
  });
});

test('workspace create projection rejects malformed, duplicate, and inactive generations', () => {
  const {
    DESKTOP_WORKSPACE_CREATE_SURFACE_MODULE_REF_V2,
    projectDesktopWorkspaceCreateCompositionV2,
  } = require(compiledPlugin('desktopRendererCompositionPortV2.js'));
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'workspace_create_surface',
    id: 'workspace-create',
    contract: 'ui-builtin:desktop-workspace-create-surface',
    moduleRef: DESKTOP_WORKSPACE_CREATE_SURFACE_MODULE_REF_V2,
    permission: 'ui.workspace-create',
    sandbox: true,
  });
  function WorkspaceCreateSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveWorkspaceCreateSurface: (definition) =>
      definition.moduleRef === DESKTOP_WORKSPACE_CREATE_SURFACE_MODULE_REF_V2
        ? WorkspaceCreateSurface
        : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  const ready = projectDesktopWorkspaceCreateCompositionV2(authority('ready', [slot]), port);
  assert.deepEqual(ready, Object.freeze({ status: 'ready', Surface: WorkspaceCreateSurface }));
  const unrelated = projectDesktopWorkspaceCreateCompositionV2(
    authority('ready', [slot, { ...slot, slot: 'settings_page', id: 'unrelated' }]),
    port,
  );
  assert.equal(unrelated.status, 'ready');
  assert.deepEqual(
    projectDesktopWorkspaceCreateCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_workspace_create_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_workspace_create_contribution_ambiguous',
    ],
    [
      authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-workspace-create' }]),
      'desktop_renderer_workspace_create_module_unavailable',
    ],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopWorkspaceCreateCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopWorkspaceCreateCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ resolveWorkspaceCreateSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_workspace_create_module_unavailable',
    }),
  );
});

test('dialog retains draft, cancellation, scope, and isolated QA ownership', () => {
  assert.match(dialog, /const requestRef = useRef<AbortController \| null>\(null\)/u);
  assert.match(dialog, /requestRef\.current\?\.abort\(\)/u);
  assert.match(dialog, /\[open, scope\.projectId, scope\.tenantId\]/u);
  assert.match(dialog, /await onCreate\(input, \{ \.\.\.scope \}, controller\.signal\)/u);
  assert.match(dialog, /workspaceCreateDraftIsDirty\(draft\)/u);
  assert.match(qa, /<WorkspaceCreateDialog/u);

  const inputStart = app.indexOf('workspaceCreate: {');
  const inputEnd = app.indexOf('workspaceSettings:', inputStart);
  const input = app.slice(inputStart, inputEnd);
  assert.match(input, /open:\s*workspaceCreateOpen/u);
  assert.match(input, /scope:\s*\{/u);
  assert.match(input, /onOpenChange:\s*setWorkspaceCreateOpen/u);
  assert.match(input, /onCreate:\s*createWorkspaceFromDialog/u);
});
