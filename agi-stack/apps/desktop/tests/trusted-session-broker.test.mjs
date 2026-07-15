import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  clearNativeTrustedSession,
  decodeNativeTrustedSession,
  loadNativeTrustedSession,
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
