import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { WorkspaceMemberRole } from '../api/client';
import type { DesktopRuntimeConfig, WorkspaceAgentBinding, WorkspaceMemberSummary } from '../types';

const MEMBER_REQUIRED_KEYS_V2 = new Set(['id', 'role', 'user_id', 'workspace_id']);
const MEMBER_OPTIONAL_KEYS_V2 = new Set(['created_at', 'invited_by', 'updated_at', 'user_email']);
const MEMBER_ROLES_V2 = new Set<WorkspaceMemberRole>(['owner', 'editor', 'viewer']);
const AGENT_REQUIRED_KEYS_V2 = new Set(['agent_id', 'id', 'is_active', 'workspace_id']);
const AGENT_OPTIONAL_KEYS_V2 = new Set([
  'config',
  'created_at',
  'description',
  'display_name',
  'hex_q',
  'hex_r',
  'label',
  'status',
  'theme_color',
  'updated_at',
]);

export function cloneWorkspaceRosterRuntimeConfigV2(
  config: DesktopRuntimeConfig
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw workspaceRosterInputInvalidV2();
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
    throw workspaceRosterInputInvalidV2();
  }
  return Object.freeze(copy);
}

export function cloneWorkspaceRosterSignalV2(value: unknown): AbortSignal | undefined {
  if (value === undefined) return undefined;
  if (typeof AbortSignal === 'undefined' || !(value instanceof AbortSignal)) {
    throw workspaceRosterInputInvalidV2();
  }
  return value;
}

export function assertWorkspaceRosterSignalV2(
  expected: AbortSignal | undefined,
  actual: AbortSignal | undefined
): void {
  if (actual !== expected) throw workspaceRosterInputInvalidV2();
}

export function cloneWorkspaceRosterMembersV2(
  value: unknown,
  workspaceId: string
): WorkspaceMemberSummary[] {
  if (!Array.isArray(value)) throw workspaceRosterResponseInvalidV2();
  const seenIds = new Set<string>();
  const seenUsers = new Set<string>();
  const result = value.map((candidate) => {
    const member = cloneWorkspaceRosterMemberV2(candidate, workspaceId);
    if (seenIds.has(member.id) || seenUsers.has(member.user_id)) {
      throw workspaceRosterResponseInvalidV2();
    }
    seenIds.add(member.id);
    seenUsers.add(member.user_id);
    return member;
  });
  return Object.freeze(result) as WorkspaceMemberSummary[];
}

export function cloneWorkspaceRosterAgentsV2(
  value: unknown,
  workspaceId: string
): WorkspaceAgentBinding[] {
  if (!Array.isArray(value)) throw workspaceRosterResponseInvalidV2();
  const seenIds = new Set<string>();
  const seenAgents = new Set<string>();
  const result = value.map((candidate) => {
    const agent = cloneWorkspaceRosterAgentV2(candidate, workspaceId);
    if (seenIds.has(agent.id) || seenAgents.has(agent.agent_id)) {
      throw workspaceRosterResponseInvalidV2();
    }
    seenIds.add(agent.id);
    seenAgents.add(agent.agent_id);
    return agent;
  });
  return Object.freeze(result) as WorkspaceAgentBinding[];
}

export function workspaceRosterInputInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_roster_input_invalid',
    'desktop workspace roster operation input is invalid'
  );
}

export function workspaceRosterResponseInvalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_workspace_roster_response_invalid',
    'desktop workspace roster response is invalid'
  );
}

export function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

export function hasExactOptionalKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function cloneWorkspaceRosterMemberV2(value: unknown, workspaceId: string): WorkspaceMemberSummary {
  if (
    !isPlainRecordV2(value) ||
    !hasRequiredAndOptionalKeysV2(value, MEMBER_REQUIRED_KEYS_V2, MEMBER_OPTIONAL_KEYS_V2) ||
    !isCanonicalIdentifierV2(value.id) ||
    value.workspace_id !== workspaceId ||
    !isCanonicalIdentifierV2(value.user_id) ||
    typeof value.role !== 'string' ||
    !MEMBER_ROLES_V2.has(value.role as WorkspaceMemberRole) ||
    !isOptionalNullableCanonicalStringV2(value.user_email) ||
    !isOptionalNullableCanonicalStringV2(value.invited_by) ||
    !isOptionalCanonicalStringV2(value.created_at) ||
    !isOptionalNullableCanonicalStringV2(value.updated_at)
  ) {
    throw workspaceRosterResponseInvalidV2();
  }
  return Object.freeze({
    id: value.id,
    workspace_id: workspaceId,
    user_id: value.user_id,
    role: value.role,
    ...(value.user_email === undefined ? {} : { user_email: value.user_email }),
    ...(value.invited_by === undefined ? {} : { invited_by: value.invited_by }),
    ...(value.created_at === undefined ? {} : { created_at: value.created_at }),
    ...(value.updated_at === undefined ? {} : { updated_at: value.updated_at }),
  });
}

