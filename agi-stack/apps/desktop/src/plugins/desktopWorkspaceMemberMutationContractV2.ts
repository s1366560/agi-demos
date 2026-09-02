import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { WorkspaceMemberRole } from '../api/client';
import type { DesktopRuntimeConfig, WorkspaceMemberSummary } from '../types';

const MEMBER_REQUIRED_KEYS_V2 = new Set(['id', 'role', 'user_id', 'workspace_id']);
const MEMBER_OPTIONAL_KEYS_V2 = new Set(['created_at', 'invited_by', 'updated_at', 'user_email']);
const MEMBER_ROLES_V2 = new Set<WorkspaceMemberRole>(['owner', 'editor', 'viewer']);

export function cloneWorkspaceMemberMutationRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw workspaceMemberMutationInputInvalidV2();
  const copy: DesktopRuntimeConfig = {
    apiBaseUrl: config.apiBaseUrl,
    deviceAuthorizationBaseUrl: config.deviceAuthorizationBaseUrl,
    apiKey: config.apiKey,
    localApiToken: config.localApiToken,
    tenantId: config.tenantId,
    projectId: config.projectId,
    workspaceId: config.workspaceId,
    mode: config.mode,
    workspaceRoot: config.workspaceRoot,
  };
  if (
    Object.values(copy).some((value) => typeof value !== 'string') ||
    (copy.mode !== 'cloud' && copy.mode !== 'local') ||
    !isCanonicalIdentifierV2(copy.apiBaseUrl) ||
    !isCanonicalIdentifierV2(copy.tenantId) ||
    !isCanonicalIdentifierV2(copy.projectId) ||
    !isCanonicalIdentifierV2(copy.workspaceId)
  ) {
    throw workspaceMemberMutationInputInvalidV2();
  }
  return Object.freeze(copy);
}

export function cloneWorkspaceMemberMutationWorkspaceIdV2(
  config: DesktopRuntimeConfig,
  workspaceId: unknown,
): string {
  if (!isCanonicalIdentifierV2(workspaceId) || workspaceId !== config.workspaceId) {
    throw workspaceMemberMutationInputInvalidV2();
  }
  return workspaceId;
}

export function cloneWorkspaceMemberMutationUserIdV2(userId: unknown): string {
  if (!isCanonicalIdentifierV2(userId)) throw workspaceMemberMutationInputInvalidV2();
  return userId;
}

export function cloneWorkspaceMemberMutationRoleV2(role: unknown): WorkspaceMemberRole {
  if (typeof role !== 'string' || !MEMBER_ROLES_V2.has(role as WorkspaceMemberRole)) {
    throw workspaceMemberMutationInputInvalidV2();
  }
  return role as WorkspaceMemberRole;
}

export function cloneWorkspaceMemberMutationSignalV2(value: unknown): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw workspaceMemberMutationInputInvalidV2();
  }
  return value;
}

export function assertWorkspaceMemberMutationSignalV2(
  expected: AbortSignal | undefined,
  actual: AbortSignal | undefined,
): void {
  if (actual !== expected) throw workspaceMemberMutationInputInvalidV2();
}

export function cloneWorkspaceMemberMutationResponseV2(
  value: unknown,
  workspaceId: string,
  userId: string,
  role: WorkspaceMemberRole,
): WorkspaceMemberSummary {
  if (
    !isPlainRecordV2(value) ||
    !hasRequiredAndOptionalKeysV2(value, MEMBER_REQUIRED_KEYS_V2, MEMBER_OPTIONAL_KEYS_V2) ||
    !isCanonicalIdentifierV2(value.id) ||
    value.workspace_id !== workspaceId ||
    value.user_id !== userId ||
    value.role !== role ||
    !isOptionalNullableCanonicalIdentifierV2(value.user_email) ||
    !isOptionalNullableCanonicalIdentifierV2(value.invited_by) ||
    !isOptionalCanonicalIdentifierV2(value.created_at) ||
    !isOptionalNullableCanonicalIdentifierV2(value.updated_at)
  ) {
    throw workspaceMemberMutationResponseInvalidV2();
  }
  return Object.freeze({
    id: value.id,
    workspace_id: workspaceId,
    user_id: userId,
    role,
    ...(value.user_email === undefined ? {} : { user_email: value.user_email }),
    ...(value.invited_by === undefined ? {} : { invited_by: value.invited_by }),
    ...(value.created_at === undefined ? {} : { created_at: value.created_at }),
    ...(value.updated_at === undefined ? {} : { updated_at: value.updated_at }),
  });
}

export function assertVoidWorkspaceMemberMutationResponseV2(value: unknown): void {
  if (value !== undefined) throw workspaceMemberMutationResponseInvalidV2();
}

export function workspaceMemberMutationInputInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_member_mutation_input_invalid',
    'desktop workspace-member mutation operation input is invalid',
  );
}

export function workspaceMemberMutationResponseInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_member_mutation_response_invalid',
    'desktop workspace-member mutation response is invalid',
  );
}

export function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function hasExactOptionalKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function hasRequiredAndOptionalKeysV2(
  value: Record<string, unknown>,
  required: ReadonlySet<string>,
  optional: ReadonlySet<string>,
): boolean {
  const keys = Object.keys(value);
  return (
    [...required].every((key) => Object.hasOwn(value, key)) &&
    keys.every((key) => required.has(key) || optional.has(key))
  );
}

function isCanonicalIdentifierV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isOptionalCanonicalIdentifierV2(value: unknown): value is string | undefined {
  return value === undefined || isCanonicalIdentifierV2(value);
}

function isOptionalNullableCanonicalIdentifierV2(
  value: unknown,
): value is string | null | undefined {
  return value === undefined || value === null || isCanonicalIdentifierV2(value);
}
