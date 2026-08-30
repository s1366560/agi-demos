import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const shellBoundary = source('src/plugins/DesktopRendererAuthenticatedShellV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const profile = readFileSync(
  new URL(
    '../../../../config/plugin-profiles/memstack-production-target-hosts.v2.yaml',
    import.meta.url,
  ),
  'utf8',
);

test('authenticated shell contribution owns desktop chrome without React child passthrough', () => {
  assert.match(compositionPort, /readonly viewModel:\s*DesktopAuthenticatedShellViewModelV2/u);
  const shellProps =
    compositionPort.match(
      /export interface DesktopRendererAuthenticatedShellSurfacePropsV2[\s\S]*?\n\}/u,
    )?.[0] ?? '';
  assert.doesNotMatch(shellProps, /ReactNode|children/u);
  assert.match(shellBoundary, /<Surface viewModel=\{viewModel\}\s*\/>/u);
  assert.doesNotMatch(shellBoundary, /children/u);
  assert.match(composition, /import \{ DesktopAuthenticatedShellSurfaceV2 \}/u);
  assert.match(
    composition,
    /validAuthenticatedShellDefinitionV2\(definition\)\s*\?\s*DesktopAuthenticatedShellSurfaceV2/u,
  );
  assert.doesNotMatch(composition, /Fragment|<Fragment>/u);
});

test('the V2 authenticated shell surface owns every production chrome outlet', () => {
  for (const component of [
    'DesktopTitlebar',
    'DesktopSidebar',
    'WorkbenchTabBar',
    'DesktopRendererProductionRouterV2',
    'DesktopRightSidebar',
    'DesktopRendererStatusBarV2',
    'DesktopRendererCommandPaletteV2',
    'DesktopRendererKeyboardShortcutsV2',
    'NewTaskFlow',
    'WorkspaceCreateDialog',
    'WorkspaceSettingsDialog',
    'DesktopRendererSettingsWindowV2',
  ]) {
    assert.match(shell, new RegExp(`<${component}\\b`, 'u'), `${component} owned by V2 surface`);
    assert.doesNotMatch(app, new RegExp(`<${component}\\b`, 'u'), `${component} absent from App`);
  }
  assert.doesNotMatch(
    shell,
    /<DesktopStatusBar\b|features\/chrome\/DesktopStatusBar|<CommandPalette\b|features\/navigation\/CommandPalette|<KeyboardShortcutsDialog\b|features\/navigation\/KeyboardShortcutsDialog|<SettingsWindow\b|features\/settings\/SettingsWindow/u,
  );
  assert.match(shell, /kind:\s*'hidden'/u);
  assert.match(shell, /kind:\s*'visible'/u);
  assert.match(app, /<DesktopRendererAuthenticatedShellV2\s+viewModel=\{desktopAuthenticatedShellViewModelV2\}\s*\/>/u);
  assert.doesNotMatch(app, /<DesktopRendererAuthenticatedShellV2>[\s\S]*?<\/DesktopRendererAuthenticatedShellV2>/u);
});

test('authenticated shell artifact revision identifies the no-passthrough contract', () => {
  assert.match(
    artifactCatalog,
    /DESKTOP_AUTHENTICATED_SHELL_SURFACE_ARTIFACT_ID_V2\s*=\s*'desktop\.ui-slots\.authenticated-shell-surface\.v2'/u,
  );
  const shellEntry = profile.slice(profile.indexOf('entry_id: builtin-desktop-authenticated-shell-surface'));
  assert.match(shellEntry, /desktop\.ui-slots\.authenticated-shell-surface\.v2/u);
  assert.doesNotMatch(shellEntry.split('\n    - entry_id:', 1)[0], /authenticated-shell-surface\.v1/u);
});
