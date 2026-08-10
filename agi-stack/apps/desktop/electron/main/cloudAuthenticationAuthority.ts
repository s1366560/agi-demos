type TrustedCloudSession = Readonly<{
  version: 1;
  api_base_url: string;
  runtime_mode: 'cloud';
  credential_kind: 'cloud_bearer';
  credential: string;
  expires_at: string | null;
}>;

type TrustedSessionSaveInput = Readonly<{ input: TrustedCloudSession }>;

export type DesktopCloudAuthenticationDependencies = Readonly<{
  now(): number;
  randomId(): string;
  fetch(url: string, init: RequestInit): Promise<Response>;
  loadTrustedSession(): Promise<unknown>;
  saveTrustedSession(input: TrustedSessionSaveInput): Promise<void>;
  clearTrustedSession(): Promise<void>;
}>;

export type PasswordLoginInput = Readonly<{
  apiBaseUrl: string;
  username: string;
  password: string;
  trustedDevice: boolean;
}>;

export type ForcePasswordChangeInput = Readonly<{
  currentPassword: string;
  newPassword: string;
}>;

export type DeviceAuthorizationInput = Readonly<{
  apiBaseUrl: string;
  deviceAuthorizationBaseUrl: string;
  trustedDevice: boolean;
}>;

export type DeviceAuthorizationOpened = Readonly<{
  status: 'authorization_pending';
  attemptId: string;
  userCode: string;
  authorizationUrl: string;
  expiresAt: number;
  interval: number;
}>;

export type DeviceAuthorizationPollResult =
  | Readonly<{ status: 'authorization_pending'; interval: number }>
  | Readonly<{ status: 'authenticated' }>
  | Readonly<{ status: 'expired' }>;

type PendingDeviceAuthorization = Readonly<{
  attemptId: string;
  apiBaseUrl: string;
  deviceCode: string;
  expiresAt: number;
  trustedDevice: boolean;
}>;

type ParsedToken = Readonly<{
  credential: string;
  mustChangePassword: boolean;
  expiresAt: string | null;
}>;

const MAX_RESPONSE_BYTES = 1024 * 1024;
const DEVICE_ATTEMPT_ID = /^[A-Za-z0-9_-]{16,128}$/u;
const DEVICE_USER_CODE = /^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}$/u;
const LOGIN_RESPONSE_KEYS = new Set([
  'access_token',
  'token_type',
  'must_change_password',
  'session',
  'context',
]);
const SESSION_KEYS = new Set([
  'session_id',
  'auth_method',
  'expires_at',
  'trusted_device',
]);
const DEVICE_CODE_KEYS = new Set([
  'device_code',
  'user_code',
  'verification_uri',
  'verification_uri_complete',
  'expires_in',
  'interval',
]);
const DEVICE_TOKEN_KEYS = new Set(['access_token', 'token_type']);
const FORCE_PASSWORD_KEYS = new Set(['success', 'message']);

export class DesktopCloudAuthenticationAuthority {
  readonly #dependencies: DesktopCloudAuthenticationDependencies;
  #pendingDevice: PendingDeviceAuthorization | null = null;
  #persistAcrossRestart = true;

  constructor(dependencies: DesktopCloudAuthenticationDependencies) {
    this.#dependencies = dependencies;
  }

