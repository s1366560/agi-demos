import type { RuntimeMode } from '../../types';

export type WorkspaceSsoAction =
  | { kind: 'local_session'; trustedDevice: boolean }
  | { kind: 'workspace_sso' }
  | { kind: 'unavailable'; capability: 'local_workspace' | 'workspace_sso' };

export type WorkspaceContinueLabelKey = 'login.localWorkspace' | 'login.workspaceSso';

export type LoginCredentialValidation = 'invalid_credentials' | null;

export function validateLoginCredentials(
  email: string,
  password: string,
): LoginCredentialValidation {
  return email.trim().includes('@') && password.length >= 6 ? null : 'invalid_credentials';
}

export function resolveWorkspaceSsoAction(
  mode: RuntimeMode,
  localReady: boolean,
): WorkspaceSsoAction {
  if (mode !== 'local') return { kind: 'workspace_sso' };
  if (!localReady) return { kind: 'unavailable', capability: 'local_workspace' };
  return { kind: 'local_session', trustedDevice: true };
}

export function resolveWorkspaceContinueLabelKey(mode: RuntimeMode): WorkspaceContinueLabelKey {
  return mode === 'local' ? 'login.localWorkspace' : 'login.workspaceSso';
}

export function resolveDeviceAuthorizationUrl(
  apiBaseUrl: string,
  verificationUriComplete: string,
  expectedUserCode: string,
): string | null {
  try {
    if (
      !expectedUserCode ||
      /\s/u.test(apiBaseUrl) ||
      /\s/u.test(verificationUriComplete)
    ) {
      return null;
    }
    const apiBase = new URL(apiBaseUrl);
    const resolved = new URL(verificationUriComplete, apiBaseUrl);
    if (!isAllowedDeviceAuthorizationTransport(apiBase)) return null;
    if (
      rawAuthorityHasUserInfo(apiBaseUrl) ||
      apiBase.username ||
      apiBase.password ||
      apiBase.hash
    ) {
      return null;
    }
    if (!isAllowedDeviceAuthorizationTransport(resolved)) return null;
    if (resolved.origin !== apiBase.origin) return null;
    if (
      rawAuthorityHasUserInfo(verificationUriComplete) ||
      resolved.username ||
      resolved.password ||
      resolved.hash
    ) {
      return null;
    }
    if (resolved.pathname !== '/device') return null;
    const queryEntries = Array.from(resolved.searchParams.entries());
    if (queryEntries.length !== 1) return null;
    const [key, userCode] = queryEntries[0];
    if (key !== 'user_code' || !userCode || userCode !== expectedUserCode) return null;
    return resolved.toString();
  } catch {
    return null;
  }
}

function isAllowedDeviceAuthorizationTransport(url: URL): boolean {
  if (url.protocol === 'https:') return true;
  if (url.protocol !== 'http:') return false;
  const hostname = url.hostname.toLowerCase();
  if (hostname === 'localhost' || hostname === '[::1]') return true;
  const octets = hostname.split('.');
  return (
    octets.length === 4 &&
    octets[0] === '127' &&
    octets.every((octet) => {
      const value = Number(octet);
      return Number.isInteger(value) && value >= 0 && value <= 255 && String(value) === octet;
    })
  );
}

function rawAuthorityHasUserInfo(rawUrl: string): boolean {
  const schemeBoundary = rawUrl.indexOf('://');
  if (schemeBoundary < 0) return false;
  const authority = rawUrl.slice(schemeBoundary + 3).split(/[/?#]/u, 1)[0] ?? '';
  return authority.includes('@');
}

export function normalizeDeviceAuthorizationInterval(intervalSeconds: number): number {
  if (!Number.isFinite(intervalSeconds)) return 5;
  return Math.min(60, Math.max(1, Math.ceil(intervalSeconds)));
}
