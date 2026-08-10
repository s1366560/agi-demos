import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const mainSource = readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8');
const preloadSource = readFileSync(new URL('../electron/preload/index.ts', import.meta.url), 'utf8');
const builderSource = readFileSync(new URL('../electron-builder.yml', import.meta.url), 'utf8');

test('packaged Electron registers a dedicated OAuth callback protocol', () => {
  assert.match(builderSource, /protocols:[\s\S]*schemes:[\s\S]*- agistack-auth/u);
  assert.match(mainSource, /setAsDefaultProtocolClient\(OAUTH_CALLBACK_SCHEME/u);
  assert.doesNotMatch(mainSource, /setAsDefaultProtocolClient\(RENDERER_PROTOCOL_SCHEME/u);
});

test('Electron captures cold-start, macOS, and second-instance OAuth callbacks', () => {
  assert.match(mainSource, /app\.on\('open-url',[\s\S]*enqueueOAuthCallbackUrl\(url\)/u);
  assert.match(
    mainSource,
    /app\.on\('second-instance', \(_event, commandLine\)[\s\S]*enqueueOAuthCallbackArgv\(commandLine\)/u,
  );
  assert.match(mainSource, /enqueueOAuthCallbackArgv\(process\.argv\)/u);
  assert.match(mainSource, /pendingOAuthCallback/u);
});

test('OAuth callback exchange stays main-owned and emits only a sanitized session event', () => {
  assert.match(mainSource, /new DesktopOAuthCallbackAuthority/u);
  assert.match(mainSource, /sidecarSupervisor[\s\S]*invoke\('trusted_session_save'/u);
  assert.match(mainSource, /OAUTH_SESSION_CHANGED_CHANNEL/u);
  assert.match(preloadSource, /OAUTH_SESSION_CHANGED_CHANNEL/u);
  assert.match(preloadSource, /onOAuthSessionChanged/u);
  assert.doesNotMatch(preloadSource, /code.*state|access_token|cloud_bearer/u);
});

test('renderer can begin OAuth only through the main-frame authorized command', () => {
  assert.match(preloadSource, /'oauth_list_providers'/u);
  assert.match(preloadSource, /'oauth_begin_authorization'/u);
  assert.match(mainSource, /case 'oauth_list_providers':/u);
  assert.match(mainSource, /case 'oauth_begin_authorization':/u);
  assert.match(
    mainSource,
    /case 'oauth_list_providers':[\s\S]*authorizedCloudRequestOwner\(event\)[\s\S]*oauthCallbackAuthority\.listProviders/u,
  );
  assert.match(
    mainSource,
    /case 'oauth_begin_authorization':[\s\S]*authorizedCloudRequestOwner\(event\)[\s\S]*oauthCallbackAuthority\.begin/u,
  );
});

test('pending OAuth attempts persist in the encrypted sidecar vault and expose restore and cancel only', () => {
  assert.match(mainSource, /pendingAttemptPersistence:[\s\S]*oauth_pending_attempt_load/u);
  assert.match(mainSource, /oauth_pending_attempt_save/u);
  assert.match(mainSource, /oauth_pending_attempt_clear/u);
  assert.match(preloadSource, /'oauth_restore_authorization'/u);
  assert.match(preloadSource, /'oauth_cancel_authorization'/u);
  assert.match(mainSource, /case 'oauth_restore_authorization':/u);
  assert.match(mainSource, /oauthCallbackAuthority\.restore\(\)/u);
  assert.match(mainSource, /case 'oauth_cancel_authorization':/u);
  assert.match(mainSource, /oauthCallbackAuthority\.cancel\(\)/u);
  assert.doesNotMatch(preloadSource, /oauth_pending_attempt_(?:load|save|clear)/u);
});
