import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { resolveWorkspaceSsoAction } = require(
  '/tmp/agistack-desktop-test-dist/src/features/auth/loginScreenModel.js',
);

test('workspace SSO uses the native local session only when the local runtime is ready', () => {
  assert.deepEqual(resolveWorkspaceSsoAction('local', true, true), {
    kind: 'local_session',
    trustedDevice: true,
  });
  assert.deepEqual(resolveWorkspaceSsoAction('local', true, false), {
    kind: 'local_session',
    trustedDevice: false,
  });
});

test('workspace SSO never impersonates password login when no SSO runtime is configured', () => {
  assert.deepEqual(resolveWorkspaceSsoAction('local', false, true), {
    kind: 'unavailable',
  });
  assert.deepEqual(resolveWorkspaceSsoAction('cloud', true, true), {
    kind: 'unavailable',
  });
});
