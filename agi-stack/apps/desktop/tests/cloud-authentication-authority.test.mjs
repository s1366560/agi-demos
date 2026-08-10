import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopCloudAuthenticationAuthority } = await import(
  '/tmp/agistack-desktop-test-dist/electron/main/cloudAuthenticationAuthority.js'
);

test('native password authentication adopts the bearer in the vault without returning it', async () => {
  const calls = [];
  const saved = [];
  const authority = authorityFor({
    calls,
    saved,
    responses: [
      jsonResponse({
        access_token: 'vault-only-token',
        token_type: 'bearer',
        must_change_password: false,
      }),
    ],
  });

  const result = await authority.loginWithPassword({
    apiBaseUrl: 'https://cloud.memstack.test',
    username: 'admin@memstack.test',
    password: 'correct horse battery staple',
    trustedDevice: false,
  });

  assert.deepEqual(result, { status: 'authenticated' });
  assert.equal(JSON.stringify(result).includes('vault-only-token'), false);
  assert.equal(calls[0].url, 'https://cloud.memstack.test/api/v1/auth/token');
  assert.equal(calls[0].init.body.toString(), 'username=admin%40memstack.test&password=correct+horse+battery+staple');
  assert.equal(new Headers(calls[0].init.headers).has('Authorization'), false);
  assert.deepEqual(saved[0], {
    input: {
      version: 1,
      api_base_url: 'https://cloud.memstack.test',
      runtime_mode: 'cloud',
      credential_kind: 'cloud_bearer',
      credential: 'vault-only-token',
      expires_at: null,
    },
  });
  assert.equal(await authority.clearTransientSession(), true);
});

test('a trusted session restored from the vault survives a normal application restart', async () => {
  let clearCalls = 0;
  const authority = new DesktopCloudAuthenticationAuthority({
    now: () => 1_700_000_000_000,
    randomId: () => 'device_attempt_12345678',
    async fetch() {
      throw new Error('unexpected fetch');
    },
    async loadTrustedSession() {
      return {
        version: 1,
        api_base_url: 'https://cloud.memstack.test',
        runtime_mode: 'cloud',
        credential_kind: 'cloud_bearer',
        credential: 'existing-vault-token',
        expires_at: null,
      };
    },
    async saveTrustedSession() {
      throw new Error('unexpected save');
    },
    async clearTrustedSession() {
      clearCalls += 1;
    },
  });

  assert.equal(await authority.clearTransientSession(), false);
  assert.equal(clearCalls, 0);
});

test('forced password change uses the vault token and never returns it', async () => {
  const calls = [];
  const saved = [];
  const authority = authorityFor({
    calls,
    saved,
    responses: [
      jsonResponse({
        access_token: 'pending-password-token',
        token_type: 'bearer',
        must_change_password: true,
      }),
      jsonResponse({ success: true, message: 'Password changed successfully' }),
    ],
  });

  assert.deepEqual(
    await authority.loginWithPassword({
      apiBaseUrl: 'https://cloud.memstack.test',
      username: 'admin@memstack.test',
      password: 'old password',
      trustedDevice: true,
    }),
    { status: 'password_change_required' },
  );
  assert.deepEqual(
    await authority.forceChangePassword({
      currentPassword: 'old password',
      newPassword: 'new password long enough',
    }),
    { status: 'authenticated' },
  );
  assert.equal(
    new Headers(calls[1].init.headers).get('Authorization'),
    'Bearer pending-password-token',
  );
  assert.deepEqual(JSON.parse(calls[1].init.body), {
    old_password: 'old password',
    new_password: 'new password long enough',
  });
  assert.equal(await authority.clearTransientSession(), false);
});

