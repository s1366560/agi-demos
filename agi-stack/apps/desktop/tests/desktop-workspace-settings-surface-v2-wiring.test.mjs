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
const boundary = source('src/plugins/DesktopRendererWorkspaceSettingsV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const dialog = source('src/features/workspace/WorkspaceSettingsDialog.tsx');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const qa = source('src/qa/WorkspaceSettingsQa.tsx');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const surface = source('src/plugins/DesktopWorkspaceSettingsSurfaceV2.tsx');
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

test('workspace settings is selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopWorkspaceSettingsCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /if \(!input\.open\) return null/u);
  assert.match(boundary, /data-workspace-settings-state=\{composition\.status\}/u);
  assert.ok(
    boundary.indexOf("workspaceSettings.status === 'ready'") <
      boundary.indexOf('if (!input.open) return null'),
    'the ready workspace-settings surface remains mounted while closed',
  );
  assert.doesNotMatch(
    boundary,
    /features\/workspace\/WorkspaceSettingsDialog|fallback|acquireOperationLease|meta\.digest/u,
  );
  assert.doesNotMatch(boundary, /\bkey=|use(?:Layout)?Effect|useState|useReducer|useMemo/u);

  assert.match(surface, /export type DesktopWorkspaceSettingsInputV2/u);
  assert.match(surface, /export interface DesktopWorkspaceSettingsSurfacePropsV2/u);
  assert.match(surface, /<WorkspaceSettingsDialog \{\.\.\.input\}\s*\/>/u);
  assert.doesNotMatch(surface, /useDesktopRendererGenerationV2|acquireOperationLease/u);
  assert.doesNotMatch(surface, /AbortController|use(?:Layout)?Effect|useState|useReducer/u);

  assert.match(shell, /DesktopRendererWorkspaceSettingsV2/u);
  assert.match(shell, /workspaceSettings:\s*DesktopWorkspaceSettingsInputV2/u);
  assert.match(
    shell,
    /<DesktopRendererWorkspaceSettingsV2\s+input=\{surfaces\.workspaceSettings\}\s*\/>/u,
  );
  assert.doesNotMatch(shell, /<WorkspaceSettingsDialog\b/u);
  assert.doesNotMatch(shell, /features\/workspace\/WorkspaceSettingsDialog/u);
  assert.doesNotMatch(app, /<WorkspaceSettingsDialog\b/u);
});

test('workspace settings resolver validates the exact builtin same-realm slot contract', () => {
  assert.match(compositionPort, /DESKTOP_WORKSPACE_SETTINGS_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveWorkspaceSettingsSurface/u);
  assert.match(compositionPort, /projectDesktopWorkspaceSettingsCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_workspace_settings_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_workspace_settings_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_workspace_settings_module_unavailable/u);
  assert.match(composition, /import \{ DesktopWorkspaceSettingsSurfaceV2 \}/u);
  assert.match(composition, /validWorkspaceSettingsDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'workspace_settings_surface'/u);
  assert.match(composition, /definition\.id === 'workspace-settings'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-workspace-settings-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_WORKSPACE_SETTINGS_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.workspace-settings'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'workspace_settings_surface'/u);
  assert.match(sharedSlotTypes, /\| 'workspace_settings_surface'/u);
});

test('workspace settings contribution occupies the order 87 shell seam', () => {
  const artifactDeclaration = new RegExp(
    String.raw`DESKTOP_WORKSPACE_SETTINGS_SURFACE_ARTIFACT_ID_V2\s*=\s*\n?\s*` +
      String.raw`'desktop\.ui-slots\.workspace-settings-surface\.v1'`,
    'u',
  );
  assert.match(artifactCatalog, artifactDeclaration);
  assert.match(artifactCatalog, /slot:\s*'workspace_settings_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-workspace-settings-surface'/u);

  const workspaceCreateIndex = profile.indexOf('entry_id: builtin-desktop-workspace-create-surface');
  const workspaceSettingsIndex = profile.indexOf(
    'entry_id: builtin-desktop-workspace-settings-surface',
  );
  const workbenchIndex = profile.indexOf('entry_id: builtin-desktop-workbench-surface');
  assert.ok(workspaceCreateIndex >= 0);
  assert.ok(workspaceSettingsIndex > workspaceCreateIndex);
  assert.ok(workbenchIndex > workspaceSettingsIndex);
  const workspaceSettingsEntry = profile.slice(workspaceSettingsIndex, workbenchIndex);
  assert.match(workspaceSettingsEntry, /id:\s*desktop\.workspace-settings-surface/u);
  assert.match(workspaceSettingsEntry, /order:\s*87/u);
  assert.match(workspaceSettingsEntry, /desktop\.ui-slots\.workspace-settings-surface\.v1/u);

  const workspaceSettingsBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-workspace-settings-surface',
  );
  assert.deepEqual(workspaceSettingsBootstrap?.config, {
    id: 'desktop.workspace-settings-surface',
    kind: 'ui-slot',
    order: 87,
    payload: {
      artifact_refs: ['desktop.ui-slots.workspace-settings-surface.v1'],
      schema_version: 1,
    },
  });
});

