import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const mainSource = readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8');
const preloadSource = readFileSync(
  new URL('../electron/preload/index.ts', import.meta.url),
  'utf8',
);

test('Electron main owns vault-bound Cloud socket creation and renderer-owner IPC', () => {
  assert.match(mainSource, /new DesktopCloudSocketBroker\(/u);
  assert.match(
    mainSource,
    /authorizeVaultBoundCloudSocket[\s\S]*trusted_session_load[\s\S]*net\.fetch/u,
  );
  for (const command of ['cloud_socket_open', 'cloud_socket_send', 'cloud_socket_close']) {
    assert.match(mainSource, new RegExp(`case '${command}':`, 'u'));
  }
  assert.match(
    mainSource,
    /case 'cloud_socket_open':[\s\S]*authorizedCloudRequestOwner\(event\)[\s\S]*cloudSocketBroker\.open/u,
  );
});

test('Cloud sockets are cancelled with renderer and application lifecycle', () => {
  assert.match(
    mainSource,
    /window\.on\('closed',[\s\S]*cloudSocketBroker\?\.cancelOwner\(cloudRequestOwnerId\)/u,
  );
  assert.match(
    mainSource,
    /render-process-gone[\s\S]*cloudSocketBroker\?\.cancelOwner\(cloudRequestOwnerId\)/u,
  );
  assert.match(mainSource, /before-quit[\s\S]*cloudSocketBroker\?\.cancelAll\(\)/u);
});

test('preload exposes only allow-listed socket commands and sanitized event subscription', () => {
  for (const command of ['cloud_socket_open', 'cloud_socket_send', 'cloud_socket_close']) {
    assert.match(preloadSource, new RegExp(`'${command}'`, 'u'));
  }
  assert.match(preloadSource, /function onCloudSocketEvent\(/u);
  assert.match(preloadSource, /events:[\s\S]*onCloudSocketEvent/u);
  assert.doesNotMatch(preloadSource, /protocols\s*:/u);
  const exposedBridge = preloadSource.slice(preloadSource.indexOf('contextBridge.exposeInMainWorld'));
  assert.doesNotMatch(exposedBridge, /\bipcRenderer\b/u);
});
