import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const settingsSource = readFileSync(
  new URL('../src/features/settings/SettingsCorePages.tsx', import.meta.url),
  'utf8',
);

test('workspace settings opens only the allow-listed project control-plane destination', () => {
  const workspaceSettings =
    settingsSource.match(
      /export function WorkspaceSettingsPage\([\s\S]*?\nexport function GeneralSettingsPage/u,
    )?.[0] ?? '';
  assert.match(workspaceSettings, /window\.__MEMSTACK_DESKTOP__\?\.openWebControlPlane/u);
  assert.match(workspaceSettings, /destination: 'project-settings'/u);
  assert.match(workspaceSettings, /tenantId: config\.tenantId/u);
  assert.match(workspaceSettings, /projectId: config\.projectId/u);
  assert.doesNotMatch(workspaceSettings, /https?:\/\//u);
  assert.doesNotMatch(workspaceSettings, /\burl:/u);
});

test('workspace settings disables the Web entry from a structured native capability', () => {
  const workspaceSettings =
    settingsSource.match(
      /export function WorkspaceSettingsPage\([\s\S]*?\nexport function GeneralSettingsPage/u,
    )?.[0] ?? '';
  assert.match(workspaceSettings, /getCapabilities/u);
  assert.match(workspaceSettings, /webControlPlaneCapability/u);
  assert.match(
    workspaceSettings,
    /webControlPlaneCapability\.availability !== 'available'/u,
  );
  assert.match(workspaceSettings, /await onContextChange\(tenantId, projectId\)/u);
  assert.match(workspaceSettings, /onApplied\(\)/u);
});
