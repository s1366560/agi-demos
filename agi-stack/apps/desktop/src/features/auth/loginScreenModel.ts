import type { RuntimeMode } from '../../types';

export type WorkspaceSsoAction =
  | { kind: 'local_session'; trustedDevice: boolean }
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
  if (mode !== 'local') return { kind: 'unavailable', capability: 'workspace_sso' };
  if (!localReady) return { kind: 'unavailable', capability: 'local_workspace' };
  return { kind: 'local_session', trustedDevice: true };
}

export function resolveWorkspaceContinueLabelKey(mode: RuntimeMode): WorkspaceContinueLabelKey {
  return mode === 'local' ? 'login.localWorkspace' : 'login.workspaceSso';
}
