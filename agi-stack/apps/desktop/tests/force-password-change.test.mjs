import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  completeForcedPasswordChangeOutcome,
  passwordChangeGateAuthState,
  validateForcedPasswordChange,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/auth/forcePasswordChangeModel.js',
);
const { DesktopApiClient } = require(
  '/tmp/agistack-desktop-test-dist/src/api/client.js',
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const screenSource = readFileSync(
  new URL('../src/features/auth/ForcePasswordChangeScreen.tsx', import.meta.url),
  'utf8',
);
const screenStyles = readFileSync(
  new URL('../src/features/auth/ForcePasswordChangeScreen.css', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

test('forced password validation matches the Web field contract', () => {
  assert.deepEqual(
    validateForcedPasswordChange({
      currentPassword: '',
      newPassword: 'new-password',
      confirmPassword: 'new-password',
    }),
    { field: 'currentPassword', messageKey: 'forcePassword.currentRequired' },
  );
  assert.deepEqual(
    validateForcedPasswordChange({
      currentPassword: 'current-password',
      newPassword: 'short',
      confirmPassword: 'short',
    }),
    { field: 'newPassword', messageKey: 'forcePassword.minimumLength' },
  );
  assert.deepEqual(
    validateForcedPasswordChange({
      currentPassword: 'same-password',
      newPassword: 'same-password',
      confirmPassword: 'same-password',
    }),
    { field: 'newPassword', messageKey: 'forcePassword.mustDiffer' },
  );
  assert.deepEqual(
    validateForcedPasswordChange({
      currentPassword: 'current-password',
      newPassword: 'new-password',
      confirmPassword: 'different-password',
    }),
    { field: 'confirmPassword', messageKey: 'forcePassword.mismatch' },
  );
  assert.equal(
    validateForcedPasswordChange({
      currentPassword: 'current-password',
      newPassword: 'new-password',
      confirmPassword: 'new-password',
    }),
    null,
  );
});

test('the public password-change gate contains no credential material', () => {
  const required = passwordChangeGateAuthState(false, null);
  const submitting = passwordChangeGateAuthState(true, 'retry');

  assert.equal(required.status, 'password_change_required');
  assert.equal(required.mustChangePassword, true);
  assert.equal(required.credentialKind, null);
  assert.equal(required.user, null);
  assert.equal(submitting.status, 'changing_password');
  assert.equal(submitting.error, 'retry');
  assert.doesNotMatch(
    JSON.stringify(required),
    /access_token|transient-token|current-password|new-password/i,
  );

  const completed = completeForcedPasswordChangeOutcome({
    access_token: 'transient-token',
    token_type: 'bearer',
    must_change_password: true,
  });
  assert.equal(completed.must_change_password, false);
  assert.equal(completed.access_token, 'transient-token');
});

test('desktop password change uses the authenticated endpoint without URL credentials', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ input: String(input), init });
    return new Response(
      JSON.stringify({ success: true, message: 'Password changed successfully' }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      mode: 'cloud',
      apiBaseUrl: 'https://api.memstack.test',
      apiKey: 'transient-token',
    });
    const outcome = await client.forceChangePassword(
      'current-password',
      'new-password',
    );

    assert.deepEqual(outcome, {
      success: true,
      message: 'Password changed successfully',
    });
    assert.equal(calls.length, 1);
    assert.equal(
      calls[0].input,
      'https://api.memstack.test/api/v1/auth/force-change-password',
    );
    assert.equal(calls[0].init.method, 'POST');
    assert.equal(
      new Headers(calls[0].init.headers).get('Authorization'),
      'Bearer transient-token',
    );
    assert.deepEqual(JSON.parse(String(calls[0].init.body)), {
      old_password: 'current-password',
      new_password: 'new-password',
    });
    assert.doesNotMatch(calls[0].input, /current-password|new-password|transient-token/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('the forced password screen is localized, accessible, and cannot bypass the gate', () => {
  assert.match(screenSource, /export function ForcePasswordChangeScreen/);
  assert.match(screenSource, /validateForcedPasswordChange/);
  assert.match(screenSource, /autoComplete="current-password"/);
  assert.match(screenSource, /autoComplete="new-password"/);
  assert.match(screenSource, /role="alert"/);
  assert.match(screenSource, /onSignOut/);
  assert.match(screenSource, /disabled=\{busy\}/);
  assert.match(screenStyles, /\.force-password-screen/);

  for (const key of [
    'forcePassword.title',
    'forcePassword.subtitle',
    'forcePassword.currentPassword',
    'forcePassword.newPassword',
    'forcePassword.confirmPassword',
    'forcePassword.submit',
    'forcePassword.signOut',
    'forcePassword.minimumLength',
    'forcePassword.mustDiffer',
    'forcePassword.mismatch',
    'forcePassword.changedSignInFailed',
  ]) {
    assert.equal(
      (i18nSource.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) ?? []).length,
      2,
      key,
    );
  }
});

test('App retains the transient token only for the guarded flow and persists after success', () => {
  assert.match(appSource, /pendingPasswordChangeRef/);
  assert.match(appSource, /passwordChangeTokenRetained = true/);
  assert.match(appSource, /passwordChangeGateAuthState\(false, null\)/);
  assert.match(appSource, /forceChangePassword\(currentPassword, newPassword\)/);
  assert.match(appSource, /completeForcedPasswordChangeOutcome/);
  assert.match(appSource, /auth\.status === 'password_change_required'/);
  assert.match(appSource, /auth\.status === 'changing_password'/);
  assert.match(appSource, /<ForcePasswordChangeScreen/);

  const flowStart = appSource.indexOf('const submitForcedPasswordChange');
  const flowEnd = appSource.indexOf('const hydrateLocalSession', flowStart);
  const flowSource = appSource.slice(flowStart, flowEnd);
  const passwordChange = flowSource.indexOf('.forceChangePassword(');
  const trustedSave = flowSource.indexOf('saveNativeTrustedSession(');
  assert.ok(passwordChange >= 0);
  assert.ok(trustedSave > passwordChange);
  assert.doesNotMatch(flowSource, /localStorage|sessionStorage/);
});
