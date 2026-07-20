import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  clearLocalTrustedSession,
  clearNativeTrustedSession,
  decodeNativeTrustedSession,
  loadLocalTrustedSession,
  loadNativeTrustedSession,
  saveLocalTrustedSession,
  saveNativeTrustedSession,
} = require('/tmp/agistack-desktop-test-dist/src/api/trustedSession.js');

const cloudRecord = {
  version: 1,
  api_base_url: 'https://memstack.example',
  runtime_mode: 'cloud',
  credential_kind: 'cloud_bearer',
  credential: 'ms_sk_redacted-test-only',
  expires_at: null,
};

const localRecord = {
  version: 1,
  api_base_url: 'http://127.0.0.1:61877/api/v1',
  runtime_mode: 'local',
  credential_kind: 'local_session_reference',
  credential: 'session-reference-test-only',
  expires_at: '2026-08-20T00:00:00Z',
};

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');

test('native trusted session decoder accepts only the versioned broker contract', () => {
  assert.deepEqual(decodeNativeTrustedSession(cloudRecord), cloudRecord);
  assert.equal(decodeNativeTrustedSession({ ...cloudRecord, version: 2 }), null);
  assert.equal(decodeNativeTrustedSession({ ...cloudRecord, credential: '' }), null);
  assert.equal(decodeNativeTrustedSession({ ...cloudRecord, extra: true }), null);
  assert.equal(
    decodeNativeTrustedSession({ ...cloudRecord, credential_kind: 'password' }),
    null,
  );
});

test('native trusted session commands preserve the strict Tauri broker contract', async () => {
  const commands = [];
  globalThis.window = {
    __TAURI__: {
      core: {
        invoke: async (command, args) => {
          commands.push({ command, args });
          return command === 'trusted_session_load' ? cloudRecord : null;
        },
      },
    },
  };

  assert.deepEqual(await loadNativeTrustedSession(), cloudRecord);
  await saveNativeTrustedSession(cloudRecord);
  await clearNativeTrustedSession();

  assert.deepEqual(commands, [
    { command: 'trusted_session_load', args: undefined },
    { command: 'trusted_session_save', args: { input: cloudRecord } },
    { command: 'trusted_session_clear', args: undefined },
  ]);
  delete globalThis.window;
});

test('local trusted session references use the SQLite broker instead of native credential storage', async () => {
  const commands = [];
  globalThis.window = {
    __TAURI__: {
      core: {
        invoke: async (command, args) => {
          commands.push({ command, args });
          return command === 'local_trusted_session_load' ? localRecord : null;
        },
      },
    },
  };

  assert.deepEqual(await loadLocalTrustedSession(), localRecord);
  await saveLocalTrustedSession(localRecord);
  await clearLocalTrustedSession();

  assert.deepEqual(commands, [
    { command: 'local_trusted_session_load', args: undefined },
    { command: 'local_trusted_session_save', args: { input: localRecord } },
    { command: 'local_trusted_session_clear', args: undefined },
  ]);
  assert.equal(commands.some(({ command }) => command === 'trusted_session_load'), false);
  assert.equal(commands.some(({ command }) => command === 'trusted_session_save'), false);
  assert.equal(commands.some(({ command }) => command === 'trusted_session_clear'), false);
  delete globalThis.window;
});

test('local login never invokes the native credential broker', () => {
  const localLogin = appSource.slice(
    appSource.indexOf('const loginLocalSession = async'),
    appSource.indexOf('const handleConfigChange ='),
  );
  assert.match(localLogin, /clearLocalTrustedSession/);
  assert.match(localLogin, /saveLocalTrustedSession/);
  assert.doesNotMatch(localLogin, /clearNativeTrustedSession/);
  assert.doesNotMatch(localLogin, /saveNativeTrustedSession/);
});

test('malformed native records are cleared before a redacted error is returned', async () => {
  const commands = [];
  globalThis.window = {
    __TAURI__: {
      core: {
        invoke: async (command) => {
          commands.push(command);
          return command === 'trusted_session_load' ? { ...cloudRecord, unexpected: true } : null;
        },
      },
    },
  };

  await assert.rejects(loadNativeTrustedSession(), {
    message: 'The trusted desktop session record is invalid.',
  });
  assert.deepEqual(commands, ['trusted_session_load', 'trusted_session_clear']);
  delete globalThis.window;
});
