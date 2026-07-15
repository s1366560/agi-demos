import type { RuntimeMode } from '../../types';

export type WorkspaceSsoAction =
  | { kind: 'local_session'; trustedDevice: boolean }
  | { kind: 'unavailable' };

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
  if (mode !== 'local' || !localReady) return { kind: 'unavailable' };
  return { kind: 'local_session', trustedDevice: true };
}
