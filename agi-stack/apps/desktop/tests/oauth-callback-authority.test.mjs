import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  DesktopOAuthCallbackAuthority,
  DesktopOAuthCallbackAuthorityError,
} = require('/tmp/agistack-desktop-test-dist/electron/main/oauthCallbackAuthority.js');

const state = 'b'.repeat(43);
const apiBaseUrl = 'https://cloud.memstack.test';
const resumeRoute = '/tenant/tenant-1/project/project-1/overview';

test('main-owned OAuth provider discovery exposes only display metadata', async () => {
  const requests = [];
  const authority = createAuthority({
    requests,
    responses: [
      jsonResponse({
        providers: [
          { id: 'github', display_name: 'GitHub' },
          { id: 'google', display_name: 'Google' },
        ],
      }),
    ],
  });

  const providers = await authority.listProviders({ apiBaseUrl });

  assert.deepEqual(providers, [
    { id: 'github', displayName: 'GitHub' },
    { id: 'google', displayName: 'Google' },
  ]);
  assert.deepEqual(requests.map(({ url }) => new URL(url).pathname), [
    '/api/v1/auth/oauth/providers',
  ]);
  assert.equal(JSON.stringify(providers).includes('authorization_url'), false);
});

test('main-owned OAuth provider discovery rejects response drift', async () => {
  const authority = createAuthority({
    responses: [
      jsonResponse({
        providers: [{ id: 'github', display_name: 'GitHub', client_id: 'forbidden' }],
      }),
    ],
  });

  await assert.rejects(
    authority.listProviders({ apiBaseUrl }),
    (error) =>
      error instanceof DesktopOAuthCallbackAuthorityError &&
      error.reasonCode === 'oauth_authorization_contract_invalid',
  );
});

test('main-owned OAuth begin verifies the provider roster and hides provider state', async () => {
  const requests = [];
  const opened = [];
  const authority = createAuthority({
    requests,
    opened,
    responses: [
      jsonResponse({ providers: [{ id: 'github', display_name: 'GitHub' }] }),
      jsonResponse({
        provider: 'github',
        authorization_url: `https://github.test/authorize?client_id=desktop&state=${state}`,
        expires_in: 600,
      }),
    ],
  });

  const result = await authority.begin({ apiBaseUrl, provider: 'github', resumeRoute });

  assert.deepEqual(result, {
    status: 'authorization_opened',
    provider: 'github',
    expiresAt: 1_600_000,
  });
  assert.equal(JSON.stringify(result).includes(state), false);
  assert.deepEqual(opened, [
    `https://github.test/authorize?client_id=desktop&state=${state}`,
  ]);
  assert.deepEqual(requests.map(({ url }) => new URL(url).pathname), [
    '/api/v1/auth/oauth/providers',
    '/api/v1/auth/oauth/github/authorize',
  ]);
  assert.deepEqual(JSON.parse(requests[1].init.body), {
    redirect_to: resumeRoute,
    callback_surface: 'desktop',
  });
});

test('main-owned OAuth callback persists the bearer before returning a credential-free outcome', async () => {
  const requests = [];
  const savedSessions = [];
  const authority = createAuthority({
    requests,
    savedSessions,
    responses: beginResponses('github'),
  });
  await authority.begin({ apiBaseUrl, provider: 'github', resumeRoute });
  authority.enqueueResponse(
    jsonResponse({
      access_token: 'vault-only-oauth-session',
      token_type: 'bearer',
      redirect_to: resumeRoute,
      user: { user_id: 'user-1' },
    }),
  );

  const result = await authority.complete({
    kind: 'success',
    provider: 'github',
    code: 'provider-code',
    state,
  });

  assert.deepEqual(result, {
    status: 'authenticated',
    provider: 'github',
    resumeRoute,
  });
  assert.deepEqual(savedSessions, [
    {
      input: {
        version: 1,
        api_base_url: apiBaseUrl,
        runtime_mode: 'cloud',
        credential_kind: 'cloud_bearer',
        credential: 'vault-only-oauth-session',
        expires_at: null,
      },
    },
  ]);
  assert.equal(JSON.stringify(result).includes('vault-only-oauth-session'), false);
  assert.deepEqual(JSON.parse(requests[2].init.body), {
    code: 'provider-code',
    state,
  });
});

