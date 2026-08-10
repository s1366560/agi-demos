type DesktopInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

const AUTHORIZATION_OPENED_KEYS = new Set(['status', 'provider', 'expiresAt']);
const PENDING_AUTHORIZATION_KEYS = new Set(['status', 'provider', 'expiresAt']);
const EMPTY_AUTHORIZATION_KEYS = new Set(['status']);
const AUTHENTICATED_EVENT_KEYS = new Set(['status', 'provider', 'resumeRoute']);
const FAILED_EVENT_KEYS = new Set(['status', 'reasonCode']);
const PROVIDER_KEYS = new Set(['id', 'displayName']);

export type NativeOAuthProvider = Readonly<{
  id: string;
  displayName: string;
}>;

export type NativeOAuthListProvidersRequest = Readonly<{
  apiBaseUrl: string;
}>;

export type NativeOAuthBeginRequest = Readonly<{
  apiBaseUrl: string;
  provider: string;
  resumeRoute: string;
}>;

export type NativeOAuthAuthorizationOpened = Readonly<{
  status: 'authorization_opened';
  provider: string;
  expiresAt: number;
}>;

export type NativeOAuthPendingAuthorization =
  | Readonly<{
      status: 'pending';
      provider: string;
      expiresAt: number;
    }>
  | Readonly<{ status: 'empty' }>;

export type NativeOAuthSessionEvent =
  | Readonly<{
      status: 'authenticated';
      provider: string;
      resumeRoute: string;
    }>
  | Readonly<{
      status: 'failed';
      reasonCode: string;
    }>;

export type NativeOAuthClient = Readonly<{
  listProviders(request: NativeOAuthListProvidersRequest): Promise<readonly NativeOAuthProvider[]>;
  begin(request: NativeOAuthBeginRequest): Promise<NativeOAuthAuthorizationOpened>;
  restore(): Promise<NativeOAuthPendingAuthorization>;
  cancel(): Promise<void>;
  subscribe(listener: (event: NativeOAuthSessionEvent) => void): () => void;
}>;

export function decodeNativeOAuthSessionEvent(value: unknown): NativeOAuthSessionEvent | null {
  if (!isRecord(value)) return null;
  if (value.status === 'authenticated') {
    if (!hasExactKeys(value, AUTHENTICATED_EVENT_KEYS)) return null;
    const provider = protocolToken(value.provider, 128);
    const resumeRoute = canonicalPathCandidate(value.resumeRoute);
    if (!provider || !resumeRoute) return null;
    return Object.freeze({ status: 'authenticated', provider, resumeRoute });
  }
  if (value.status === 'failed') {
    if (!hasExactKeys(value, FAILED_EVENT_KEYS)) return null;
    const reasonCode = protocolToken(value.reasonCode, 128, '_');
    if (!reasonCode) return null;
    return Object.freeze({ status: 'failed', reasonCode });
  }
  return null;
}

export function desktopNativeOAuthClient(): NativeOAuthClient | null {
  if (typeof window === 'undefined') return null;
  const invoke = window.__MEMSTACK_DESKTOP__?.core?.invoke as DesktopInvoke | undefined;
  const subscribeToNativeEvent = window.__MEMSTACK_DESKTOP__?.events?.onOAuthSessionChanged;
  if (!invoke) return null;

  return Object.freeze({
    async listProviders(
      request: NativeOAuthListProvidersRequest,
    ): Promise<readonly NativeOAuthProvider[]> {
      const value = await invoke('oauth_list_providers', request);
      const providers = decodeProviders(value);
      if (!providers) throw new Error('oauth_provider_list_contract_invalid');
      return providers;
    },
    async begin(request: NativeOAuthBeginRequest): Promise<NativeOAuthAuthorizationOpened> {
      const value = await invoke('oauth_begin_authorization', request);
      const result = decodeAuthorizationOpened(value);
      if (!result) throw new Error('oauth_begin_authorization_contract_invalid');
      return result;
    },
    async restore(): Promise<NativeOAuthPendingAuthorization> {
      const value = await invoke('oauth_restore_authorization');
      const result = decodePendingAuthorization(value);
      if (!result) throw new Error('oauth_pending_authorization_contract_invalid');
      return result;
    },
    async cancel(): Promise<void> {
      await invoke('oauth_cancel_authorization');
    },
    subscribe(listener: (event: NativeOAuthSessionEvent) => void): () => void {
      if (typeof listener !== 'function') {
        throw new Error('oauth_session_listener_invalid');
      }
      if (!subscribeToNativeEvent) {
        throw new Error('oauth_session_event_unavailable');
      }
      return subscribeToNativeEvent((value: unknown): void => {
        listener(
          decodeNativeOAuthSessionEvent(value) ??
            Object.freeze({
              status: 'failed',
              reasonCode: 'oauth_session_event_contract_invalid',
            }),
        );
      });
    },
  });
}