test('device authentication keeps device_code privileged through polling and cancellation', async () => {
  const calls = [];
  const saved = [];
  const authority = authorityFor({
    calls,
    saved,
    responses: [
      jsonResponse({
        device_code: 'device-code-must-stay-main-1234567890ABCDEFG',
        user_code: 'ABCDEFGH',
        verification_uri: '/device',
        verification_uri_complete: '/device?user_code=ABCDEFGH',
        expires_in: 600,
        interval: 5,
      }),
      jsonResponse(
        { detail: { error: 'authorization_pending', interval: 7 } },
        428,
      ),
      jsonResponse({ access_token: 'device-vault-token', token_type: 'bearer' }),
    ],
  });

  const opened = await authority.beginDeviceAuthorization({
    apiBaseUrl: 'https://api.memstack.test',
    deviceAuthorizationBaseUrl: 'https://app.memstack.test',
    trustedDevice: true,
  });
  assert.deepEqual(opened, {
    status: 'authorization_pending',
    attemptId: 'device_attempt_12345678',
    userCode: 'ABCDEFGH',
    authorizationUrl: 'https://app.memstack.test/device?user_code=ABCDEFGH',
    expiresAt: 1_700_000_600_000,
    interval: 5,
  });
  assert.equal(JSON.stringify(opened).includes('device-code-must-stay-main'), false);
  assert.deepEqual(await authority.pollDeviceAuthorization(opened.attemptId), {
    status: 'authorization_pending',
    interval: 7,
  });
  assert.deepEqual(await authority.pollDeviceAuthorization(opened.attemptId), {
    status: 'authenticated',
  });
  assert.deepEqual(saved.at(-1).input.credential, 'device-vault-token');
  assert.deepEqual(JSON.parse(calls[1].init.body), {
    device_code: 'device-code-must-stay-main-1234567890ABCDEFG',
  });
});

test('device cancellation revokes the privileged code and clears pending state', async () => {
  const calls = [];
  const authority = authorityFor({
    calls,
    saved: [],
    responses: [
      jsonResponse({
        device_code: 'device-code-must-stay-main-1234567890ABCDEFG',
        user_code: 'ABCDEFGH',
        verification_uri: '/device',
        verification_uri_complete: '/device?user_code=ABCDEFGH',
        expires_in: 600,
        interval: 5,
      }),
      jsonResponse({ success: true }),
    ],
  });
  const opened = await authority.beginDeviceAuthorization({
    apiBaseUrl: 'https://api.memstack.test',
    deviceAuthorizationBaseUrl: 'https://app.memstack.test',
    trustedDevice: false,
  });

  assert.deepEqual(await authority.cancelDeviceAuthorization(opened.attemptId), {
    cancelled: true,
  });
  assert.deepEqual(JSON.parse(calls[1].init.body), {
    device_code: 'device-code-must-stay-main-1234567890ABCDEFG',
  });
  await assert.rejects(
    authority.pollDeviceAuthorization(opened.attemptId),
    /cloud_auth_device_attempt_missing/u,
  );
});

test('native cloud authentication rejects unsafe origins and reflected credentials', async () => {
  const authority = authorityFor({
    calls: [],
    saved: [],
    responses: [],
  });
  await assert.rejects(
    authority.loginWithPassword({
      apiBaseUrl: 'http://cloud.memstack.test',
      username: 'admin@memstack.test',
      password: 'password',
      trustedDevice: false,
    }),
    /cloud_auth_contract_invalid/u,
  );

  const reflected = authorityFor({
    calls: [],
    saved: [],
    responses: [
      jsonResponse({
        access_token: 'reflected-token',
        token_type: 'bearer',
        must_change_password: false,
        detail: 'reflected-token',
      }),
    ],
  });
  await assert.rejects(
    reflected.loginWithPassword({
      apiBaseUrl: 'https://cloud.memstack.test',
      username: 'admin@memstack.test',
      password: 'password',
      trustedDevice: false,
    }),
    /cloud_auth_response_invalid/u,
  );
});

function authorityFor({ calls, saved, responses }) {
  let trustedSession = null;
  return new DesktopCloudAuthenticationAuthority({
    now: () => 1_700_000_000_000,
    randomId: () => 'device_attempt_12345678',
    async fetch(url, init) {
      calls.push({ url, init });
      const response = responses.shift();
      if (!response) throw new Error('unexpected fetch');
      return response;
    },
    async loadTrustedSession() {
      return trustedSession;
    },
    async saveTrustedSession(input) {
      saved.push(input);
      trustedSession = input.input;
    },
    async clearTrustedSession() {
      trustedSession = null;
    },
  });
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
