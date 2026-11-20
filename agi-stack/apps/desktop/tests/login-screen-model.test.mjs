import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  normalizeDeviceAuthorizationInterval,
  resolveDeviceAuthorizationUrl,
  resolveWorkspaceContinueLabelKey,
  resolveWorkspaceSsoAction,
  validateLoginCredentials,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/auth/loginScreenModel.js',
);
const {
  LEGACY_LOGIN_MODE_PREFERENCE_KEY,
  initialDesktopRuntimeConfig,
  purgeLegacyLoginModePreference,
  runsInElectronShell,
  runtimeConfigForLoginAvailability,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/auth/loginRuntimeModel.js',
);

function createMemoryStorage(initialValue = null) {
  let value = initialValue;
  return {
    getItem(key) {
      assert.equal(key, LEGACY_LOGIN_MODE_PREFERENCE_KEY);
      return value;
    },
    removeItem(key) {
      assert.equal(key, LEGACY_LOGIN_MODE_PREFERENCE_KEY);
      value = null;
    },
    value() {
      return value;
    },
  };
}

test('startup clears a retired local login preference and does not seed a local workspace', () => {
  const storage = createMemoryStorage('{"version":1,"mode":"local"}');
  assert.equal(purgeLegacyLoginModePreference(storage), true);
  assert.equal(storage.value(), null);
  const config = initialDesktopRuntimeConfig();
  assert.equal(config.mode, 'cloud');
  assert.equal(config.apiBaseUrl, 'http://127.0.0.1:8000');
  assert.equal(config.tenantId, 'default');
  assert.equal(config.projectId, '');
  assert.equal(config.apiKey, '');
  assert.equal(config.localApiToken, '');
});

test('clearing a cloud login-mode preference does not claim a local session was removed', () => {
  const storage = createMemoryStorage('{"version":1,"mode":"cloud"}');
  assert.equal(purgeLegacyLoginModePreference(storage), false);
  assert.equal(storage.value(), null);
  assert.equal(purgeLegacyLoginModePreference(createMemoryStorage(null)), false);
});

test('unreadable login-mode residue is removed and reported as a retired local session', () => {
  const storage = createMemoryStorage('not-json');
  assert.equal(purgeLegacyLoginModePreference(storage), true);
  assert.equal(storage.value(), null);
  const inaccessibleStorage = {
    getItem() {
      throw new Error('storage unavailable');
    },
    removeItem() {
      throw new Error('storage unavailable');
    },
  };
  assert.equal(purgeLegacyLoginModePreference(inaccessibleStorage), false);
});

test('login always uses the cloud runtime and drops local workspace seeds', () => {
  const local = {
    apiBaseUrl: 'http://127.0.0.1:8088',
    deviceAuthorizationBaseUrl: 'https://signin.memstack.example',
    apiKey: 'secret-token',
    localApiToken: 'local-token',
    tenantId: 'local',
    projectId: 'local-project',
    workspaceId: 'workspace-a',
    mode: 'local',
    workspaceRoot: '/workspace',
  };
  assert.deepEqual(runtimeConfigForLoginAvailability(local), {
    apiBaseUrl: 'http://127.0.0.1:8000',
    deviceAuthorizationBaseUrl: 'https://signin.memstack.example',
    apiKey: '',
    localApiToken: '',
    tenantId: 'default',
    projectId: '',
    workspaceId: '',
    mode: 'cloud',
    workspaceRoot: '/workspace',
  });
  const cloud = {
    ...local,
    mode: 'cloud',
    apiBaseUrl: 'https://cloud.example.test',
    tenantId: 'tenant-a',
    projectId: 'project-a',
  };
  assert.equal(runtimeConfigForLoginAvailability(cloud), cloud);
});

test('Electron shell detection requires the dedicated allow-listed bridge', () => {
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: { invoke: async () => undefined },
    },
  };
  assert.equal(runsInElectronShell(), true);

  globalThis.window = {
    __TAURI__: { core: { invoke: async () => undefined } },
  };
  assert.equal(runsInElectronShell(), false);
  delete globalThis.window;
});

test('workspace continue is cloud SSO and has no local session action', () => {
  assert.equal(resolveWorkspaceContinueLabelKey(), 'login.workspaceSso');
  assert.deepEqual(resolveWorkspaceSsoAction(), { kind: 'workspace_sso' });
});

