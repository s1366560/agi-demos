import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const controlSource = readFileSync(
  new URL('../sidecar/src/control.rs', import.meta.url),
  'utf8',
);
const electronMainSource = readFileSync(
  new URL('../electron/main/index.ts', import.meta.url),
  'utf8',
);
const electronPreloadSource = readFileSync(
  new URL('../electron/preload/index.ts', import.meta.url),
  'utf8',
);

test('the private sidecar command surface exposes only local-runtime capabilities', () => {
  assert.match(controlSource, /local_runtime_status/u);
  assert.match(controlSource, /local_runtime_configure/u);
  assert.match(controlSource, /trusted_session_(?:save|load|clear)/u);
  assert.match(controlSource, /local_trusted_session_(?:save|load|clear)/u);
  assert.match(controlSource, /platform_plugin_authority_select_v2/u);
  assert.match(controlSource, /platform_plugin_renderer_distribution_current_v2/u);
  assert.match(
    controlSource,
    /platform_plugin_renderer_distribution_current_v2[\s\S]*request\.args\.is_none\(\)[\s\S]*renderer_distribution_current_v2/u,
  );
  assert.match(electronMainSource, /SIDECAR_COMMANDS[\s\S]*platform_plugin_authority_select_v2/u);
  assert.match(electronPreloadSource, /allowedCommands[\s\S]*platform_plugin_authority_select_v2/u);
  assert.match(
    electronMainSource,
    /SIDECAR_COMMANDS[\s\S]*platform_plugin_renderer_distribution_current_v2/u,
  );
  assert.match(
    electronPreloadSource,
    /allowedCommands[\s\S]*platform_plugin_renderer_distribution_current_v2/u,
  );
  assert.match(
    electronMainSource,
    /platform_plugin_renderer_distribution_current_v2[\s\S]*authorizedCloudRequestOwner\(event\)[\s\S]*sidecarSupervisor\.invoke/u,
  );

  assert.doesNotMatch(controlSource, /open_device_authorization_url/u);
  assert.doesNotMatch(controlSource, /pub struct DesktopCore/u);
  assert.doesNotMatch(controlSource, /async fn (?:ingest|search|semantic_search)\b/u);
});

test('device authorization remains an Electron-owned validated external action', () => {
  assert.match(electronMainSource, /validateDeviceAuthorizationUrl/u);
  assert.match(electronMainSource, /open_device_authorization_url/u);
  assert.match(electronMainSource, /shell\.openExternal/u);
  assert.doesNotMatch(controlSource, /shell\.openExternal/u);
});
