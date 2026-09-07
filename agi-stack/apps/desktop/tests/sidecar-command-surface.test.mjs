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

test('renderer deliveries bind main-owned sessions and retire on document or identity changes', () => {
  const branch = electronMainSource.slice(
    electronMainSource.indexOf("case 'platform_plugin_renderer_delivery_current_v2':"),
    electronMainSource.indexOf("case 'platform_plugin_renderer_distribution_current_v2':"),
  );
  assert.match(branch, /authorizedCloudRequestOwner\(event\)/u);
  assert.match(branch, /owner = randomUUID\(\)/u);
  assert.match(branch, /owner_id: owner, delivery_token: args\?\.delivery_token, receipt: args\?\.receipt/u);
  assert.doesNotMatch(branch, /args\?\.(?:owner_id|api_base_url|credential|nonce|data_plane_id)/u);
  assert.match(branch, /rendererDeliveryOwnersV2\.get\(ownerId\) !== owner/u);
  assert.match(electronMainSource, /did-start-navigation[\s\S]*retireRendererDeliveryOwnerV2/u);
  assert.match(electronMainSource, /render-process-gone[\s\S]*retireRendererDeliveryOwnerV2/u);
  assert.match(electronPreloadSource, /platform_plugin_renderer_receipt_submit_v2/u);
  assert.doesNotMatch(electronPreloadSource, /plugin_renderer_data_plane_credential_(?:import|clear)_v2/u);
});
