import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  isTrustedAudioMediaPermission,
} = require('/tmp/agistack-desktop-test-dist/electron/main/mediaPermissionPolicy.js');

const mainSource = readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8');
const preloadSource = readFileSync(
  new URL('../electron/preload/index.ts', import.meta.url),
  'utf8',
);
const builderConfig = readFileSync(new URL('../electron-builder.yml', import.meta.url), 'utf8');
const macEntitlements = readFileSync(
  new URL('../electron/resources/entitlements.mac.plist', import.meta.url),
  'utf8',
);
const inheritedMacEntitlements = readFileSync(
  new URL('../electron/resources/entitlements.mac.inherit.plist', import.meta.url),
  'utf8',
);
const localMacEntitlements = readFileSync(
  new URL('../electron/resources/entitlements.mac.local.plist', import.meta.url),
  'utf8',
);

const trustedRequest = {
  senderIsMainWindow: true,
  permission: 'media',
  requestingUrl: 'agistack://app/index.html',
  allowedOrigin: 'agistack://app',
  mediaTypes: ['audio'],
};

test('native media permission policy allows only trusted audio-only requests', () => {
  assert.equal(isTrustedAudioMediaPermission(trustedRequest), true);
  assert.equal(
    isTrustedAudioMediaPermission({
      ...trustedRequest,
      senderIsMainWindow: false,
    }),
    false,
  );
  assert.equal(
    isTrustedAudioMediaPermission({
      ...trustedRequest,
      requestingUrl: 'https://untrusted.example.test/',
    }),
    false,
  );
  assert.equal(isTrustedAudioMediaPermission({ ...trustedRequest, mediaTypes: ['video'] }), false);
  assert.equal(
    isTrustedAudioMediaPermission({
      ...trustedRequest,
      mediaTypes: ['audio', 'video'],
    }),
    false,
  );
  assert.equal(
    isTrustedAudioMediaPermission({
      ...trustedRequest,
      permission: 'display-capture',
    }),
    false,
  );
  assert.equal(
    isTrustedAudioMediaPermission({
      ...trustedRequest,
      allowedOrigin: 'http://127.0.0.1:5173',
      requestingUrl: 'http://127.0.0.1:5173/qa/session-steering.html',
    }),
    true,
  );
});

test('Electron brokers microphone access without widening the preload or media policy', () => {
  assert.match(mainSource, /setPermissionRequestHandler/);
  assert.match(mainSource, /setPermissionCheckHandler/);
  assert.match(mainSource, /askForMediaAccess\('microphone'\)/);
  assert.match(mainSource, /isTrustedAudioMediaPermission/);
  assert.match(preloadSource, /'request_microphone_access'/);
  assert.doesNotMatch(preloadSource, /getUserMedia|mediaDevices|ipcRenderer\.send/);
});

test('macOS packages explain microphone usage and ship the AudioWorklet asset', () => {
  assert.match(builderConfig, /NSMicrophoneUsageDescription:/);
  for (const entitlements of [
    macEntitlements,
    inheritedMacEntitlements,
    localMacEntitlements,
  ]) {
    assert.match(entitlements, /com\.apple\.security\.device\.audio-input/);
  }
  assert.equal(existsSync(new URL('../public/audio-processor.js', import.meta.url)), true);
});