test('workspace settings projection rejects malformed, duplicate, and inactive generations', () => {
  const {
    DESKTOP_WORKSPACE_SETTINGS_SURFACE_MODULE_REF_V2,
    projectDesktopWorkspaceSettingsCompositionV2,
  } = require(compiledPlugin('desktopRendererCompositionPortV2.js'));
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'workspace_settings_surface',
    id: 'workspace-settings',
    contract: 'ui-builtin:desktop-workspace-settings-surface',
    moduleRef: DESKTOP_WORKSPACE_SETTINGS_SURFACE_MODULE_REF_V2,
    permission: 'ui.workspace-settings',
    sandbox: true,
  });
  function WorkspaceSettingsSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveWorkspaceSettingsSurface: (definition) =>
      definition.moduleRef === DESKTOP_WORKSPACE_SETTINGS_SURFACE_MODULE_REF_V2
        ? WorkspaceSettingsSurface
        : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  const ready = projectDesktopWorkspaceSettingsCompositionV2(authority('ready', [slot]), port);
  assert.deepEqual(ready, Object.freeze({ status: 'ready', Surface: WorkspaceSettingsSurface }));
  const unrelated = projectDesktopWorkspaceSettingsCompositionV2(
    authority('ready', [slot, { ...slot, slot: 'settings_page', id: 'unrelated' }]),
    port,
  );
  assert.equal(unrelated.status, 'ready');
  assert.deepEqual(
    projectDesktopWorkspaceSettingsCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_workspace_settings_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_workspace_settings_contribution_ambiguous',
    ],
    [
      authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-workspace-settings' }]),
      'desktop_renderer_workspace_settings_module_unavailable',
    ],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopWorkspaceSettingsCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopWorkspaceSettingsCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ resolveWorkspaceSettingsSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_workspace_settings_module_unavailable',
    }),
  );
});

test('dialog retains draft, cancellation, scope, membership, bindings, and isolated QA ownership', () => {
  assert.match(dialog, /const requestRef = useRef<AbortController \| null>\(null\)/u);
  assert.match(dialog, /requestRef\.current\?\.abort\(\)/u);
  assert.match(dialog, /await onSave\(input, \{ \.\.\.scope \}, controller\.signal\)/u);
  assert.match(dialog, /<WorkspaceMembersPanel/u);
  assert.match(dialog, /<WorkspaceAgentBindingsPanel/u);
  assert.match(qa, /<WorkspaceSettingsDialog/u);

  const inputStart = app.indexOf('workspaceSettings: {');
  const inputEnd = app.indexOf('settings: {', inputStart);
  const input = app.slice(inputStart, inputEnd);
  assert.match(input, /open:\s*workspaceSettingsOpen/u);
  assert.match(input, /workspace:\s*selectedWorkspace/u);
  assert.match(input, /scope:\s*\{/u);
  assert.match(input, /onOpenChange:\s*setWorkspaceSettingsOpen/u);
  assert.match(input, /onSave:\s*updateWorkspaceFromDialog/u);
  assert.match(input, /onAddMember:\s*addWorkspaceMemberFromDialog/u);
  assert.match(input, /onBindAgent:\s*bindWorkspaceAgentFromDialog/u);
});
