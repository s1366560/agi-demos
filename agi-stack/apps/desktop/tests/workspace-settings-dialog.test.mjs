import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const dialogSource = await readFile(
  new URL('../src/features/workspace/WorkspaceSettingsDialog.tsx', import.meta.url),
  'utf8',
);
const appSource = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');
const shellSurfaceSource = await readFile(
  new URL('../src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx', import.meta.url),
  'utf8',
);

test('workspace Configure routes selected workspaces to their dedicated settings dialog', () => {
  assert.match(appSource, /const \[workspaceSettingsOpen, setWorkspaceSettingsOpen\]/);
  assert.match(
    appSource,
    /const openWorkspaceSettings = \(\) => \{[\s\S]*selectedWorkspace[\s\S]*setWorkspaceSettingsOpen\(true\)[\s\S]*openSettingsEntry\('workspace_overview'\)/,
  );
  assert.match(
    shellSurfaceSource,
    /<DesktopRendererWorkspaceSettingsV2 input=\{surfaces\.workspaceSettings\}\s*\/>/u,
  );
  assert.doesNotMatch(shellSurfaceSource, /<WorkspaceSettingsDialog\b/u);
  assert.match(appSource, /workspaceSettings:\s*\{[\s\S]*workspace:\s*selectedWorkspace/u);
  assert.match(appSource, /onSave:\s*updateWorkspaceFromDialog/u);
});

test('workspace settings dialog exposes save, reset, archive, validation, and feedback contracts', () => {
  assert.match(dialogSource, /hydrateWorkspaceSettingsDraft/);
  assert.match(dialogSource, /workspaceSettingsDraftIsDirty/);
  assert.match(dialogSource, /workspaceSettingsProjectionSignature/);
  assert.match(dialogSource, /if \(!open \|\| busy \|\| dirty \|\| !workspace\) return/);
  assert.match(dialogSource, /buildWorkspaceUpdateInput/);
  assert.match(dialogSource, /workspaceSettings\.archive/);
  assert.match(dialogSource, /workspaceSettings\.reset/);
  assert.match(dialogSource, /workspaceSettings\.discardTitle/);
  assert.match(dialogSource, /aria-live=\{feedback\?\.tone/);
  assert.match(dialogSource, /disabled=\{busy \|\| !validation\.canSubmit \|\| !dirty\}/);
  assert.match(dialogSource, /error instanceof DesktopApiError && error\.status === 409/);
  assert.match(dialogSource, /WorkspaceSettingsScopeChangedError/);
});
