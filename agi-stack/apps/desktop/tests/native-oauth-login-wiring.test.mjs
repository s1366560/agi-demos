import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const authSource = readFileSync(
  new URL('../src/hooks/useCloudSessionAuth.ts', import.meta.url),
  'utf8',
);
const loginSource = readFileSync(
  new URL('../src/features/auth/LoginScreen.tsx', import.meta.url),
  'utf8',
);

test('Cloud LoginScreen renders main-owned OAuth providers without authorization metadata', () => {
  assert.match(loginSource, /nativeOAuthProviders\.map/u);
  assert.match(loginSource, /onNativeOAuth\(provider\.id\)/u);
  assert.doesNotMatch(loginSource, /authorizationUrl.*nativeOAuth|nativeOAuth.*authorizationUrl/u);
});

test('native OAuth login subscribes to credential-free events and hydrates the vault projection', () => {
  assert.match(authSource, /desktopNativeOAuthClient/u);
  assert.match(authSource, /\.listProviders\(/u);
  assert.match(authSource, /client\.subscribe/u);
  assert.match(authSource, /desktopCloudSessionProjectionClient/u);
  assert.match(authSource, /createProjectedCloudSessionState/u);
  assert.doesNotMatch(authSource, /event\.(?:credential|accessToken|access_token|code|state)/u);
});

test('native OAuth login restores persisted attempts and clears them through main authority', () => {
  assert.match(authSource, /\.restore\(\)/u);
  assert.match(authSource, /pending\.status !== 'pending'/u);
  assert.match(authSource, /client\.cancel\(\)/u);
  assert.doesNotMatch(authSource, /localStorage[\s\S]*OAuth|OAuth[\s\S]*localStorage/u);
});

test('Cloud native resume no longer loads the bearer into App and restores a canonical route', () => {
  assert.doesNotMatch(appSource, /loadNativeTrustedSession/u);
  assert.match(appSource, /hydrateProjectedCloudSession/u);
  assert.match(appSource, /resolveNativeOAuthResumePath/u);
  assert.match(appSource, /nativeOAuthProviders=\{nativeOAuthProviders\}/u);
  assert.match(appSource, /onNativeOAuth=\{beginNativeOAuth\}/u);
});
