import type { OAuthCallbackDeepLink } from './oauthDeepLinkPolicy';

type TrustedCloudSessionSaveInput = Readonly<{
  input: Readonly<{
    version: 1;
    api_base_url: string;
    runtime_mode: 'cloud';
    credential_kind: 'cloud_bearer';
    credential: string;
    expires_at: null;
  }>;
}>;

export type DesktopOAuthPendingAttemptRecord = Readonly<{
  version: 1;
  api_base_url: string;
  provider: string;
  resume_route: string;
  state: string;
  expires_at: number;
}>;

export type DesktopOAuthPendingAttemptPersistence = Readonly<{
  load(): Promise<unknown>;
  save(input: Readonly<{ input: DesktopOAuthPendingAttemptRecord }>): Promise<void>;
  clear(): Promise<void>;
}>;

export type DesktopOAuthCallbackAuthorityDependencies = Readonly<{
  now(): number;
  fetch(url: string, init: RequestInit): Promise<Response>;
  openExternal(url: string): Promise<void>;
  saveTrustedSession(input: TrustedCloudSessionSaveInput): Promise<void>;
  normalizeResumeRoute(route: string): string | null;
  pendingAttemptPersistence?: DesktopOAuthPendingAttemptPersistence;
}>;

export type DesktopOAuthBeginInput = Readonly<{
  apiBaseUrl: string;
  provider: string;
  resumeRoute: string;
}>;

export type DesktopOAuthListProvidersInput = Readonly<{
  apiBaseUrl: string;
}>;

export type DesktopOAuthProvider = Readonly<{
  id: string;
  displayName: string;
}>;

export type DesktopOAuthBeginResult = Readonly<{
  status: 'authorization_opened';
  provider: string;
  expiresAt: number;
}>;

export type DesktopOAuthPendingAttemptState =
  | Readonly<{
      status: 'pending';
      provider: string;
      expiresAt: number;
    }>
  | Readonly<{ status: 'empty' }>;

export type DesktopOAuthCompletionResult =
  | Readonly<{
      status: 'authenticated';
      provider: string;
      resumeRoute: string;
    }>
  | Readonly<{
      status: 'failed';
      provider: string;
      reasonCode: string;
      resumeRoute: null;
    }>;

export type DesktopOAuthCallbackAuthorityReasonCode =
  | 'oauth_authorization_contract_invalid'
  | 'oauth_authorization_open_failed'
  | 'oauth_callback_contract_invalid'
  | 'oauth_callback_exchange_failed'
  | 'oauth_callback_pending_contract_invalid'
  | 'oauth_callback_pending_expired'
  | 'oauth_callback_pending_mismatch'
  | 'oauth_callback_pending_missing'
  | 'oauth_callback_pending_persistence_unavailable'
  | 'oauth_callback_vault_unavailable';

export class DesktopOAuthCallbackAuthorityError extends Error {
  readonly reasonCode: DesktopOAuthCallbackAuthorityReasonCode;

  constructor(reasonCode: DesktopOAuthCallbackAuthorityReasonCode) {
    super(reasonCode);
    this.name = 'DesktopOAuthCallbackAuthorityError';
    this.reasonCode = reasonCode;
  }
}

type PendingOAuthAttempt = Readonly<{
  apiBaseUrl: string;
  provider: string;
  resumeRoute: string;
  state: string;
  expiresAt: number;
}>;

const PROVIDER_ID = /^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/u;
const OAUTH_STATE = /^[A-Za-z0-9_-]{43}$/u;
const PROVIDERS_RESPONSE_KEYS = new Set(['providers']);
const PROVIDER_KEYS = new Set(['id', 'display_name']);
const AUTHORIZATION_RESPONSE_KEYS = new Set([
  'provider',
  'authorization_url',
  'expires_in',
]);
const CALLBACK_RESPONSE_KEYS = new Set([
  'access_token',
  'token_type',
  'redirect_to',
  'user',
]);
const PENDING_ATTEMPT_RECORD_KEYS = new Set([
  'version',
  'api_base_url',
  'provider',
  'resume_route',
  'state',
  'expires_at',
]);
const MAX_RESPONSE_BYTES = 1024 * 1024;
const MAX_AUTHORIZATION_TTL_SECONDS = 3600;

export class DesktopOAuthCallbackAuthority {
  readonly #dependencies: DesktopOAuthCallbackAuthorityDependencies;
  #pending: PendingOAuthAttempt | null = null;

  constructor(dependencies: DesktopOAuthCallbackAuthorityDependencies) {
    this.#dependencies = dependencies;
  }