  async loginWithPassword(
    input: PasswordLoginInput,
  ): Promise<Readonly<{ status: 'authenticated' | 'password_change_required' }>> {
    const apiBaseUrl = secureOrigin(input.apiBaseUrl);
    const username = boundedString(input.username, 320, false);
    const password = boundedString(input.password, 4096, false);
    if (!apiBaseUrl || !username || !password || typeof input.trustedDevice !== 'boolean') {
      throw contractInvalid();
    }
    const body = new URLSearchParams({ username, password });
    const response = await this.#requestJson(apiBaseUrl, '/api/v1/auth/token', {
      method: 'POST',
      headers: new Headers({
        Accept: 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
      }),
      body,
    });
    const token = parseLoginToken(response.body);
    await this.#adoptToken(apiBaseUrl, token, input.trustedDevice);
    return Object.freeze({
      status: token.mustChangePassword ? 'password_change_required' : 'authenticated',
    });
  }

  async forceChangePassword(
    input: ForcePasswordChangeInput,
  ): Promise<Readonly<{ status: 'authenticated' }>> {
    const currentPassword = boundedString(input.currentPassword, 4096, false);
    const newPassword = boundedString(input.newPassword, 4096, false);
    if (!currentPassword || !newPassword) throw contractInvalid();
    const session = await this.#trustedSession();
    const response = await this.#requestJson(
      session.api_base_url,
      '/api/v1/auth/force-change-password',
      {
        method: 'POST',
        authorization: session.credential,
        body: JSON.stringify({
          old_password: currentPassword,
          new_password: newPassword,
        }),
      },
    );
    if (
      !isExactRecord(response.body, FORCE_PASSWORD_KEYS) ||
      response.body.success !== true ||
      typeof response.body.message !== 'string'
    ) {
      throw responseInvalid();
    }
    return Object.freeze({ status: 'authenticated' });
  }

  async beginDeviceAuthorization(
    input: DeviceAuthorizationInput,
  ): Promise<DeviceAuthorizationOpened> {
    const apiBaseUrl = secureOrigin(input.apiBaseUrl);
    const deviceAuthorizationBaseUrl = secureOrigin(input.deviceAuthorizationBaseUrl);
    if (!apiBaseUrl || !deviceAuthorizationBaseUrl || typeof input.trustedDevice !== 'boolean') {
      throw contractInvalid();
    }
    if (this.#pendingDevice) {
      await this.cancelDeviceAuthorization(this.#pendingDevice.attemptId);
    }
    const response = await this.#requestJson(apiBaseUrl, '/api/v1/auth/device/code', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    const code = parseDeviceCode(response.body);
    const attemptId = this.#dependencies.randomId();
    if (!DEVICE_ATTEMPT_ID.test(attemptId)) throw contractInvalid();
    const expiresAt = this.#dependencies.now() + code.expiresIn * 1000;
    this.#pendingDevice = Object.freeze({
      attemptId,
      apiBaseUrl,
      deviceCode: code.deviceCode,
      expiresAt,
      trustedDevice: input.trustedDevice,
    });
    const authorizationUrl = new URL('/device', `${deviceAuthorizationBaseUrl}/`);
    authorizationUrl.searchParams.set('user_code', code.userCode);
    return Object.freeze({
      status: 'authorization_pending',
      attemptId,
      userCode: code.userCode,
      authorizationUrl: authorizationUrl.toString(),
      expiresAt,
      interval: code.interval,
    });
  }

  async pollDeviceAuthorization(attemptId: string): Promise<DeviceAuthorizationPollResult> {
    const pending = this.#requiredPendingDevice(attemptId);
    if (pending.expiresAt <= this.#dependencies.now()) {
      this.#pendingDevice = null;
      await this.#cancelDeviceCode(pending).catch(() => undefined);
      return Object.freeze({ status: 'expired' });
    }
    const response = await this.#requestJson(
      pending.apiBaseUrl,
      '/api/v1/auth/device/token',
      {
        method: 'POST',
        body: JSON.stringify({ device_code: pending.deviceCode }),
      },
      true,
    );
    if (response.status === 428) {
      const interval = pendingDeviceInterval(response.body);
      if (interval === null) throw responseInvalid();
      return Object.freeze({ status: 'authorization_pending', interval });
    }
    if (response.status === 410) {
      this.#pendingDevice = null;
      return Object.freeze({ status: 'expired' });
    }
    if (response.status < 200 || response.status >= 300) throw requestFailed();
    const token = parseDeviceToken(response.body);
    this.#pendingDevice = null;
    await this.#adoptToken(pending.apiBaseUrl, token, pending.trustedDevice);
    return Object.freeze({ status: 'authenticated' });
  }

  async cancelDeviceAuthorization(
    attemptId: string,
  ): Promise<Readonly<{ cancelled: true }>> {
    const pending = this.#requiredPendingDevice(attemptId);
    this.#pendingDevice = null;
    await this.#cancelDeviceCode(pending);
    return Object.freeze({ cancelled: true });
  }

  async signOut(): Promise<Readonly<{ success: boolean }>> {
    let session: TrustedCloudSession | null = null;
    try {
      session = await this.#trustedSession();
    } catch {
      await this.#dependencies.clearTrustedSession();
      this.#persistAcrossRestart = false;
      return Object.freeze({ success: true });
    }
    let revoked = false;
    try {
      const response = await this.#requestJson(session.api_base_url, '/api/v1/auth/signout', {
        method: 'POST',
        authorization: session.credential,
      });
      revoked =
        isRecord(response.body) &&
        Object.keys(response.body).length === 1 &&
        response.body.success === true;
    } finally {
      await this.#dependencies.clearTrustedSession();
      this.#persistAcrossRestart = false;
    }
    return Object.freeze({ success: revoked });
  }

  async clearTransientSession(): Promise<boolean> {
    if (this.#persistAcrossRestart) return false;
    try {
      await this.#dependencies.clearTrustedSession();
      return true;
    } catch {
      return false;
    }
  }

  async #cancelDeviceCode(pending: PendingDeviceAuthorization): Promise<void> {
    const response = await this.#requestJson(
      pending.apiBaseUrl,
      '/api/v1/auth/device/cancel',
      {
        method: 'POST',
        body: JSON.stringify({ device_code: pending.deviceCode }),
      },
    );
    if (!isRecord(response.body) || response.body.success !== true) throw responseInvalid();
  }

  #requiredPendingDevice(attemptId: string): PendingDeviceAuthorization {
    if (!DEVICE_ATTEMPT_ID.test(attemptId)) throw contractInvalid();
    const pending = this.#pendingDevice;
    if (!pending || pending.attemptId !== attemptId) {
      throw new Error('cloud_auth_device_attempt_missing');
    }
    return pending;
  }

  async #adoptToken(
    apiBaseUrl: string,
    token: ParsedToken,
    trustedDevice: boolean,
  ): Promise<void> {
    await this.#dependencies.saveTrustedSession({
      input: Object.freeze({
        version: 1,
        api_base_url: apiBaseUrl,
        runtime_mode: 'cloud',
        credential_kind: 'cloud_bearer',
        credential: token.credential,
        expires_at: token.expiresAt,
      }),
    });
    this.#persistAcrossRestart = trustedDevice;
  }

  async #trustedSession(): Promise<TrustedCloudSession> {
    const value = await this.#dependencies.loadTrustedSession();
    if (!isRecord(value)) throw new Error('cloud_auth_session_missing');
    const apiBaseUrl = secureOrigin(value.api_base_url);
    if (
      value.version !== 1 ||
      !apiBaseUrl ||
      value.runtime_mode !== 'cloud' ||
      value.credential_kind !== 'cloud_bearer' ||
      typeof value.credential !== 'string' ||
      value.credential.length < 1 ||
      value.credential.length > 16 * 1024 ||
      (value.expires_at !== null && typeof value.expires_at !== 'string')
    ) {
      throw new Error('cloud_auth_session_invalid');
    }
    return Object.freeze({
      version: 1,
      api_base_url: apiBaseUrl,
      runtime_mode: 'cloud',
      credential_kind: 'cloud_bearer',
      credential: value.credential,
      expires_at: value.expires_at as string | null,
    });
  }

  async #requestJson(
    apiBaseUrl: string,
    path: string,
    init: Readonly<{
      method: 'POST';
      headers?: Headers;
      body?: string | URLSearchParams;
      authorization?: string;
    }>,
    allowExpectedDeviceStatus = false,
  ): Promise<Readonly<{ status: number; body: unknown }>> {
    const headers = new Headers(init.headers ?? { Accept: 'application/json' });
    if (!headers.has('Accept')) headers.set('Accept', 'application/json');
    if (typeof init.body === 'string') headers.set('Content-Type', 'application/json');
    if (init.authorization) headers.set('Authorization', `Bearer ${init.authorization}`);
    const response = await this.#dependencies.fetch(
      new URL(path, `${apiBaseUrl}/`).toString(),
      {
        method: init.method,
        headers,
        redirect: 'manual',
        body: init.body,
      },
    );
    const body = await boundedJson(response);
    if (!response.ok && !(allowExpectedDeviceStatus && [410, 428].includes(response.status))) {
      throw requestFailed();
    }
    return Object.freeze({ status: response.status, body });
  }
}