test('pending OAuth authority survives restart without exposing state or bearer', async () => {
  const pendingAttemptPersistence = createPendingAttemptPersistence();
  const authority = createAuthority({
    pendingAttemptPersistence,
    responses: beginResponses('github'),
  });
  await authority.begin({ apiBaseUrl, provider: 'github', resumeRoute });

  const savedSessions = [];
  const restartedAuthority = createAuthority({
    pendingAttemptPersistence,
    savedSessions,
    responses: [
      jsonResponse({
        access_token: 'restart-vault-only-session',
        token_type: 'bearer',
        redirect_to: resumeRoute,
        user: { user_id: 'user-1' },
      }),
    ],
  });

  const restored = await restartedAuthority.restore();
  assert.deepEqual(restored, {
    status: 'pending',
    provider: 'github',
    expiresAt: 1_600_000,
  });
  assert.equal(JSON.stringify(restored).includes(state), false);
  assert.equal(JSON.stringify(restored).includes(resumeRoute), false);

  const result = await restartedAuthority.complete({
    kind: 'success',
    provider: 'github',
    code: 'provider-code',
    state,
  });
  assert.deepEqual(result, {
    status: 'authenticated',
    provider: 'github',
    resumeRoute,
  });
  assert.equal(pendingAttemptPersistence.snapshot(), null);
  assert.equal(JSON.stringify(result).includes('restart-vault-only-session'), false);
  assert.equal(savedSessions[0].input.credential, 'restart-vault-only-session');
});

test('explicit OAuth cancellation clears durable pending authority', async () => {
  const pendingAttemptPersistence = createPendingAttemptPersistence();
  const authority = createAuthority({
    pendingAttemptPersistence,
    responses: beginResponses('github'),
  });
  await authority.begin({ apiBaseUrl, provider: 'github', resumeRoute });

  await authority.cancel();

  assert.equal(pendingAttemptPersistence.snapshot(), null);
  const restartedAuthority = createAuthority({ pendingAttemptPersistence });
  await assert.rejects(
    restartedAuthority.complete({
      kind: 'success',
      provider: 'github',
      code: 'provider-code',
      state,
    }),
    (error) => error.reasonCode === 'oauth_callback_pending_missing',
  );
});

test('expired persisted OAuth authority is cleared before callback exchange', async () => {
  let currentTime = 1_000_000;
  const pendingAttemptPersistence = createPendingAttemptPersistence();
  const authority = createAuthority({
    now: () => currentTime,
    pendingAttemptPersistence,
    responses: beginResponses('github'),
  });
  await authority.begin({ apiBaseUrl, provider: 'github', resumeRoute });
  currentTime = 1_600_000;

  const restartedAuthority = createAuthority({
    now: () => currentTime,
    pendingAttemptPersistence,
  });
  await assert.rejects(
    restartedAuthority.complete({
      kind: 'success',
      provider: 'github',
      code: 'provider-code',
      state,
    }),
    (error) => error.reasonCode === 'oauth_callback_pending_expired',
  );
  assert.equal(pendingAttemptPersistence.snapshot(), null);
  assert.deepEqual(await restartedAuthority.restore(), { status: 'empty' });
});

test('persisted provider or state mismatch is consumed before callback exchange', async () => {
  const requests = [];
  const pendingAttemptPersistence = createPendingAttemptPersistence();
  const authority = createAuthority({
    pendingAttemptPersistence,
    responses: beginResponses('github'),
  });
  await authority.begin({ apiBaseUrl, provider: 'github', resumeRoute });

  const restartedAuthority = createAuthority({ requests, pendingAttemptPersistence });
  await assert.rejects(
    restartedAuthority.complete({
      kind: 'success',
      provider: 'google',
      code: 'provider-code',
      state,
    }),
    (error) => error.reasonCode === 'oauth_callback_pending_mismatch',
  );
  assert.equal(requests.length, 0);
  assert.equal(pendingAttemptPersistence.snapshot(), null);
  await assert.rejects(
    restartedAuthority.complete({
      kind: 'success',
      provider: 'github',
      code: 'provider-code',
      state,
    }),
    (error) => error.reasonCode === 'oauth_callback_pending_missing',
  );
});