  async listProviders(
    input: DesktopOAuthListProvidersInput,
  ): Promise<readonly DesktopOAuthProvider[]> {
    const apiBaseUrl = secureOrigin(input.apiBaseUrl);
    if (!apiBaseUrl) throw authorizationContractInvalid();
    const response = await this.#requestJson(apiBaseUrl, '/api/v1/auth/oauth/providers', {
      method: 'GET',
    });
    return configuredProviders(response);
  }

  async begin(input: DesktopOAuthBeginInput): Promise<DesktopOAuthBeginResult> {
    const apiBaseUrl = secureOrigin(input.apiBaseUrl);
    const provider = providerId(input.provider);
    const resumeRoute = this.#dependencies.normalizeResumeRoute(input.resumeRoute);
    if (!apiBaseUrl || !provider || !resumeRoute) throw authorizationContractInvalid();

    const providers = await this.listProviders({ apiBaseUrl });
    if (!providers.some((candidate) => candidate.id === provider)) {
      throw authorizationContractInvalid();
    }

    const authorization = await this.#requestJson(
      apiBaseUrl,
      `/api/v1/auth/oauth/${encodeURIComponent(provider)}/authorize`,
      {
        method: 'POST',
        body: JSON.stringify({
          redirect_to: resumeRoute,
          callback_surface: 'desktop',
        }),
      },
    );
    const parsed = parseAuthorizationResponse(authorization, provider);
    const expiresAt = this.#dependencies.now() + parsed.expiresIn * 1000;
    const pending = Object.freeze({
      apiBaseUrl,
      provider,
      resumeRoute,
      state: parsed.state,
      expiresAt,
    });
    await this.#savePending(pending);
    try {
      await this.#dependencies.openExternal(parsed.authorizationUrl);
    } catch {
      await this.#clearPending();
      throw new DesktopOAuthCallbackAuthorityError('oauth_authorization_open_failed');
    }
    return Object.freeze({
      status: 'authorization_opened',
      provider,
      expiresAt,
    });
  }

  async restore(): Promise<DesktopOAuthPendingAttemptState> {
    const pending = await this.#restorePending();
    if (!pending) return Object.freeze({ status: 'empty' });
    if (pending.expiresAt <= this.#dependencies.now()) {
      await this.#clearPending();
      return Object.freeze({ status: 'empty' });
    }
    return Object.freeze({
      status: 'pending',
      provider: pending.provider,
      expiresAt: pending.expiresAt,
    });
  }

  async cancel(): Promise<void> {
    await this.#clearPending();
  }

  async complete(callback: OAuthCallbackDeepLink): Promise<DesktopOAuthCompletionResult> {
    const pending = this.#pending ?? (await this.#restorePending());
    if (!pending) {
      throw new DesktopOAuthCallbackAuthorityError('oauth_callback_pending_missing');
    }
    if (pending.expiresAt <= this.#dependencies.now()) {
      await this.#clearPending();
      throw new DesktopOAuthCallbackAuthorityError('oauth_callback_pending_expired');
    }
    if (callback.provider !== pending.provider || callback.state !== pending.state) {
      await this.#clearPending();
      throw new DesktopOAuthCallbackAuthorityError('oauth_callback_pending_mismatch');
    }
    await this.#clearPending();
    if (callback.kind === 'provider_error') {
      return Object.freeze({
        status: 'failed',
        provider: pending.provider,
        reasonCode: `oauth_provider_${callback.error}`,
        resumeRoute: null,
      });
    }

    let response: unknown;
    try {
      response = await this.#requestJson(
        pending.apiBaseUrl,
        `/api/v1/auth/oauth/${encodeURIComponent(pending.provider)}/callback`,
        {
          method: 'POST',
          body: JSON.stringify({ code: callback.code, state: callback.state }),
        },
      );
    } catch (error) {
      if (error instanceof DesktopOAuthCallbackAuthorityError) throw error;
      throw new DesktopOAuthCallbackAuthorityError('oauth_callback_exchange_failed');
    }
    const session = parseCallbackResponse(response);
    const normalizedResumeRoute = this.#dependencies.normalizeResumeRoute(session.redirectTo);
    if (!normalizedResumeRoute || normalizedResumeRoute !== pending.resumeRoute) {
      await this.#revokeUnadoptedSession(pending.apiBaseUrl, session.accessToken);
      throw new DesktopOAuthCallbackAuthorityError('oauth_callback_contract_invalid');
    }

    try {
      await this.#dependencies.saveTrustedSession({
        input: Object.freeze({
          version: 1,
          api_base_url: pending.apiBaseUrl,
          runtime_mode: 'cloud',
          credential_kind: 'cloud_bearer',
          credential: session.accessToken,
          expires_at: null,
        }),
      });
    } catch {
      await this.#revokeUnadoptedSession(pending.apiBaseUrl, session.accessToken);
      throw new DesktopOAuthCallbackAuthorityError('oauth_callback_vault_unavailable');
    }
    return Object.freeze({
      status: 'authenticated',
      provider: pending.provider,
      resumeRoute: normalizedResumeRoute,
    });
  }

  async #savePending(pending: PendingOAuthAttempt): Promise<void> {
    const persistence = this.#dependencies.pendingAttemptPersistence;
    this.#pending = null;
    if (persistence) {
      try {
        await persistence.save({ input: pendingAttemptRecord(pending) });
      } catch {
        try {
          await persistence.clear();
        } catch {
          // Both failures collapse into the same fail-closed authority result.
        }
        throw pendingPersistenceUnavailable();
      }
    }
    this.#pending = pending;
  }

  async #restorePending(): Promise<PendingOAuthAttempt | null> {
    if (this.#pending) return this.#pending;
    const persistence = this.#dependencies.pendingAttemptPersistence;
    if (!persistence) return null;
    let persisted: unknown;
    try {
      persisted = await persistence.load();
    } catch {
      throw pendingPersistenceUnavailable();
    }
    if (persisted === null || persisted === undefined) return null;
    const pending = parsePendingAttemptRecord(
      persisted,
      this.#dependencies.normalizeResumeRoute,
    );
    if (!pending) {
      await this.#clearPending();
      throw new DesktopOAuthCallbackAuthorityError(
        'oauth_callback_pending_contract_invalid',
      );
    }
    this.#pending = pending;
    return pending;
  }

  async #clearPending(): Promise<void> {
    this.#pending = null;
    const persistence = this.#dependencies.pendingAttemptPersistence;
    if (!persistence) return;
    try {
      await persistence.clear();
    } catch {
      throw pendingPersistenceUnavailable();
    }
  }

  async #requestJson(
    apiBaseUrl: string,
    path: string,
    init: Readonly<{ method: 'GET' | 'POST'; body?: string; authorization?: string }>,
  ): Promise<unknown> {
    const headers = new Headers({ Accept: 'application/json' });
    if (init.body !== undefined) headers.set('Content-Type', 'application/json');
    if (init.authorization) headers.set('Authorization', `Bearer ${init.authorization}`);
    const response = await this.#dependencies.fetch(new URL(path, `${apiBaseUrl}/`).toString(), {
      method: init.method,
      headers,
      redirect: 'manual',
      body: init.body,
    });
    const body = await boundedJson(response);
    if (!response.ok) throw new DesktopOAuthCallbackAuthorityError('oauth_callback_exchange_failed');
    return body;
  }

  async #revokeUnadoptedSession(apiBaseUrl: string, credential: string): Promise<void> {
    try {
      await this.#requestJson(apiBaseUrl, '/api/v1/auth/signout', {
        method: 'POST',
        authorization: credential,
      });
    } catch {
      // The issued session remains outside renderer state and expires server-side.
    }
  }
}

