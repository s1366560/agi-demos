import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const mainSource = readFileSync(
  new URL('../electron/main/index.ts', import.meta.url),
  'utf8',
);
const preloadSource = readFileSync(
  new URL('../electron/preload/index.ts', import.meta.url),
  'utf8',
);

test('Electron owns password, device, forced-change, and sign-out Cloud authentication', () => {
  for (const command of [
    'cloud_auth_password',
    'cloud_auth_force_password_change',
    'cloud_auth_device_begin',
    'cloud_auth_device_poll',
    'cloud_auth_device_cancel',
    'cloud_auth_signout',
  ]) {
    assert.match(preloadSource, new RegExp(`'${command}'`, 'u'));
    assert.match(mainSource, new RegExp(`case '${command}':`, 'u'));
  }
  assert.match(
    mainSource,
    /new DesktopCloudAuthenticationAuthority\([\s\S]*trusted_session_load[\s\S]*trusted_session_save[\s\S]*trusted_session_clear/u,
  );
  assert.match(
    mainSource,
    /cloudAuth\?\.clearTransientSession\(\)/u,
  );
});

test('Cloud authentication commands remain main-frame authorized', () => {
  assert.match(
    mainSource,
    /case 'cloud_auth_password':[\s\S]*authorizedCloudRequestOwner\(event\)[\s\S]*cloudAuthenticationAuthority\.loginWithPassword/u,
  );
  assert.match(
    mainSource,
    /case 'cloud_auth_device_poll':[\s\S]*authorizedCloudRequestOwner\(event\)[\s\S]*cloudAuthenticationAuthority\.pollDeviceAuthorization/u,
  );
});