test('device authorization URLs preserve the configured authority and reject unsafe shapes', () => {
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://app.memstack.example',
      '/device?user_code=ABCDEFGH',
      'ABCDEFGH',
    ),
    'https://app.memstack.example/device?user_code=ABCDEFGH',
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://app.memstack.example',
      'https://app.memstack.example/device?user_code=ABCDEFGH',
      'ABCDEFGH',
    ),
    'https://app.memstack.example/device?user_code=ABCDEFGH',
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://app.memstack.example',
      'https://api.memstack.example/device?user_code=ABCDEFGH',
      'ABCDEFGH',
    ),
    null,
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://memstack.example',
      'javascript:alert(1)',
      'ABCDEFGH',
    ),
    null,
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://memstack.example',
      'https://user@example.com/device?user_code=ABCDEFGH',
      'ABCDEFGH',
    ),
    null,
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://memstack.example',
      'https://@memstack.example/device?user_code=ABCDEFGH',
      'ABCDEFGH',
    ),
    null,
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://memstack.example',
      'https://memstack.example/device?user_code=one&user_code=two',
      'ABCDEFGH',
    ),
    null,
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://@memstack.example',
      'https://memstack.example/device?user_code=ABCDEFGH',
      'ABCDEFGH',
    ),
    null,
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://memstack.example',
      'https:\t//@memstack.example/device',
      'ABCDEFGH',
    ),
    null,
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://memstack.example',
      'https://example.com/device?user_code=ABCDEFGH#token',
      'ABCDEFGH',
    ),
    null,
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://memstack.example',
      'https://example.com/not-device?user_code=ABCDEFGH',
      'ABCDEFGH',
    ),
    null,
  );
});

test('device authorization URLs allow HTTP only for strict loopback authorities', () => {
  for (const baseUrl of [
    'http://localhost:8000/api',
    'http://127.0.0.1:8000',
    'http://127.42.9.7:8000',
    'http://[::1]:8000',
  ]) {
    assert.notEqual(
      resolveDeviceAuthorizationUrl(baseUrl, '/device?user_code=ABCDEFGH', 'ABCDEFGH'),
      null,
    );
  }

  for (const baseUrl of [
    'http://memstack.example',
    'http://localhost.example',
    'http://127.0.0.1.example',
    'http://128.0.0.1',
    'http://[::2]',
  ]) {
    assert.equal(
      resolveDeviceAuthorizationUrl(baseUrl, '/device?user_code=ABCDEFGH', 'ABCDEFGH'),
      null,
    );
  }
});

test('device authorization URL user code must be singular, non-empty, and response-bound', () => {
  for (const verificationUrl of [
    '/device',
    '/device?user_code=',
    '/device?user_code=ABCDEFGH&user_code=ABCDEFGH',
    '/device?user_code=HGFEDCBA',
    '/device?user_code=ABCDEFGH&scope=openid',
  ]) {
    assert.equal(
      resolveDeviceAuthorizationUrl(
        'https://memstack.example',
        verificationUrl,
        'ABCDEFGH',
      ),
      null,
    );
  }
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://memstack.example',
      '/device?user_code=ABCDEFGH',
      '',
    ),
    null,
  );
});

test('device authorization poll intervals are finite protocol-safe seconds', () => {
  assert.equal(normalizeDeviceAuthorizationInterval(5), 5);
  assert.equal(normalizeDeviceAuthorizationInterval(0), 1);
  assert.equal(normalizeDeviceAuthorizationInterval(120), 60);
  assert.equal(normalizeDeviceAuthorizationInterval(Number.NaN), 5);
});

test('email login enforces the approved structural credential boundary', () => {
  assert.equal(validateLoginCredentials('alex@northstar.ai', '123456'), null);
  assert.equal(validateLoginCredentials(' alex@northstar.ai ', '123456'), null);
  assert.equal(validateLoginCredentials('alex.northstar.ai', '123456'), 'invalid_credentials');
  assert.equal(validateLoginCredentials('alex@northstar.ai', '12345'), 'invalid_credentials');
  assert.equal(validateLoginCredentials('', ''), 'invalid_credentials');
});

test('an edited cloud login endpoint is preserved without restoring a local seed', () => {
  const current = {
    ...initialDesktopRuntimeConfig(),
    apiBaseUrl: 'http://127.0.0.1:18766',
    tenantId: 'tenant-a',
    projectId: 'project-a',
  };
  assert.equal(runtimeConfigForLoginAvailability(current).apiBaseUrl, 'http://127.0.0.1:18766');
  assert.equal(runtimeConfigForLoginAvailability(current).tenantId, 'tenant-a');
  assert.equal(runtimeConfigForLoginAvailability(current).projectId, 'project-a');
});
