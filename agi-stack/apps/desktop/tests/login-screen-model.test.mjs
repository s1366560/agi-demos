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

test('local workspace continue preserves the trusted-device choice when the runtime is ready', () => {
  assert.equal(resolveWorkspaceContinueLabelKey('local'), 'login.localWorkspace');
  assert.deepEqual(resolveWorkspaceSsoAction('local', true, true), {
    kind: 'local_session',
    trustedDevice: true,
  });
  assert.deepEqual(resolveWorkspaceSsoAction('local', true, false), {
    kind: 'local_session',
    trustedDevice: false,
  });
});

test('workspace continue starts device authorization in cloud and fails closed for local startup', () => {
  assert.equal(resolveWorkspaceContinueLabelKey('cloud'), 'login.workspaceSso');
  assert.deepEqual(resolveWorkspaceSsoAction('local', false, false), {
    kind: 'unavailable',
    capability: 'local_workspace',
  });
  assert.deepEqual(resolveWorkspaceSsoAction('cloud', true, false), {
    kind: 'workspace_sso',
  });
});

test('device authorization URLs preserve the configured authority and reject unsafe shapes', () => {
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://memstack.example/api',
      '/device?user_code=ABCDEFGH',
      'ABCDEFGH',
    ),
    'https://memstack.example/device?user_code=ABCDEFGH',
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://api.memstack.example',
      'https://api.memstack.example/device?user_code=ABCDEFGH',
      'ABCDEFGH',
    ),
    'https://api.memstack.example/device?user_code=ABCDEFGH',
  );
  assert.equal(
    resolveDeviceAuthorizationUrl(
      'https://api.memstack.example',
      'https://app.memstack.example/device?user_code=ABCDEFGH',
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
