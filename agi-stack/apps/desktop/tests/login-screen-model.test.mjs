import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { resolveWorkspaceSsoAction, validateLoginCredentials } = require(
  '/tmp/agistack-desktop-test-dist/src/features/auth/loginScreenModel.js',
);

test('workspace SSO uses one trusted native local session when the runtime is ready', () => {
  assert.deepEqual(resolveWorkspaceSsoAction('local', true), {
    kind: 'local_session',
    trustedDevice: true,
  });
});

test('workspace SSO never impersonates password login when no SSO runtime is configured', () => {
  assert.deepEqual(resolveWorkspaceSsoAction('local', false), {
    kind: 'unavailable',
  });
  assert.deepEqual(resolveWorkspaceSsoAction('cloud', true), {
    kind: 'unavailable',
  });
});

test('email login enforces the approved structural credential boundary', () => {
  assert.equal(validateLoginCredentials('alex@northstar.ai', '123456'), null);
  assert.equal(validateLoginCredentials(' alex@northstar.ai ', '123456'), null);
  assert.equal(validateLoginCredentials('alex.northstar.ai', '123456'), 'invalid_credentials');
  assert.equal(validateLoginCredentials('alex@northstar.ai', '12345'), 'invalid_credentials');
  assert.equal(validateLoginCredentials('', ''), 'invalid_credentials');
});
