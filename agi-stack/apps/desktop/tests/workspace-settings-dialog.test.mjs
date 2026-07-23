import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const dialogSource = await readFile(
  new URL('../src/features/workspace/WorkspaceSettingsDialog.tsx', import.meta.url),
  'utf8',
);
const appSource = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('workspace Configure routes selected workspaces to their dedicated settings dialog', () => {
  assert.match(appSource, /const \[workspaceSettingsOpen, setWorkspaceSettingsOpen\]/);
  assert.match(
    appSource,
    /const openWorkspaceSettings = \(\) => \{[\s\S]*selectedWorkspace[\s\S]*setWorkspaceSettingsOpen\(true\)[\s\S]*openSettingsEntry\('workspace_overview'\)/,
  );
  assert.match(appSource, /<WorkspaceSettingsDialog[\s\S]*workspace=\{selectedWorkspace\}/);
  assert.match(appSource, /onSave=\{updateWorkspaceFromDialog\}/);
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
