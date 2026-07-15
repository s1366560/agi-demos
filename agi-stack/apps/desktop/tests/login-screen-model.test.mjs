import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  resolveWorkspaceContinueLabelKey,
  resolveWorkspaceSsoAction,
  validateLoginCredentials,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/auth/loginScreenModel.js',
);

test('local workspace continue uses one trusted native session when the runtime is ready', () => {
  assert.equal(resolveWorkspaceContinueLabelKey('local'), 'login.localWorkspace');
  assert.deepEqual(resolveWorkspaceSsoAction('local', true), {
    kind: 'local_session',
    trustedDevice: true,
  });
});

test('workspace continue reports the unavailable capability for each runtime mode', () => {
  assert.equal(resolveWorkspaceContinueLabelKey('cloud'), 'login.workspaceSso');
  assert.deepEqual(resolveWorkspaceSsoAction('local', false), {
    kind: 'unavailable',
    capability: 'local_workspace',
  });
  assert.deepEqual(resolveWorkspaceSsoAction('cloud', true), {
    kind: 'unavailable',
    capability: 'workspace_sso',
  });
});

test('email login enforces the approved structural credential boundary', () => {
  assert.equal(validateLoginCredentials('alex@northstar.ai', '123456'), null);
  assert.equal(validateLoginCredentials(' alex@northstar.ai ', '123456'), null);
  assert.equal(validateLoginCredentials('alex.northstar.ai', '123456'), 'invalid_credentials');
  assert.equal(validateLoginCredentials('alex@northstar.ai', '12345'), 'invalid_credentials');
  assert.equal(validateLoginCredentials('', ''), 'invalid_credentials');
});
