import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const boundary = source('src/plugins/DesktopRendererSettingsWindowV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const noProjectQa = source('src/qa/NoProjectEntryQa.tsx');
const providerSettingsQa = source('src/qa/ProviderSettingsQa.tsx');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const surface = source('src/plugins/DesktopSettingsWindowSurfaceV2.tsx');
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

test('settings window is selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopSettingsWindowCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /if \(!input\.open\) return null/u);
  assert.match(boundary, /data-settings-window-state=\{composition\.status\}/u);
  assert.match(boundary, /data-reason-code=\{loading \? undefined : composition\.reasonCode\}/u);
  assert.ok(
    boundary.indexOf("composition.status === 'ready'") <
      boundary.indexOf('if (!input.open) return null'),
    'the ready SettingsWindow remains mounted while closed',
  );
  assert.doesNotMatch(
    boundary,
    /features\/settings\/SettingsWindow|fallback|use(?:Layout)?Effect|useState|useReducer|useMemo|acquireOperationLease|meta\.digest|\bkey=/u,
  );

  assert.match(surface, /export type DesktopSettingsWindowInputV2/u);
  assert.match(surface, /export interface DesktopSettingsWindowSurfacePropsV2/u);
  assert.match(surface, /<SettingsWindow \{\.\.\.input\}\s*\/>/u);
  assert.doesNotMatch(
    surface,
    /useDesktopRendererGenerationV2|acquireOperationLease|meta\.digest|generation(?:Digest|Version)|\bkey=|use(?:Layout)?Effect|useState|useReducer/u,
  );

  assert.match(shell, /DesktopRendererSettingsWindowV2/u);
  assert.match(shell, /settings:\s*DesktopSettingsWindowInputV2/u);
  assert.match(shell, /<DesktopRendererSettingsWindowV2 input=\{surfaces\.settings\}\s*\/>/u);
  assert.doesNotMatch(
    shell,
    /ComponentProps<typeof SettingsWindow>|<SettingsWindow\b|features\/settings\/SettingsWindow/u,
  );
  assert.doesNotMatch(app, /<SettingsWindow\b/u);
});

test('settings resolver validates the exact slot contract and fails closed', () => {
  assert.match(compositionPort, /DESKTOP_SETTINGS_WINDOW_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveSettingsWindowSurface/u);
  assert.match(compositionPort, /projectDesktopSettingsWindowCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_settings_window_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_settings_window_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_settings_window_module_unavailable/u);
  assert.match(composition, /import \{ DesktopSettingsWindowSurfaceV2 \}/u);
  assert.match(composition, /validSettingsWindowDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'settings_window_surface'/u);
  assert.match(composition, /definition\.id === 'settings-window'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-settings-window-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_SETTINGS_WINDOW_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.settings-window'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'settings_window_surface'/u);
  assert.match(sharedSlotTypes, /\| 'settings_window_surface'/u);
});

test('settings contribution is ordered after shell and before session canvas', () => {
  assert.match(
    artifactCatalog,
    /DESKTOP_SETTINGS_WINDOW_SURFACE_ARTIFACT_ID_V2\s*=\s*\n?\s*'desktop\.ui-slots\.settings-window-surface\.v1'/u,
  );
  assert.match(artifactCatalog, /slot:\s*'settings_window_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-settings-window-surface'/u);

  const shellIndex = profile.indexOf('entry_id: builtin-desktop-authenticated-shell-surface');
  const settingsIndex = profile.indexOf('entry_id: builtin-desktop-settings-window-surface');
  const sessionCanvasIndex = profile.indexOf('entry_id: builtin-desktop-session-canvas-surface');
  assert.ok(shellIndex >= 0);
  assert.ok(settingsIndex > shellIndex);
  assert.ok(sessionCanvasIndex > settingsIndex);
  const settingsEntry = profile.slice(settingsIndex, sessionCanvasIndex);
  assert.match(settingsEntry, /id:\s*desktop\.settings-window-surface/u);
  assert.match(settingsEntry, /order:\s*81/u);
  assert.match(settingsEntry, /desktop\.ui-slots\.settings-window-surface\.v1/u);

  const settingsBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-settings-window-surface',
  );
  assert.deepEqual(settingsBootstrap?.config, {
    id: 'desktop.settings-window-surface',
    kind: 'ui-slot',
    order: 81,
    payload: {
      artifact_refs: ['desktop.ui-slots.settings-window-surface.v1'],
      schema_version: 1,
    },
  });
});

test('settings projection rejects missing, duplicate, wrong, and inactive generations', () => {
  const {
    DESKTOP_SETTINGS_WINDOW_SURFACE_MODULE_REF_V2,
    projectDesktopSettingsWindowCompositionV2,
  } = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererCompositionPortV2.js');
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'settings_window_surface',
    id: 'settings-window',
    contract: 'ui-builtin:desktop-settings-window-surface',
    moduleRef: DESKTOP_SETTINGS_WINDOW_SURFACE_MODULE_REF_V2,
    permission: 'ui.settings-window',
    sandbox: true,
  });
  function SettingsWindowSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveSettingsWindowSurface: (definition) =>
      definition.moduleRef === DESKTOP_SETTINGS_WINDOW_SURFACE_MODULE_REF_V2
        ? SettingsWindowSurface
        : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  assert.deepEqual(
    projectDesktopSettingsWindowCompositionV2(authority('ready', [slot]), port),
    Object.freeze({ status: 'ready', Surface: SettingsWindowSurface }),
  );
  assert.deepEqual(
    projectDesktopSettingsWindowCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_settings_window_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_settings_window_contribution_ambiguous',
    ],
    [
      authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-settings-window' }]),
      'desktop_renderer_settings_window_module_unavailable',
    ],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopSettingsWindowCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopSettingsWindowCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ resolveSettingsWindowSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_settings_window_module_unavailable',
    }),
  );
});

test('direct SettingsWindow QA callers retain their isolated harnesses', () => {
  assert.match(noProjectQa, /<SettingsWindow\b/u);
  assert.match(providerSettingsQa, /<SettingsWindow\b/u);
});