function pendingAttemptRecord(pending: PendingOAuthAttempt): DesktopOAuthPendingAttemptRecord {
  return Object.freeze({
    version: 1,
    api_base_url: pending.apiBaseUrl,
    provider: pending.provider,
    resume_route: pending.resumeRoute,
    state: pending.state,
    expires_at: pending.expiresAt,
  });
}

function parsePendingAttemptRecord(
  input: unknown,
  normalizeResumeRoute: (route: string) => string | null,
): PendingOAuthAttempt | null {
  if (
    !isExactRecord(input, PENDING_ATTEMPT_RECORD_KEYS) ||
    input.version !== 1 ||
    typeof input.resume_route !== 'string' ||
    typeof input.state !== 'string' ||
    !OAUTH_STATE.test(input.state) ||
    !positiveSafeInteger(input.expires_at)
  ) {
    return null;
  }
  const apiBaseUrl = secureOrigin(input.api_base_url);
  const provider = providerId(input.provider);
  let resumeRoute: string | null;
  try {
    resumeRoute = normalizeResumeRoute(input.resume_route);
  } catch {
    return null;
  }
  if (!apiBaseUrl || !provider || resumeRoute !== input.resume_route) return null;
  return Object.freeze({
    apiBaseUrl,
    provider,
    resumeRoute,
    state: input.state,
    expiresAt: input.expires_at,
  });
}

function configuredProviders(input: unknown): readonly DesktopOAuthProvider[] {
  if (!isExactRecord(input, PROVIDERS_RESPONSE_KEYS) || !Array.isArray(input.providers)) {
    throw authorizationContractInvalid();
  }
  const providers = input.providers.map((value) => {
    if (!isExactRecord(value, PROVIDER_KEYS)) throw authorizationContractInvalid();
    const id = providerId(value.id);
    const displayName = boundedDisplayName(value.display_name);
    if (!id || !displayName) {
      throw authorizationContractInvalid();
    }
    return Object.freeze({ id, displayName });
  });
  if (new Set(providers.map(({ id }) => id)).size !== providers.length) {
    throw authorizationContractInvalid();
  }
  return Object.freeze(providers);
}

