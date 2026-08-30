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
const boundary = source('src/plugins/DesktopRendererCommandPaletteV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const palette = source('src/features/navigation/CommandPalette.tsx');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const surface = source('src/plugins/DesktopCommandPaletteSurfaceV2.tsx');
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

test('command palette is selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopCommandPaletteCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /if \(input\.kind === 'hidden'\) return null/u);
  assert.match(boundary, /data-command-palette-state=\{composition\.status\}/u);
  assert.ok(
    boundary.indexOf("commandPalette.status === 'ready'") <
      boundary.indexOf("input.kind === 'hidden'"),
    'the ready surface stays selected while the palette is hidden',
  );
  assert.doesNotMatch(
    boundary,
    /features\/navigation\/CommandPalette|fallback|acquireOperationLease|meta\.digest|\bkey=/u,
  );
  assert.doesNotMatch(boundary, /use(?:Layout)?Effect|useState|useReducer|useMemo/u);

  assert.match(surface, /export type DesktopCommandPaletteInputV2/u);
  assert.match(surface, /export interface DesktopCommandPaletteSurfacePropsV2/u);
  assert.match(surface, /createPortal\(<CommandPalette \{\.\.\.input\.props\}\s*\/>/u);
  assert.match(surface, /document\.body/u);
  assert.doesNotMatch(surface, /useDesktopRendererGenerationV2|acquireOperationLease/u);
  assert.doesNotMatch(surface, /meta\.digest|generation(?:Digest|Version)|\bkey=/u);

  assert.match(shell, /DesktopRendererCommandPaletteV2/u);
  assert.match(shell, /commandPalette:\s*DesktopCommandPaletteInputV2/u);
  assert.match(
    shell,
    /<DesktopRendererCommandPaletteV2 input=\{surfaces\.commandPalette\}\s*\/>/u,
  );
  assert.doesNotMatch(shell, /createPortal|<CommandPalette\b/u);
  assert.doesNotMatch(shell, /features\/navigation\/CommandPalette/u);
  assert.doesNotMatch(app, /<CommandPalette\b/u);
});

test('command palette resolver validates the exact builtin same-realm slot contract', () => {
  assert.match(compositionPort, /DESKTOP_COMMAND_PALETTE_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveCommandPaletteSurface/u);
  assert.match(compositionPort, /projectDesktopCommandPaletteCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_command_palette_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_command_palette_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_command_palette_module_unavailable/u);
  assert.match(composition, /import \{ DesktopCommandPaletteSurfaceV2 \}/u);
  assert.match(composition, /validCommandPaletteDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'command_palette_surface'/u);
  assert.match(composition, /definition\.id === 'command-palette'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-command-palette-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_COMMAND_PALETTE_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.command-palette'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'command_palette_surface'/u);
  assert.match(sharedSlotTypes, /\| 'command_palette_surface'/u);
});

test('command palette contribution occupies the order 84 shell seam', () => {
  const artifactDeclaration = new RegExp(
    String.raw`DESKTOP_COMMAND_PALETTE_SURFACE_ARTIFACT_ID_V2\s*=\s*\n?\s*` +
      String.raw`'desktop\.ui-slots\.command-palette-surface\.v1'`,
    'u',
  );
  assert.match(artifactCatalog, artifactDeclaration);
  assert.match(artifactCatalog, /slot:\s*'command_palette_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-command-palette-surface'/u);

  const statusBarIndex = profile.indexOf('entry_id: builtin-desktop-status-bar-surface');
  const commandIndex = profile.indexOf('entry_id: builtin-desktop-command-palette-surface');
  const sessionCanvasIndex = profile.indexOf('entry_id: builtin-desktop-session-canvas-surface');
  assert.ok(statusBarIndex >= 0);
  assert.ok(commandIndex > statusBarIndex);
  assert.ok(sessionCanvasIndex > commandIndex);
  const commandEntry = profile.slice(commandIndex, sessionCanvasIndex);
  assert.match(commandEntry, /id:\s*desktop\.command-palette-surface/u);
  assert.match(commandEntry, /order:\s*84/u);
  assert.match(commandEntry, /desktop\.ui-slots\.command-palette-surface\.v1/u);

  const commandBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-command-palette-surface',
  );
  assert.deepEqual(commandBootstrap?.config, {
    id: 'desktop.command-palette-surface',
    kind: 'ui-slot',
    order: 84,
    payload: {
      artifact_refs: ['desktop.ui-slots.command-palette-surface.v1'],
      schema_version: 1,
    },
  });
});

test('command palette projection rejects malformed, duplicate, and inactive generations', () => {
  const {
    DESKTOP_COMMAND_PALETTE_SURFACE_MODULE_REF_V2,
    projectDesktopCommandPaletteCompositionV2,
  } = require(compiledPlugin('desktopRendererCompositionPortV2.js'));
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'command_palette_surface',
    id: 'command-palette',
    contract: 'ui-builtin:desktop-command-palette-surface',
    moduleRef: DESKTOP_COMMAND_PALETTE_SURFACE_MODULE_REF_V2,
    permission: 'ui.command-palette',
    sandbox: true,
  });
  function CommandPaletteSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveCommandPaletteSurface: (definition) =>
      definition.moduleRef === DESKTOP_COMMAND_PALETTE_SURFACE_MODULE_REF_V2
        ? CommandPaletteSurface
        : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  const ready = projectDesktopCommandPaletteCompositionV2(authority('ready', [slot]), port);
  assert.deepEqual(ready, Object.freeze({ status: 'ready', Surface: CommandPaletteSurface }));
  const unrelated = projectDesktopCommandPaletteCompositionV2(
    authority('ready', [slot, { ...slot, slot: 'settings_page', id: 'unrelated' }]),
    port,
  );
  assert.equal(unrelated.status, 'ready');
  assert.deepEqual(
    projectDesktopCommandPaletteCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_command_palette_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_command_palette_contribution_ambiguous',
    ],
    [
      authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-command-palette' }]),
      'desktop_renderer_command_palette_module_unavailable',
    ],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopCommandPaletteCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopCommandPaletteCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ resolveCommandPaletteSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_command_palette_module_unavailable',
    }),
  );
});

test('palette input, focus trap, and portal behavior remain surface-owned', () => {
  assert.match(palette, /window\.addEventListener\('focusin', keepFocusInsidePalette\)/u);
  assert.match(palette, /inputRef\.current\?\.focus\(\)/u);
  assert.match(palette, /if \(event\.key === 'Escape'\)/u);
  assert.match(surface, /createPortal/u);

  const inputStart = app.indexOf('commandPalette: commandPaletteOpen');
  const inputEnd = app.indexOf('keyboardShortcuts:', inputStart);
  const input = app.slice(inputStart, inputEnd);
  assert.match(input, /inputRef:\s*commandInputRef/u);
  assert.match(input, /query:\s*commandQuery/u);
  assert.match(input, /items:\s*filteredCommandItems/u);
  assert.match(input, /onQueryChange:\s*setCommandQuery/u);
  assert.match(input, /onClose:\s*closeCommandPalette/u);
});
