import { RuntimeV2Error } from '@agistack/plugin-runtime';

import {
  PROJECT_TEAM_DEGRADED_REASON,
  type ProjectAgentTeammate,
  type ProjectTeamMember,
  type ProjectTeamRole,
  type ProjectTeamSnapshot,
} from '../features/project-knowledge/projectTeamClient';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopProjectTeamLoadOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectKnowledgeScope;
  signal?: AbortSignal;
}>;

export type DesktopProjectTeamAuthorityOperationInputV2 = DesktopProjectTeamLoadOperationInputV2 &
  Readonly<{ kind: 'load' }>;

export type PreparedDesktopProjectTeamAuthorityOperationV2 =
  DesktopProjectTeamAuthorityOperationInputV2;

const INPUT_KEYS_V2 = new Set(['kind', 'config', 'scope', 'signal']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);
const SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'scopeRevision',
  'authority',
  'availability',
  'reasonCode',
  'allowedActions',
  'members',
  'agents',
  'currentUserRole',
]);
const MEMBER_KEYS_V2 = new Set(['userId', 'email', 'name', 'role', 'permissions', 'createdAt']);
const AGENT_KEYS_V2 = new Set(['id', 'name', 'enabled', 'model']);
const ROLES_V2 = new Set<ProjectTeamRole>(['owner', 'admin', 'member', 'editor', 'viewer']);

export function prepareDesktopProjectTeamAuthorityOperationV2(
  input: DesktopProjectTeamAuthorityOperationInputV2,
): PreparedDesktopProjectTeamAuthorityOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    input.kind !== 'load' ||
    !hasExactOptionalKeysV2(input, INPUT_KEYS_V2) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidInputV2();
  }
  const config = cloneDesktopProjectTeamRuntimeConfigV2(input.config);
  const scope = cloneDesktopProjectTeamScopeV2(input.scope, config);
  return Object.freeze({
    kind: 'load',
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function cloneDesktopProjectTeamRuntimeConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!isPlainRecordV2(config)) throw invalidInputV2();
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
    !canonicalStringV2(copy.apiBaseUrl) ||
    !canonicalIdentifierV2(copy.tenantId) ||
    !canonicalIdentifierV2(copy.projectId)
  ) {
    throw invalidInputV2();
  }
  return Object.freeze(copy);
}

export function cloneDesktopProjectTeamScopeV2(
  scope: ProjectKnowledgeScope,
  config: DesktopRuntimeConfig,
): ProjectKnowledgeScope {
  if (
    !isPlainRecordV2(scope) ||
    !hasExactKeysV2(scope, SCOPE_KEYS_V2) ||
    scope.authority !== config.mode ||
    !canonicalIdentifierV2(scope.tenantId) ||
    !canonicalIdentifierV2(scope.projectId) ||
    scope.tenantId !== config.tenantId ||
    scope.projectId !== config.projectId
  ) {
    throw invalidInputV2();
  }
  return Object.freeze({
    authority: scope.authority,
    tenantId: scope.tenantId,
    projectId: scope.projectId,
  });
}

export function requireDesktopProjectTeamSnapshotV2(
  value: unknown,
  scope: ProjectKnowledgeScope,
): ProjectTeamSnapshot {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    value.authority !== scope.authority ||
    value.availability !== 'degraded' ||
    value.reasonCode !== PROJECT_TEAM_DEGRADED_REASON ||
    !exactActionsV2(value.allowedActions) ||
    !Number.isSafeInteger(value.scopeRevision) ||
    Number(value.scopeRevision) < 0 ||
    !sameScopeV2(value.scope, scope) ||
    !validRoleV2(value.currentUserRole) ||
    !validMembersV2(value.members) ||
    !validAgentsV2(value.agents)
  ) {
    throw invalidServiceContractV2();
  }
  return deepFreezeV2(structuredClone(value)) as ProjectTeamSnapshot;
}

function validMembersV2(value: unknown): value is readonly ProjectTeamMember[] {
  if (!Array.isArray(value)) return false;
  const ids = new Set<string>();
  for (const member of value) {
    if (!validMemberV2(member) || ids.has(member.userId)) return false;
    ids.add(member.userId);
  }
  return true;
}

function validMemberV2(value: unknown): value is ProjectTeamMember {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, MEMBER_KEYS_V2) &&
    canonicalIdentifierV2(value.userId) &&
    canonicalIdentifierV2(value.email) &&
    (value.name === null || typeof value.name === 'string') &&
    validRoleV2(value.role) &&
    isPlainRecordV2(value.permissions) &&
    canonicalIdentifierV2(value.createdAt)
  );
}

function validAgentsV2(value: unknown): value is readonly ProjectAgentTeammate[] {
  if (!Array.isArray(value)) return false;
  const ids = new Set<string>();
  for (const agent of value) {
    if (!validAgentV2(agent) || ids.has(agent.id)) return false;
    ids.add(agent.id);
  }
  return true;
}

function validAgentV2(value: unknown): value is ProjectAgentTeammate {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, AGENT_KEYS_V2) &&
    canonicalIdentifierV2(value.id) &&
    canonicalIdentifierV2(value.name) &&
    typeof value.enabled === 'boolean' &&
    (value.model === null || canonicalIdentifierV2(value.model))
  );
}

function sameScopeV2(value: unknown, scope: ProjectKnowledgeScope): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, SCOPE_KEYS_V2) &&
    value.authority === scope.authority &&
    value.tenantId === scope.tenantId &&
    value.projectId === scope.projectId
  );
}

function exactActionsV2(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value[0] === 'view' &&
    value[1] === 'list-members' &&
    value[2] === 'list-agent-teammates'
  );
}

function validRoleV2(value: unknown): value is ProjectTeamRole {
  return typeof value === 'string' && ROLES_V2.has(value as ProjectTeamRole);
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_team_operation_input_invalid',
    'desktop project team operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_team_service_contract_invalid',
    'desktop project team authority returned an invalid result',
  );
}

function hasExactOptionalKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function hasExactKeysV2(value: Record<string, unknown>, expected: ReadonlySet<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function canonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function canonicalIdentifierV2(value: unknown): value is string {
  return canonicalStringV2(value) && value.length <= 512;
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return typeof AbortSignal !== 'undefined' && value instanceof AbortSignal;
}

function deepFreezeV2<T>(value: T): T {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const nested of Object.values(value)) deepFreezeV2(nested);
  }
  return value;
}
