import assert from 'node:assert/strict';
import { test } from 'node:test';

const { desktopNativeCloudAuthClient } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/nativeCloudAuthClient.js'
);

test('native Cloud auth client exposes only token-free command results', async () => {
  const originalWindow = globalThis.window;
  const commands = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          commands.push({ command, args });
          if (command === 'cloud_auth_password') return { status: 'authenticated' };
          if (command === 'cloud_auth_device_begin') {
            return {
              status: 'authorization_pending',
              attemptId: 'device_attempt_12345678',
              userCode: 'ABCDEFGH',
              authorizationUrl: 'https://app.memstack.test/device?user_code=ABCDEFGH',
              expiresAt: 1_700_000_600_000,
              interval: 5,
            };
          }
          if (command === 'cloud_auth_device_poll') return { status: 'authenticated' };
          if (command === 'cloud_auth_device_cancel') return { cancelled: true };
          if (command === 'cloud_auth_force_password_change') {
            return { status: 'authenticated' };
          }
          if (command === 'cloud_auth_signout') return { success: true };
          throw new Error('unexpected command');
        },
      },
    },
  };
  try {
    const client = desktopNativeCloudAuthClient();
    assert.ok(client);
    assert.deepEqual(
      await client.loginWithPassword({
        apiBaseUrl: 'https://api.memstack.test',
        username: 'admin@memstack.test',
        password: 'password',
        trustedDevice: false,
      }),
      { status: 'authenticated' },
    );
    const device = await client.beginDeviceAuthorization({
      apiBaseUrl: 'https://api.memstack.test',
      deviceAuthorizationBaseUrl: 'https://app.memstack.test',
      trustedDevice: true,
    });
    assert.equal(JSON.stringify(device).includes('device_code'), false);
    assert.deepEqual(await client.pollDeviceAuthorization(device.attemptId), {
      status: 'authenticated',
    });
    assert.deepEqual(await client.cancelDeviceAuthorization(device.attemptId), {
      cancelled: true,
    });
    assert.deepEqual(
      await client.forceChangePassword({
        currentPassword: 'password',
        newPassword: 'new password',
      }),
      { status: 'authenticated' },
    );
    assert.deepEqual(await client.signOut(), { success: true });
    assert.deepEqual(
      commands.map(({ command }) => command),
      [
        'cloud_auth_password',
        'cloud_auth_device_begin',
        'cloud_auth_device_poll',
        'cloud_auth_device_cancel',
        'cloud_auth_force_password_change',
        'cloud_auth_signout',
      ],
    );
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('native Cloud auth client rejects credential-bearing or malformed main results', async () => {
  const originalWindow = globalThis.window;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke() {
          return { status: 'authenticated', access_token: 'must-not-cross-ipc' };
        },
      },
    },
  };
  try {
    await assert.rejects(
      desktopNativeCloudAuthClient().loginWithPassword({
        apiBaseUrl: 'https://api.memstack.test',
        username: 'admin@memstack.test',
        password: 'password',
        trustedDevice: false,
      }),
      /cloud_auth_result_invalid/u,
    );
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});