function decodeProviders(value: unknown): readonly NativeOAuthProvider[] | null {
  if (!Array.isArray(value)) return null;
  const providers: NativeOAuthProvider[] = [];
  const providerIds = new Set<string>();
  for (const candidate of value) {
    if (!isRecord(candidate) || !hasExactKeys(candidate, PROVIDER_KEYS)) return null;
    const id = protocolToken(candidate.id, 128);
    const displayName = boundedDisplayName(candidate.displayName);
    if (!id || !displayName || providerIds.has(id)) return null;
    providerIds.add(id);
    providers.push(Object.freeze({ id, displayName }));
  }
  return Object.freeze(providers);
}

function decodeAuthorizationOpened(value: unknown): NativeOAuthAuthorizationOpened | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, AUTHORIZATION_OPENED_KEYS) ||
    value.status !== 'authorization_opened'
  ) {
    return null;
  }
  const provider = protocolToken(value.provider, 128);
  if (!provider || !Number.isSafeInteger(value.expiresAt) || (value.expiresAt as number) <= 0) {
    return null;
  }
  return Object.freeze({
    status: 'authorization_opened',
    provider,
    expiresAt: value.expiresAt as number,
  });
}

function decodePendingAuthorization(value: unknown): NativeOAuthPendingAuthorization | null {
  if (!isRecord(value)) return null;
  if (value.status === 'empty') {
    return hasExactKeys(value, EMPTY_AUTHORIZATION_KEYS)
      ? Object.freeze({ status: 'empty' })
      : null;
  }
  if (
    value.status !== 'pending' ||
    !hasExactKeys(value, PENDING_AUTHORIZATION_KEYS)
  ) {
    return null;
  }
  const provider = protocolToken(value.provider, 128);
  if (!provider || !Number.isSafeInteger(value.expiresAt) || (value.expiresAt as number) <= 0) {
    return null;
  }
  return Object.freeze({
    status: 'pending',
    provider,
    expiresAt: value.expiresAt as number,
  });
}

function canonicalPathCandidate(value: unknown): string | null {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 2048 ||
    !value.startsWith('/') ||
    value.startsWith('//') ||
    hasControlCharacter(value)
  ) {
    return null;
  }
  return value;
}

function boundedDisplayName(value: unknown): string | null {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 128 ||
    value !== value.trim() ||
    hasControlCharacter(value)
  ) {
    return null;
  }
  return value;
}

function protocolToken(value: unknown, maxLength: number, extraCharacter = '-'): string | null {
  if (typeof value !== 'string' || value.length === 0 || value.length > maxLength) return null;
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    const isDigit = codePoint !== undefined && codePoint >= 48 && codePoint <= 57;
    const isLowercase = codePoint !== undefined && codePoint >= 97 && codePoint <= 122;
    if (!isDigit && !isLowercase && character !== extraCharacter) return null;
  }
  return value;
}

function hasControlCharacter(value: string): boolean {
  for (const character of value) {
    const codePoint = character.codePointAt(0);
    if (codePoint !== undefined && (codePoint < 32 || codePoint === 127)) return true;
  }
  return false;
}

function hasExactKeys(value: Record<string, unknown>, keys: ReadonlySet<string>): boolean {
  const actualKeys = Object.keys(value);
  return actualKeys.length === keys.size && actualKeys.every((key) => keys.has(key));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