function parseLoginToken(value: unknown): ParsedToken {
  if (!isAllowedRecord(value, LOGIN_RESPONSE_KEYS)) throw responseInvalid();
  const parsed = parseBearer(value);
  if (typeof value.must_change_password !== 'boolean') throw responseInvalid();
  let expiresAt: string | null = null;
  if (value.session !== undefined) {
    if (!isAllowedRecord(value.session, SESSION_KEYS)) throw responseInvalid();
    if (value.session.expires_at !== null && typeof value.session.expires_at !== 'string') {
      throw responseInvalid();
    }
    expiresAt = value.session.expires_at as string | null;
  }
  return Object.freeze({
    credential: parsed.credential,
    mustChangePassword: value.must_change_password,
    expiresAt,
  });
}

function parseDeviceToken(value: unknown): ParsedToken {
  if (!isExactRecord(value, DEVICE_TOKEN_KEYS)) throw responseInvalid();
  const parsed = parseBearer(value);
  return Object.freeze({
    credential: parsed.credential,
    mustChangePassword: false,
    expiresAt: null,
  });
}

function parseBearer(value: Record<string, unknown>): Readonly<{ credential: string }> {
  if (
    typeof value.access_token !== 'string' ||
    value.access_token.length < 1 ||
    value.access_token.length > 16 * 1024 ||
    typeof value.token_type !== 'string' ||
    value.token_type.toLowerCase() !== 'bearer'
  ) {
    throw responseInvalid();
  }
  return Object.freeze({ credential: value.access_token });
}

