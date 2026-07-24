import type { AuthState, DesktopRuntimeConfig, LoginOutcome } from '../../types';

export type ForcedPasswordChangeValues = {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
};

export type ForcedPasswordChangeField = keyof ForcedPasswordChangeValues;

export type ForcedPasswordChangeValidation = {
  field: ForcedPasswordChangeField;
  messageKey:
    | 'forcePassword.currentRequired'
    | 'forcePassword.newRequired'
    | 'forcePassword.confirmRequired'
    | 'forcePassword.minimumLength'
    | 'forcePassword.mustDiffer'
    | 'forcePassword.mismatch';
};

export type PendingPasswordChangeAttempt = {
  outcome: LoginOutcome;
  runtimeConfig: DesktopRuntimeConfig;
  trustedDevice: boolean;
  authRevision: number;
};

export function validateForcedPasswordChange(
  values: ForcedPasswordChangeValues,
): ForcedPasswordChangeValidation | null {
  if (!values.currentPassword) {
    return { field: 'currentPassword', messageKey: 'forcePassword.currentRequired' };
  }
  if (!values.newPassword) {
    return { field: 'newPassword', messageKey: 'forcePassword.newRequired' };
  }
  if (values.newPassword.length < 8) {
    return { field: 'newPassword', messageKey: 'forcePassword.minimumLength' };
  }
  if (values.currentPassword === values.newPassword) {
    return { field: 'newPassword', messageKey: 'forcePassword.mustDiffer' };
  }
  if (!values.confirmPassword) {
    return { field: 'confirmPassword', messageKey: 'forcePassword.confirmRequired' };
  }
  if (values.newPassword !== values.confirmPassword) {
    return { field: 'confirmPassword', messageKey: 'forcePassword.mismatch' };
  }
  return null;
}

export function passwordChangeGateAuthState(
  submitting: boolean,
  error: string | null,
): AuthState {
  return {
    status: submitting ? 'changing_password' : 'password_change_required',
    credentialKind: null,
    session: null,
    context: null,
    user: null,
    tenants: [],
    projects: [],
    mustChangePassword: true,
    error,
  };
}

export function completeForcedPasswordChangeOutcome(
  outcome: LoginOutcome,
): LoginOutcome {
  return { ...outcome, must_change_password: false };
}