test('invalid persisted OAuth authority fails closed and is removed', async () => {
  const pendingAttemptPersistence = createPendingAttemptPersistence({
    version: 1,
    api_base_url: apiBaseUrl,
    provider: 'github',
    resume_route: resumeRoute,
    state,
    expires_at: 1_600_000,
    unexpected: true,
  });
  const authority = createAuthority({ pendingAttemptPersistence });

  await assert.rejects(
    authority.restore(),
    (error) => error.reasonCode === 'oauth_callback_pending_contract_invalid',
  );
  assert.equal(pendingAttemptPersistence.snapshot(), null);
});

test('OAuth pending persistence failure blocks browser authorization', async () => {
  const opened = [];
  const authority = createAuthority({
    opened,
    responses: beginResponses('github'),
    pendingAttemptPersistence: {
      async load() {
        return null;
      },
      async save() {
        throw new Error('vault unavailable');
      },
      async clear() {},
    },
  });

  await assert.rejects(
    authority.begin({ apiBaseUrl, provider: 'github', resumeRoute }),
    (error) => error.reasonCode === 'oauth_callback_pending_persistence_unavailable',
  );
  assert.deepEqual(opened, []);
});

test('browser authorization failure clears durable pending authority', async () => {
  const pendingAttemptPersistence = createPendingAttemptPersistence();
  const authority = createAuthority({
    pendingAttemptPersistence,
    responses: beginResponses('github'),
  });
  authority.enqueueOpenFailure(new Error('browser unavailable'));

  await assert.rejects(
    authority.begin({ apiBaseUrl, provider: 'github', resumeRoute }),
    (error) => error.reasonCode === 'oauth_authorization_open_failed',
  );
  assert.equal(pendingAttemptPersistence.snapshot(), null);
});

test('OAuth pending load and clear failures stop before callback exchange', async () => {
  const requests = [];
  const persistedAttempt = {
    version: 1,
    api_base_url: apiBaseUrl,
    provider: 'github',
    resume_route: resumeRoute,
    state,
    expires_at: 1_600_000,
  };
  const loadFailure = createAuthority({
    pendingAttemptPersistence: {
      async load() {
        throw new Error('vault unavailable');
      },
      async save() {},
      async clear() {},
    },
  });
  await assert.rejects(
    loadFailure.restore(),
    (error) => error.reasonCode === 'oauth_callback_pending_persistence_unavailable',
  );

  const clearFailure = createAuthority({
    requests,
    pendingAttemptPersistence: {
      async load() {
        return persistedAttempt;
      },
      async save() {},
      async clear() {
        throw new Error('vault unavailable');
      },
    },
  });
  await assert.rejects(
    clearFailure.complete({
      kind: 'success',
      provider: 'github',
      code: 'provider-code',
      state,
    }),
    (error) => error.reasonCode === 'oauth_callback_pending_persistence_unavailable',
  );
  assert.equal(requests.length, 0);
});

test('OAuth authority never persists pending state in renderer localStorage', () => {
  const source = readFileSync(
    new URL('../electron/main/oauthCallbackAuthority.ts', import.meta.url),
    'utf8',
  );
  assert.equal(source.includes('localStorage'), false);
});

test('pending attempt binds callback provider and state before any exchange', async () => {
  const requests = [];
  const authority = createAuthority({ requests, responses: beginResponses('github') });
  await authority.begin({ apiBaseUrl, provider: 'github', resumeRoute });

  await assert.rejects(
    authority.complete({
      kind: 'success',
      provider: 'google',
      code: 'provider-code',
      state,
    }),
    (error) =>
      error instanceof DesktopOAuthCallbackAuthorityError &&
      error.reasonCode === 'oauth_callback_pending_mismatch',
  );
  assert.equal(requests.length, 2);
});

test('provider denial consumes the pending attempt without calling callback exchange', async () => {
  const requests = [];
  const pendingAttemptPersistence = createPendingAttemptPersistence();
  const authority = createAuthority({
    requests,
    pendingAttemptPersistence,
    responses: beginResponses('github'),
  });
  await authority.begin({ apiBaseUrl, provider: 'github', resumeRoute });

  assert.deepEqual(
    await authority.complete({
      kind: 'provider_error',
      provider: 'github',
      error: 'access_denied',
      errorDescription: 'Cancelled',
      state,
    }),
    {
      status: 'failed',
      provider: 'github',
      reasonCode: 'oauth_provider_access_denied',
      resumeRoute: null,
    },
  );
  assert.equal(requests.length, 2);
  assert.equal(pendingAttemptPersistence.snapshot(), null);
  await assert.rejects(
    authority.complete({
      kind: 'success',
      provider: 'github',
      code: 'provider-code',
      state,
    }),
    (error) => error.reasonCode === 'oauth_callback_pending_missing',
  );
});