function parseAuthorizationResponse(
  input: unknown,
  provider: string,
): Readonly<{ authorizationUrl: string; state: string; expiresIn: number }> {
  if (
    !isExactRecord(input, AUTHORIZATION_RESPONSE_KEYS) ||
    input.provider !== provider ||
    typeof input.authorization_url !== 'string' ||
    !positiveSafeInteger(input.expires_in) ||
    input.expires_in > MAX_AUTHORIZATION_TTL_SECONDS
  ) {
    throw authorizationContractInvalid();
  }
  const authorizationUrl = secureWebUrl(input.authorization_url);
  if (!authorizationUrl) throw authorizationContractInvalid();
  const stateValues = authorizationUrl.searchParams.getAll('state');
  const state = stateValues.length === 1 ? stateValues[0] : null;
  if (!state || !OAUTH_STATE.test(state)) throw authorizationContractInvalid();
  return Object.freeze({
    authorizationUrl: authorizationUrl.toString(),
    state,
    expiresIn: input.expires_in,
  });
}

function parseCallbackResponse(
  input: unknown,
): Readonly<{ accessToken: string; redirectTo: string }> {
  if (
    !isExactRecord(input, CALLBACK_RESPONSE_KEYS) ||
    typeof input.access_token !== 'string' ||
    !input.access_token ||
    input.access_token !== input.access_token.trim() ||
    hasControlCharacter(input.access_token) ||
    input.token_type !== 'bearer' ||
    typeof input.redirect_to !== 'string' ||
    !isRecord(input.user)
  ) {
    throw new DesktopOAuthCallbackAuthorityError('oauth_callback_contract_invalid');
  }
  return Object.freeze({ accessToken: input.access_token, redirectTo: input.redirect_to });
}

async function boundedJson(response: Response): Promise<unknown> {
  const contentType = (response.headers.get('content-type') ?? '').toLowerCase();
  if (!contentType.includes('application/json')) {
    await response.body?.cancel().catch(() => undefined);
    throw new DesktopOAuthCallbackAuthorityError('oauth_callback_contract_invalid');
  }
  const declaredLength = response.headers.get('content-length');
  if (declaredLength !== null) {
    const parsed = Number(declaredLength);
    if (!/^\d+$/u.test(declaredLength) || !Number.isSafeInteger(parsed) || parsed > MAX_RESPONSE_BYTES) {
      await response.body?.cancel().catch(() => undefined);
      throw new DesktopOAuthCallbackAuthorityError('oauth_callback_contract_invalid');
    }
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw new DesktopOAuthCallbackAuthorityError('oauth_callback_contract_invalid');
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new DesktopOAuthCallbackAuthorityError('oauth_callback_contract_invalid');
  }
}

function secureOrigin(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const url = secureWebUrl(value);
  if (!url || url.pathname !== '/' || url.search || url.hash) return null;
  return url.origin;
}

function secureWebUrl(value: string): URL | null {
  try {
    const url = new URL(value);
    const loopback =
      url.protocol === 'http:' &&
      ['localhost', '127.0.0.1', '::1', '[::1]'].includes(url.hostname.toLowerCase());
    if ((url.protocol !== 'https:' && !loopback) || url.username || url.password || url.hash) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

function providerId(value: unknown): string | null {
  return typeof value === 'string' && PROVIDER_ID.test(value) ? value : null;
}

function boundedDisplayName(value: unknown): string | null {
  return typeof value === 'string' &&
    value.length > 0 &&
    value.length <= 128 &&
    value === value.trim() &&
    !hasControlCharacter(value)
    ? value
    : null;
}

function positiveSafeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

function isExactRecord(value: unknown, keys: ReadonlySet<string>): value is Record<string, unknown> {
  return isRecord(value) && Object.keys(value).every((key) => keys.has(key));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function hasControlCharacter(value: string): boolean {
  return [...value].some((character) => {
    const code = character.charCodeAt(0);
    return code <= 0x1f || code === 0x7f;
  });
}

function authorizationContractInvalid(): DesktopOAuthCallbackAuthorityError {
  return new DesktopOAuthCallbackAuthorityError('oauth_authorization_contract_invalid');
}

function pendingPersistenceUnavailable(): DesktopOAuthCallbackAuthorityError {
  return new DesktopOAuthCallbackAuthorityError(
    'oauth_callback_pending_persistence_unavailable',
  );
}