function cloneWorkspaceRosterAgentV2(value: unknown, workspaceId: string): WorkspaceAgentBinding {
  if (
    !isPlainRecordV2(value) ||
    !hasRequiredAndOptionalKeysV2(value, AGENT_REQUIRED_KEYS_V2, AGENT_OPTIONAL_KEYS_V2) ||
    !isCanonicalIdentifierV2(value.id) ||
    value.workspace_id !== workspaceId ||
    !isCanonicalIdentifierV2(value.agent_id) ||
    typeof value.is_active !== 'boolean' ||
    !isOptionalNullableCanonicalStringV2(value.display_name) ||
    !isOptionalNullableTrimmedStringV2(value.description) ||
    !isOptionalNullableJsonRecordV2(value.config) ||
    !isOptionalNullableSafeIntegerV2(value.hex_q) ||
    !isOptionalNullableSafeIntegerV2(value.hex_r) ||
    !isOptionalNullableCanonicalStringV2(value.theme_color) ||
    !isOptionalNullableTrimmedStringV2(value.label) ||
    !isOptionalNullableCanonicalStringV2(value.status) ||
    !isOptionalCanonicalStringV2(value.created_at) ||
    !isOptionalNullableCanonicalStringV2(value.updated_at)
  ) {
    throw workspaceRosterResponseInvalidV2();
  }
  return Object.freeze({
    id: value.id,
    workspace_id: workspaceId,
    agent_id: value.agent_id,
    is_active: value.is_active,
    ...(value.display_name === undefined ? {} : { display_name: value.display_name }),
    ...(value.description === undefined ? {} : { description: value.description }),
    ...(value.config === undefined
      ? {}
      : { config: value.config === null ? null : cloneJsonRecordV2(value.config) }),
    ...(value.hex_q === undefined ? {} : { hex_q: value.hex_q }),
    ...(value.hex_r === undefined ? {} : { hex_r: value.hex_r }),
    ...(value.theme_color === undefined ? {} : { theme_color: value.theme_color }),
    ...(value.label === undefined ? {} : { label: value.label }),
    ...(value.status === undefined ? {} : { status: value.status }),
    ...(value.created_at === undefined ? {} : { created_at: value.created_at }),
    ...(value.updated_at === undefined ? {} : { updated_at: value.updated_at }),
  });
}

function cloneJsonRecordV2(value: unknown): Readonly<Record<string, unknown>> {
  if (!isPlainRecordV2(value)) throw workspaceRosterResponseInvalidV2();
  return cloneJsonValueV2(value, new Set(), 0) as Readonly<Record<string, unknown>>;
}

function cloneJsonValueV2(value: unknown, ancestors: Set<object>, depth: number): unknown {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw workspaceRosterResponseInvalidV2();
    return value;
  }
  if (depth >= 32 || typeof value !== 'object' || value === null || ancestors.has(value)) {
    throw workspaceRosterResponseInvalidV2();
  }
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      return Object.freeze(value.map((item) => cloneJsonValueV2(item, ancestors, depth + 1)));
    }
    if (!isPlainRecordV2(value)) throw workspaceRosterResponseInvalidV2();
    const clone: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      if (key === '__proto__' || key === 'constructor' || key === 'prototype') {
        throw workspaceRosterResponseInvalidV2();
      }
      clone[key] = cloneJsonValueV2(item, ancestors, depth + 1);
    }
    return Object.freeze(clone);
  } finally {
    ancestors.delete(value);
  }
}

function hasRequiredAndOptionalKeysV2(
  value: Record<string, unknown>,
  required: ReadonlySet<string>,
  optional: ReadonlySet<string>
): boolean {
  return (
    [...required].every((key) => Object.hasOwn(value, key)) &&
    Object.keys(value).every((key) => required.has(key) || optional.has(key))
  );
}

function isCanonicalIdentifierV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isOptionalCanonicalStringV2(value: unknown): value is string | undefined {
  return value === undefined || isCanonicalIdentifierV2(value);
}

function isOptionalNullableCanonicalStringV2(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || isCanonicalIdentifierV2(value);
}

function isOptionalNullableTrimmedStringV2(value: unknown): value is string | null | undefined {
  return (
    value === undefined || value === null || (typeof value === 'string' && value === value.trim())
  );
}

function isOptionalNullableSafeIntegerV2(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || Number.isSafeInteger(value);
}

function isOptionalNullableJsonRecordV2(
  value: unknown
): value is Record<string, unknown> | null | undefined {
  if (value === undefined || value === null) return true;
  try {
    cloneJsonRecordV2(value);
    return true;
  } catch {
    return false;
  }
}