test('vault failure revokes the issued bearer and never reports authenticated', async () => {
  const requests = [];
  const authority = createAuthority({
    requests,
    responses: beginResponses('github'),
    async saveTrustedSession() {
      throw new Error('vault unavailable');
    },
  });
  await authority.begin({ apiBaseUrl, provider: 'github', resumeRoute });
  authority.enqueueResponse(
    jsonResponse({
      access_token: 'unadopted-session',
      token_type: 'bearer',
      redirect_to: resumeRoute,
      user: { user_id: 'user-1' },
    }),
  );
  authority.enqueueResponse(jsonResponse({ success: true }));

  await assert.rejects(
    authority.complete({
      kind: 'success',
      provider: 'github',
      code: 'provider-code',
      state,
    }),
    (error) =>
      error instanceof DesktopOAuthCallbackAuthorityError &&
      error.reasonCode === 'oauth_callback_vault_unavailable',
  );
  assert.equal(new URL(requests[3].url).pathname, '/api/v1/auth/signout');
  assert.equal(
    new Headers(requests[3].init.headers).get('Authorization'),
    'Bearer unadopted-session',
  );
});

test('server resume-route drift is rejected and the issued bearer is revoked', async () => {
  const requests = [];
  const savedSessions = [];
  const authority = createAuthority({
    requests,
    savedSessions,
    responses: beginResponses('github'),
  });
  await authority.begin({ apiBaseUrl, provider: 'github', resumeRoute });
  authority.enqueueResponse(
    jsonResponse({
      access_token: 'unadopted-session',
      token_type: 'bearer',
      redirect_to: '/unexpected',
      user: { user_id: 'user-1' },
    }),
  );
  authority.enqueueResponse(jsonResponse({ success: true }));

  await assert.rejects(
    authority.complete({
      kind: 'success',
      provider: 'github',
      code: 'provider-code',
      state,
    }),
    (error) => error.reasonCode === 'oauth_callback_contract_invalid',
  );
  assert.deepEqual(savedSessions, []);
  assert.equal(new URL(requests[3].url).pathname, '/api/v1/auth/signout');
});

function createAuthority({
  requests = [],
  opened = [],
  savedSessions = [],
  responses = [],
  now = () => 1_000_000,
  pendingAttemptPersistence,
  saveTrustedSession,
} = {}) {
  const queuedResponses = [...responses];
  const queuedOpenFailures = [];
  const authority = new DesktopOAuthCallbackAuthority({
    now,
    async fetch(url, init) {
      requests.push({ url, init });
      const response = queuedResponses.shift();
      if (!response) throw new Error('missing test response');
      return response;
    },
    async openExternal(url) {
      const failure = queuedOpenFailures.shift();
      if (failure) throw failure;
      opened.push(url);
    },
    saveTrustedSession:
      saveTrustedSession ??
      (async (input) => {
        savedSessions.push(input);
      }),
    normalizeResumeRoute(route) {
      return route === resumeRoute ? route : null;
    },
    ...(pendingAttemptPersistence ? { pendingAttemptPersistence } : {}),
  });
  authority.enqueueResponse = (response) => queuedResponses.push(response);
  authority.enqueueOpenFailure = (error) => queuedOpenFailures.push(error);
  return authority;
}

function createPendingAttemptPersistence(initialValue = null) {
  let value = initialValue;
  return {
    async load() {
      return value;
    },
    async save(input) {
      value = input.input;
    },
    async clear() {
      value = null;
    },
    snapshot() {
      return value;
    },
  };
}

function beginResponses(provider) {
  return [
    jsonResponse({ providers: [{ id: provider, display_name: 'Provider' }] }),
    jsonResponse({
      provider,
      authorization_url: `https://provider.test/authorize?state=${state}`,
      expires_in: 600,
    }),
  ];
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
