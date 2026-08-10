type DesktopInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

export type NativeCloudAuthenticationResult = Readonly<{
  status: 'authenticated' | 'password_change_required';
}>;

export type NativeDeviceAuthorizationOpened = Readonly<{
  status: 'authorization_pending';
  attemptId: string;
  userCode: string;
  authorizationUrl: string;
  expiresAt: number;
  interval: number;
}>;

export type NativeDeviceAuthorizationPollResult =
  | Readonly<{ status: 'authorization_pending'; interval: number }>
  | Readonly<{ status: 'authenticated' }>
  | Readonly<{ status: 'expired' }>;

export type NativeCloudAuthClient = Readonly<{
  loginWithPassword(input: Readonly<{
    apiBaseUrl: string;
    username: string;
    password: string;
    trustedDevice: boolean;
  }>): Promise<NativeCloudAuthenticationResult>;
  forceChangePassword(input: Readonly<{
    currentPassword: string;
    newPassword: string;
  }>): Promise<Readonly<{ status: 'authenticated' }>>;
  beginDeviceAuthorization(input: Readonly<{
    apiBaseUrl: string;
    deviceAuthorizationBaseUrl: string;
    trustedDevice: boolean;
  }>): Promise<NativeDeviceAuthorizationOpened>;
  pollDeviceAuthorization(attemptId: string): Promise<NativeDeviceAuthorizationPollResult>;
  cancelDeviceAuthorization(attemptId: string): Promise<Readonly<{ cancelled: true }>>;
  signOut(): Promise<Readonly<{ success: boolean }>>;
}>;

const ATTEMPT_ID = /^[A-Za-z0-9_-]{16,128}$/u;
const USER_CODE = /^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{8}$/u;

export function desktopNativeCloudAuthClient(): NativeCloudAuthClient | null {
  if (typeof window === 'undefined') return null;
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke as DesktopInvoke | undefined;
  if (!invoke) return null;
  return Object.freeze({
    async loginWithPassword(input) {
      return decodeAuthenticationResult(await invoke('cloud_auth_password', input));
    },
    async forceChangePassword(input) {
      const result = decodeAuthenticationResult(
        await invoke('cloud_auth_force_password_change', input),
      );
      if (result.status !== 'authenticated') throw resultInvalid();
      return Object.freeze({ status: 'authenticated' as const });
    },
    async beginDeviceAuthorization(input) {
      return decodeDeviceAuthorizationOpened(
        await invoke('cloud_auth_device_begin', input),
      );
    },
    async pollDeviceAuthorization(attemptId) {
      return decodeDevicePollResult(
        await invoke('cloud_auth_device_poll', { attemptId }),
      );
    },
    async cancelDeviceAuthorization(attemptId) {
      const value = await invoke('cloud_auth_device_cancel', { attemptId });
      if (!isExactRecord(value, new Set(['cancelled'])) || value.cancelled !== true) {
        throw resultInvalid();
      }
      return Object.freeze({ cancelled: true });
    },
    async signOut() {
      const value = await invoke('cloud_auth_signout');
      if (!isExactRecord(value, new Set(['success'])) || typeof value.success !== 'boolean') {
        throw resultInvalid();
      }
      return Object.freeze({ success: value.success });
    },
  });
}

function decodeAuthenticationResult(value: unknown): NativeCloudAuthenticationResult {
  if (
    !isExactRecord(value, new Set(['status'])) ||
    (value.status !== 'authenticated' && value.status !== 'password_change_required')
  ) {
    throw resultInvalid();
  }
  return Object.freeze({ status: value.status });
}

function decodeDeviceAuthorizationOpened(value: unknown): NativeDeviceAuthorizationOpened {
  if (
    !isExactRecord(
      value,
      new Set([
        'status',
        'attemptId',
        'userCode',
        'authorizationUrl',
        'expiresAt',
        'interval',
      ]),
    ) ||
    value.status !== 'authorization_pending' ||
    typeof value.attemptId !== 'string' ||
    !ATTEMPT_ID.test(value.attemptId) ||
    typeof value.userCode !== 'string' ||
    !USER_CODE.test(value.userCode) ||
    secureWebUrl(value.authorizationUrl) === null ||
    !Number.isSafeInteger(value.expiresAt) ||
    (value.expiresAt as number) <= 0 ||
    !integerBetween(value.interval, 1, 60)
  ) {
    throw resultInvalid();
  }
  return Object.freeze({
    status: 'authorization_pending',
    attemptId: value.attemptId,
    userCode: value.userCode,
    authorizationUrl: value.authorizationUrl as string,
    expiresAt: value.expiresAt as number,
    interval: value.interval,
  });
}

function decodeDevicePollResult(value: unknown): NativeDeviceAuthorizationPollResult {
  if (!isRecord(value)) throw resultInvalid();
  if (
    value.status === 'authorization_pending' &&
    isExactRecord(value, new Set(['status', 'interval'])) &&
    integerBetween(value.interval, 1, 60)
  ) {
    return Object.freeze({ status: 'authorization_pending', interval: value.interval });
  }
  if (
    (value.status === 'authenticated' || value.status === 'expired') &&
    isExactRecord(value, new Set(['status']))
  ) {
    return Object.freeze({ status: value.status });
  }
  throw resultInvalid();
}

function secureWebUrl(value: unknown): URL | null {
  if (typeof value !== 'string' || value.length > 2048) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  const loopback = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(
    url.hostname.toLowerCase(),
  );
  if (
    (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) ||
    url.username ||
    url.password ||
    url.hash
  ) {
    return null;
  }
  return url;
}

function integerBetween(value: unknown, minimum: number, maximum: number): value is number {
  return Number.isSafeInteger(value) && (value as number) >= minimum && (value as number) <= maximum;
}

function isExactRecord(
  value: unknown,
  keys: ReadonlySet<string>,
): value is Record<string, unknown> {
  return (
    isRecord(value) &&
    Object.keys(value).length === keys.size &&
    Object.keys(value).every((key) => keys.has(key))
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function resultInvalid(): Error {
  return new Error('cloud_auth_result_invalid');
}