function parseDeviceCode(value: unknown): Readonly<{
  deviceCode: string;
  userCode: string;
  expiresIn: number;
  interval: number;
}> {
  if (
    !isExactRecord(value, DEVICE_CODE_KEYS) ||
    typeof value.device_code !== 'string' ||
    value.device_code.length < 32 ||
    value.device_code.length > 256 ||
    typeof value.user_code !== 'string' ||
    !DEVICE_USER_CODE.test(value.user_code) ||
    value.verification_uri !== '/device' ||
    value.verification_uri_complete !== `/device?user_code=${value.user_code}` ||
    !integerBetween(value.expires_in, 1, 3600) ||
    !integerBetween(value.interval, 1, 60)
  ) {
    throw responseInvalid();
  }
  return Object.freeze({
    deviceCode: value.device_code,
    userCode: value.user_code,
    expiresIn: value.expires_in,
    interval: value.interval,
  });
}

function pendingDeviceInterval(value: unknown): number | null {
  if (!isRecord(value) || !isRecord(value.detail)) return null;
  if (
    value.detail.error !== 'authorization_pending' ||
    !integerBetween(value.detail.interval, 1, 60)
  ) {
    return null;
  }
  return value.detail.interval;
}

async function boundedJson(response: Response): Promise<unknown> {
  if (response.type === 'opaqueredirect' || response.status >= 300 && response.status < 400) {
    throw responseInvalid();
  }
  const reader = response.body?.getReader();
  if (!reader) return null;
  const chunks: Uint8Array[] = [];
  let bytes = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > MAX_RESPONSE_BYTES) {
        await reader.cancel();
        throw responseInvalid();
      }
      chunks.push(chunk.value);
    }
  } finally {
    reader.releaseLock();
  }
  const combined = new Uint8Array(bytes);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder().decode(combined)) as unknown;
  } catch {
    throw responseInvalid();
  }
}

function secureOrigin(value: unknown): string | null {
  if (typeof value !== 'string' || value !== value.trim() || value.length > 2048) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  const loopback = ['127.0.0.1', 'localhost', '[::1]', '::1'].includes(
    url.hostname.toLowerCase(),
  );
  if (
    (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) ||
    url.username ||
    url.password ||
    url.hash ||
    (url.pathname !== '/' && url.pathname !== '') ||
    url.search
  ) {
    return null;
  }
  return url.origin;
}

function boundedString(value: unknown, maxLength: number, allowEmpty: boolean): string | null {
  if (typeof value !== 'string' || value.length > maxLength || value !== value.trim()) return null;
  if (!allowEmpty && value.length === 0) return null;
  for (const character of value) {
    const code = character.codePointAt(0) ?? 0;
    if (code <= 0x1f || code === 0x7f) return null;
  }
  return value;
}

function integerBetween(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isSafeInteger(value) && (value as number) >= minimum && (value as number) <= maximum;
}

function isAllowedRecord(
  value: unknown,
  allowedKeys: ReadonlySet<string>,
): value is Record<string, unknown> {
  return isRecord(value) && Object.keys(value).every((key) => allowedKeys.has(key));
}

function isExactRecord(
  value: unknown,
  expectedKeys: ReadonlySet<string>,
): value is Record<string, unknown> {
  return (
    isAllowedRecord(value, expectedKeys) && Object.keys(value).length === expectedKeys.size
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function contractInvalid(): Error {
  return new Error('cloud_auth_contract_invalid');
}

function responseInvalid(): Error {
  return new Error('cloud_auth_response_invalid');
}

function requestFailed(): Error {
  return new Error('cloud_auth_request_failed');
}
