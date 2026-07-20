import type { RuntimeMode } from '../types';

type TauriInvoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

export type NativeTrustedCredentialKind = 'cloud_bearer' | 'local_session_reference';

export type NativeTrustedSession = {
  version: 1;
  api_base_url: string;
  runtime_mode: RuntimeMode;
  credential_kind: NativeTrustedCredentialKind;
  credential: string;
  expires_at: string | null;
};

const trustedSessionKeys = new Set([
  'version',
  'api_base_url',
  'runtime_mode',
  'credential_kind',
  'credential',
  'expires_at',
]);

function desktopInvoke(): TauriInvoke | null {
  return window.__TAURI__?.core?.invoke ?? null;
}

function requireDesktopInvoke(): TauriInvoke {
  const invoke = desktopInvoke();
  if (!invoke) throw new Error('Trusted sessions require the Tauri desktop shell.');
  return invoke;
}

export function hasNativeTrustedSessionBroker(): boolean {
  return desktopInvoke() !== null;
}

export function decodeNativeTrustedSession(value: unknown): NativeTrustedSession | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (Object.keys(record).some((key) => !trustedSessionKeys.has(key))) return null;
  if (record.version !== 1) return null;
  if (typeof record.api_base_url !== 'string' || !record.api_base_url.trim()) return null;
  if (record.runtime_mode !== 'cloud' && record.runtime_mode !== 'local') return null;
  if (
    record.credential_kind !== 'cloud_bearer' &&
    record.credential_kind !== 'local_session_reference'
  ) {
    return null;
  }
  if (typeof record.credential !== 'string' || !record.credential.trim()) return null;
  if (
    record.expires_at !== undefined &&
    record.expires_at !== null &&
    typeof record.expires_at !== 'string'
  ) {
    return null;
  }

  return {
    version: 1,
    api_base_url: record.api_base_url.trim(),
    runtime_mode: record.runtime_mode,
    credential_kind: record.credential_kind,
    credential: record.credential,
    expires_at: typeof record.expires_at === 'string' ? record.expires_at : null,
  };
}

export async function loadNativeTrustedSession(): Promise<NativeTrustedSession | null> {
  const invoke = requireDesktopInvoke();
  const value = await invoke('trusted_session_load');
  if (value === null || value === undefined) return null;
  const session = decodeNativeTrustedSession(value);
  if (!session) {
    await clearNativeTrustedSession();
    throw new Error('The trusted desktop session record is invalid.');
  }
  return session;
}

export async function saveNativeTrustedSession(session: NativeTrustedSession): Promise<void> {
  const invoke = requireDesktopInvoke();
  await invoke('trusted_session_save', { input: session });
}

export async function clearNativeTrustedSession(): Promise<void> {
  const invoke = requireDesktopInvoke();
  await invoke('trusted_session_clear');
}

function requireLocalTrustedSession(session: NativeTrustedSession): NativeTrustedSession {
  if (
    session.runtime_mode !== 'local' ||
    session.credential_kind !== 'local_session_reference'
  ) {
    throw new Error('The local trusted desktop session record is invalid.');
  }
  return session;
}

export async function loadLocalTrustedSession(): Promise<NativeTrustedSession | null> {
  const invoke = requireDesktopInvoke();
  const value = await invoke('local_trusted_session_load');
  if (value === null || value === undefined) return null;
  const session = decodeNativeTrustedSession(value);
  if (!session) {
    await clearLocalTrustedSession();
    throw new Error('The local trusted desktop session record is invalid.');
  }
  return requireLocalTrustedSession(session);
}

export async function saveLocalTrustedSession(session: NativeTrustedSession): Promise<void> {
  const invoke = requireDesktopInvoke();
  await invoke('local_trusted_session_save', { input: requireLocalTrustedSession(session) });
}

export async function clearLocalTrustedSession(): Promise<void> {
  const invoke = requireDesktopInvoke();
  await invoke('local_trusted_session_clear');
}
