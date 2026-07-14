import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  clearTrustedLocalSessionReference,
  readTrustedLocalSessionReference,
  trustedLocalSessionStorageKey,
  writeTrustedLocalSessionReference,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/auth/trustedLocalSessionReference.js'
);

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}

test('trusted local session storage persists only the non-secret session reference', () => {
  const storage = memoryStorage();
  const now = Date.parse('2026-07-13T00:00:00Z');
  const reference = writeTrustedLocalSessionReference(
    storage,
    {
      session_id: 'local-session-1',
      auth_method: 'local',
      expires_at: '2026-07-14T00:00:00Z',
      trusted_device: true,
    },
    now,
  );

  assert.deepEqual(reference, {
    version: 1,
    sessionId: 'local-session-1',
    expiresAt: '2026-07-14T00:00:00Z',
  });
  const serialized = storage.getItem(trustedLocalSessionStorageKey);
  assert.deepEqual(JSON.parse(serialized), reference);
  assert.equal(serialized.includes('access_token'), false);
  assert.equal(serialized.includes('apiKey'), false);
});

test('untrusted, expired, or secret-bearing references are rejected and cleared', () => {
  const storage = memoryStorage();
  const now = Date.parse('2026-07-13T00:00:00Z');
  storage.setItem(
    trustedLocalSessionStorageKey,
    JSON.stringify({
      version: 1,
      sessionId: 'local-session-1',
      expiresAt: '2026-07-14T00:00:00Z',
      access_token: 'must-never-persist',
    }),
  );
  assert.equal(readTrustedLocalSessionReference(storage, now), null);
  assert.equal(storage.getItem(trustedLocalSessionStorageKey), null);

  writeTrustedLocalSessionReference(
    storage,
    {
      session_id: 'untrusted',
      auth_method: 'local',
      expires_at: '2026-07-14T00:00:00Z',
      trusted_device: false,
    },
    now,
  );
  assert.equal(storage.getItem(trustedLocalSessionStorageKey), null);

  storage.setItem(
    trustedLocalSessionStorageKey,
    JSON.stringify({ version: 1, sessionId: 'expired', expiresAt: '2026-07-12T00:00:00Z' }),
  );
  assert.equal(readTrustedLocalSessionReference(storage, now), null);
  clearTrustedLocalSessionReference(storage);
  assert.equal(storage.getItem(trustedLocalSessionStorageKey), null);
});
