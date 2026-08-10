import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledModule = '/tmp/agistack-desktop-test-dist/src/api/nativeOAuthClient.js';

afterEach(() => {
  delete globalThis.window;
});

test('native OAuth client begins authorization without receiving URL, state, or bearer', async () => {
  const { desktopNativeOAuthClient } = require(compiledModule);
  const commands = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async (command, args) => {
          commands.push({ command, args });
          return {
            status: 'authorization_opened',
            provider: 'github',
            expiresAt: 1_700_000,
          };
        },
      },
      events: {},
    },
  };

  const client = desktopNativeOAuthClient();
  assert.ok(client);
  const result = await client.begin({
    apiBaseUrl: 'https://cloud.memstack.test',
    provider: 'github',
    resumeRoute: '/tenant/tenant-1/overview',
  });

  assert.deepEqual(result, {
    status: 'authorization_opened',
    provider: 'github',
    expiresAt: 1_700_000,
  });
  assert.deepEqual(commands, [
    {
      command: 'oauth_begin_authorization',
      args: {
        apiBaseUrl: 'https://cloud.memstack.test',
        provider: 'github',
        resumeRoute: '/tenant/tenant-1/overview',
      },
    },
  ]);
  assert.equal(JSON.stringify(result).includes('state'), false);
  assert.equal(JSON.stringify(result).includes('token'), false);
});

test('native OAuth client lists only provider display metadata', async () => {
  const { desktopNativeOAuthClient } = require(compiledModule);
  const commands = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async (command, args) => {
          commands.push({ command, args });
          return [
            { id: 'github', displayName: 'GitHub' },
            { id: 'google', displayName: 'Google' },
          ];
        },
      },
      events: {},
    },
  };

  assert.deepEqual(
    await desktopNativeOAuthClient().listProviders({
      apiBaseUrl: 'https://cloud.memstack.test',
    }),
    [
      { id: 'github', displayName: 'GitHub' },
      { id: 'google', displayName: 'Google' },
    ],
  );
  assert.deepEqual(commands, [
    {
      command: 'oauth_list_providers',
      args: { apiBaseUrl: 'https://cloud.memstack.test' },
    },
  ]);
});

test('native OAuth client restores and explicitly cancels a persisted pending attempt', async () => {
  const { desktopNativeOAuthClient } = require(compiledModule);
  const commands = [];
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async (command, args) => {
          commands.push({ command, args });
          if (command === 'oauth_restore_authorization') {
            return {
              status: 'pending',
              provider: 'github',
              expiresAt: 1_700_000,
            };
          }
          return undefined;
        },
      },
      events: {},
    },
  };

  const client = desktopNativeOAuthClient();
  assert.deepEqual(await client.restore(), {
    status: 'pending',
    provider: 'github',
    expiresAt: 1_700_000,
  });
  await client.cancel();
  assert.deepEqual(commands, [
    { command: 'oauth_restore_authorization', args: undefined },
    { command: 'oauth_cancel_authorization', args: undefined },
  ]);
});

test('native OAuth pending decoder rejects secret-bearing and malformed restore results', async () => {
  const { desktopNativeOAuthClient } = require(compiledModule);
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async () => ({
          status: 'pending',
          provider: 'github',
          expiresAt: 1_700_000,
          state: 'forbidden',
        }),
      },
      events: {},
    },
  };

  await assert.rejects(desktopNativeOAuthClient().restore(), {
    message: 'oauth_pending_authorization_contract_invalid',
  });
});

test('native OAuth provider decoder rejects credential and authorization metadata', async () => {
  const { desktopNativeOAuthClient } = require(compiledModule);
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async () => [
          { id: 'github', displayName: 'GitHub', authorizationUrl: 'https://forbidden.test' },
        ],
      },
      events: {},
    },
  };

  await assert.rejects(
    desktopNativeOAuthClient().listProviders({ apiBaseUrl: 'https://cloud.memstack.test' }),
    { message: 'oauth_provider_list_contract_invalid' },
  );
});

test('native OAuth event decoder rejects extras and exposes only canonical session state', () => {
  const { decodeNativeOAuthSessionEvent } = require(compiledModule);

  assert.deepEqual(
    decodeNativeOAuthSessionEvent({
      status: 'authenticated',
      provider: 'github',
      resumeRoute: '/tenant/tenant-1/overview',
    }),
    {
      status: 'authenticated',
      provider: 'github',
      resumeRoute: '/tenant/tenant-1/overview',
    },
  );
  assert.deepEqual(
    decodeNativeOAuthSessionEvent({
      status: 'failed',
      reasonCode: 'oauth_provider_access_denied',
    }),
    {
      status: 'failed',
      reasonCode: 'oauth_provider_access_denied',
    },
  );
  assert.equal(
    decodeNativeOAuthSessionEvent({
      status: 'authenticated',
      provider: 'github',
      resumeRoute: '/tenant/tenant-1/overview',
      access_token: 'forbidden',
    }),
    null,
  );
});

test('native OAuth client subscribes through the preload event and fails closed on drift', () => {
  const { desktopNativeOAuthClient } = require(compiledModule);
  const received = [];
  let nativeListener;
  let unsubscribed = false;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: { invoke: async () => undefined },
      events: {
        onOAuthSessionChanged(listener) {
          nativeListener = listener;
          return () => {
            unsubscribed = true;
          };
        },
      },
    },
  };

  const unsubscribe = desktopNativeOAuthClient().subscribe((event) => received.push(event));
  nativeListener({
    status: 'authenticated',
    provider: 'github',
    resumeRoute: '/tenant/tenant-1/overview',
  });
  nativeListener({ status: 'authenticated', provider: 'github', credential: 'forbidden' });

  assert.deepEqual(received, [
    {
      status: 'authenticated',
      provider: 'github',
      resumeRoute: '/tenant/tenant-1/overview',
    },
    {
      status: 'failed',
      reasonCode: 'oauth_session_event_contract_invalid',
    },
  ]);
  unsubscribe();
  assert.equal(unsubscribed, true);
});
