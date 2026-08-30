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
const boundary = source('src/plugins/DesktopRendererKeyboardShortcutsV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const dialog = source('src/features/navigation/KeyboardShortcutsDialog.tsx');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const surface = source('src/plugins/DesktopKeyboardShortcutsSurfaceV2.tsx');
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

test('keyboard shortcuts are selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopKeyboardShortcutsCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /if \(!input\.open\) return null/u);
  assert.match(boundary, /data-keyboard-shortcuts-state=\{composition\.status\}/u);
  assert.match(boundary, /data-reason-code=\{loading \? undefined : composition\.reasonCode\}/u);
  assert.ok(
    boundary.indexOf("composition.status === 'ready'") <
      boundary.indexOf('if (!input.open) return null'),
    'the ready shortcuts surface remains mounted while closed',
  );
  assert.doesNotMatch(
    boundary,
    /features\/navigation\/KeyboardShortcutsDialog|fallback|use(?:Layout)?Effect|useState|useReducer|useMemo|acquireOperationLease|meta\.digest|\bkey=/u,
  );

  assert.match(surface, /export type DesktopKeyboardShortcutsInputV2/u);
  assert.match(surface, /export interface DesktopKeyboardShortcutsSurfacePropsV2/u);
  assert.match(surface, /<KeyboardShortcutsDialog \{\.\.\.input\}\s*\/>/u);
  assert.doesNotMatch(
    surface,
    /useDesktopRendererGenerationV2|acquireOperationLease|meta\.digest|generation(?:Digest|Version)|\bkey=|use(?:Layout)?Effect|useState|useReducer/u,
  );

  assert.match(shell, /DesktopRendererKeyboardShortcutsV2/u);
  assert.match(shell, /keyboardShortcuts:\s*DesktopKeyboardShortcutsInputV2/u);
  assert.match(
    shell,
    /<DesktopRendererKeyboardShortcutsV2 input=\{surfaces\.keyboardShortcuts\}\s*\/>/u,
  );
  assert.doesNotMatch(
    shell,
    /ComponentProps<typeof KeyboardShortcutsDialog>|<KeyboardShortcutsDialog\b|features\/navigation\/KeyboardShortcutsDialog/u,
  );
  assert.doesNotMatch(app, /<KeyboardShortcutsDialog\b/u);
});

test('keyboard shortcuts resolver validates the exact slot contract and fails closed', () => {
  assert.match(compositionPort, /DESKTOP_KEYBOARD_SHORTCUTS_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveKeyboardShortcutsSurface/u);
  assert.match(compositionPort, /projectDesktopKeyboardShortcutsCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_keyboard_shortcuts_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_keyboard_shortcuts_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_keyboard_shortcuts_module_unavailable/u);
  assert.match(composition, /import \{ DesktopKeyboardShortcutsSurfaceV2 \}/u);
  assert.match(composition, /validKeyboardShortcutsDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'keyboard_shortcuts_surface'/u);
  assert.match(composition, /definition\.id === 'keyboard-shortcuts'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-keyboard-shortcuts-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_KEYBOARD_SHORTCUTS_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.keyboard-shortcuts'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'keyboard_shortcuts_surface'/u);
  assert.match(sharedSlotTypes, /\| 'keyboard_shortcuts_surface'/u);
});

test('keyboard shortcuts contribution is ordered after settings and before session canvas', () => {
  assert.match(
    artifactCatalog,
    /DESKTOP_KEYBOARD_SHORTCUTS_SURFACE_ARTIFACT_ID_V2\s*=\s*\n?\s*'desktop\.ui-slots\.keyboard-shortcuts-surface\.v1'/u,
  );
  assert.match(artifactCatalog, /slot:\s*'keyboard_shortcuts_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-keyboard-shortcuts-surface'/u);

  const settingsIndex = profile.indexOf('entry_id: builtin-desktop-settings-window-surface');
  const shortcutsIndex = profile.indexOf('entry_id: builtin-desktop-keyboard-shortcuts-surface');
  const sessionCanvasIndex = profile.indexOf('entry_id: builtin-desktop-session-canvas-surface');
  assert.ok(settingsIndex >= 0);
  assert.ok(shortcutsIndex > settingsIndex);
  assert.ok(sessionCanvasIndex > shortcutsIndex);
  const shortcutsEntry = profile.slice(shortcutsIndex, sessionCanvasIndex);
  assert.match(shortcutsEntry, /id:\s*desktop\.keyboard-shortcuts-surface/u);
  assert.match(shortcutsEntry, /order:\s*82/u);
  assert.match(shortcutsEntry, /desktop\.ui-slots\.keyboard-shortcuts-surface\.v1/u);

  const shortcutsBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-keyboard-shortcuts-surface',
  );
  assert.deepEqual(shortcutsBootstrap?.config, {
    id: 'desktop.keyboard-shortcuts-surface',
    kind: 'ui-slot',
    order: 82,
    payload: {
      artifact_refs: ['desktop.ui-slots.keyboard-shortcuts-surface.v1'],
      schema_version: 1,
    },
  });
});

test('keyboard shortcuts projection rejects missing, duplicate, wrong, and inactive generations', () => {
  const {
    DESKTOP_KEYBOARD_SHORTCUTS_SURFACE_MODULE_REF_V2,
    projectDesktopKeyboardShortcutsCompositionV2,
  } = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererCompositionPortV2.js');
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'keyboard_shortcuts_surface',
    id: 'keyboard-shortcuts',
    contract: 'ui-builtin:desktop-keyboard-shortcuts-surface',
    moduleRef: DESKTOP_KEYBOARD_SHORTCUTS_SURFACE_MODULE_REF_V2,
    permission: 'ui.keyboard-shortcuts',
    sandbox: true,
  });
  function KeyboardShortcutsSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveKeyboardShortcutsSurface: (definition) =>
      definition.moduleRef === DESKTOP_KEYBOARD_SHORTCUTS_SURFACE_MODULE_REF_V2
        ? KeyboardShortcutsSurface
        : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  assert.deepEqual(
    projectDesktopKeyboardShortcutsCompositionV2(authority('ready', [slot]), port),
    Object.freeze({ status: 'ready', Surface: KeyboardShortcutsSurface }),
  );
  assert.deepEqual(
    projectDesktopKeyboardShortcutsCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_keyboard_shortcuts_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_keyboard_shortcuts_contribution_ambiguous',
    ],
    [
      authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-keyboard-shortcuts' }]),
      'desktop_renderer_keyboard_shortcuts_module_unavailable',
    ],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopKeyboardShortcutsCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopKeyboardShortcutsCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ resolveKeyboardShortcutsSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_keyboard_shortcuts_module_unavailable',
    }),
  );
});

test('the original dialog retains focus restoration and portal ownership', () => {
  assert.match(dialog, /const restoreTargetRef = useRef<HTMLElement \| null>\(null\)/u);
  assert.match(dialog, /if \(!open\) return/u);
  assert.match(dialog, /window\.requestAnimationFrame/u);
  assert.match(dialog, /return createPortal\(<KeyboardShortcutsPanel/u);
});
