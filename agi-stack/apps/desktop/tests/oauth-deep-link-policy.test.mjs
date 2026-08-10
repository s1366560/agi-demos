import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  OAuthDeepLinkPolicyError,
  parseOAuthCallbackDeepLink,
  selectOAuthDeepLinkFromArgv,
} = require('/tmp/agistack-desktop-test-dist/electron/main/oauthDeepLinkPolicy.js');

const state = 'a'.repeat(43);

test('native OAuth callback parser accepts only the dedicated success contract', () => {
  assert.deepEqual(
    parseOAuthCallbackDeepLink(
      `agistack-auth://oauth/callback/github?code=provider-code&state=${state}`,
    ),
    {
      kind: 'success',
      provider: 'github',
      code: 'provider-code',
      state,
    },
  );
});

test('native OAuth callback parser accepts a bounded provider error contract', () => {
  assert.deepEqual(
    parseOAuthCallbackDeepLink(
      `agistack-auth://oauth/callback/google?error=access_denied&state=${state}&error_description=Cancelled`,
    ),
    {
      kind: 'provider_error',
      provider: 'google',
      error: 'access_denied',
      errorDescription: 'Cancelled',
      state,
    },
  );
});

test('native OAuth callback parser rejects renderer URLs and malformed authorities', () => {
  for (const candidate of [
    `agistack://app/callback/github?code=x&state=${state}`,
    `agistack-auth://user@oauth/callback/github?code=x&state=${state}`,
    `agistack-auth://oauth:444/callback/github?code=x&state=${state}`,
    `agistack-auth://oauth/callback/github?code=x&state=${state}#fragment`,
    `agistack-auth://other/callback/github?code=x&state=${state}`,
    `agistack-auth://oauth/callback/github/extra?code=x&state=${state}`,
  ]) {
    assert.throws(() => parseOAuthCallbackDeepLink(candidate), OAuthDeepLinkPolicyError);
  }
});

test('native OAuth callback parser rejects ambiguous, unknown and oversized query data', () => {
  for (const candidate of [
    `agistack-auth://oauth/callback/github?code=x&code=y&state=${state}`,
    `agistack-auth://oauth/callback/github?code=x&state=${state}&unexpected=true`,
    `agistack-auth://oauth/callback/github?code=x&state=short`,
    `agistack-auth://oauth/callback/GitHub?code=x&state=${state}`,
    `agistack-auth://oauth/callback/github?code=${'x'.repeat(4097)}&state=${state}`,
    `agistack-auth://oauth/callback/github?error=access_denied&code=x&state=${state}`,
    `agistack-auth://oauth/callback/github?error=access_denied&state=${state}&error_description=${'x'.repeat(513)}`,
  ]) {
    assert.throws(() => parseOAuthCallbackDeepLink(candidate), OAuthDeepLinkPolicyError);
  }
});

test('argv selection supports cold start and second instance without accepting ambiguity', () => {
  const callback = `agistack-auth://oauth/callback/github?code=x&state=${state}`;
  assert.deepEqual(selectOAuthDeepLinkFromArgv(['/Applications/MemStack', callback]), {
    kind: 'success',
    provider: 'github',
    code: 'x',
    state,
  });
  assert.equal(selectOAuthDeepLinkFromArgv(['/Applications/MemStack', '--flag']), null);
  assert.throws(
    () => selectOAuthDeepLinkFromArgv(['/Applications/MemStack', callback, callback]),
    (error) =>
      error instanceof OAuthDeepLinkPolicyError &&
      error.reasonCode === 'oauth_deep_link_ambiguous',
  );
});
