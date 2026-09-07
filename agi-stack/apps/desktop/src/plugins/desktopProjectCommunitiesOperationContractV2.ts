import { RuntimeV2Error } from '@agistack/plugin-runtime';

import {
  PROJECT_COMMUNITIES_DEGRADED_REASON,
  type ProjectCommunitiesSnapshot,
  type ProjectCommunity,
} from '../features/project-knowledge/projectCommunitiesClient';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopProjectCommunitiesLoadOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectKnowledgeScope;
  signal?: AbortSignal;
}>;

export type DesktopProjectCommunitiesAuthorityOperationInputV2 =
  DesktopProjectCommunitiesLoadOperationInputV2 & Readonly<{ kind: 'load' }>;

export type PreparedDesktopProjectCommunitiesAuthorityOperationV2 =
  DesktopProjectCommunitiesAuthorityOperationInputV2;

const INPUT_KEYS_V2 = new Set(['kind', 'config', 'scope', 'signal']);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);
const SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'scopeRevision',
  'authority',
  'availability',
  'reasonCode',
  'allowedActions',
  'communities',
  'total',
]);
const COMMUNITY_KEYS_V2 = new Set([
  'id',
  'name',
  'summary',
  'memberCount',
  'projectId',
  'createdAt',
]);

export function prepareDesktopProjectCommunitiesAuthorityOperationV2(
  input: DesktopProjectCommunitiesAuthorityOperationInputV2,
): PreparedDesktopProjectCommunitiesAuthorityOperationV2 {
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
  const config = cloneDesktopProjectCommunitiesRuntimeConfigV2(input.config);
  const scope = cloneDesktopProjectCommunitiesScopeV2(input.scope, config);
  return Object.freeze({
    kind: 'load',
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function cloneDesktopProjectCommunitiesRuntimeConfigV2(
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

export function cloneDesktopProjectCommunitiesScopeV2(
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

export function requireDesktopProjectCommunitiesSnapshotV2(
  value: unknown,
  scope: ProjectKnowledgeScope,
): ProjectCommunitiesSnapshot {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    value.authority !== scope.authority ||
    value.availability !== 'degraded' ||
    value.reasonCode !== PROJECT_COMMUNITIES_DEGRADED_REASON ||
    !exactActionsV2(value.allowedActions) ||
    !Number.isSafeInteger(value.scopeRevision) ||
    Number(value.scopeRevision) < 0 ||
    !sameScopeV2(value.scope, scope) ||
    !validCommunityPageV2(value.communities, value.total, scope.projectId)
  ) {
    throw invalidServiceContractV2();
  }
  return deepFreezeV2(structuredClone(value)) as ProjectCommunitiesSnapshot;
}

function validCommunityPageV2(
  communitiesValue: unknown,
  totalValue: unknown,
  projectId: string,
): boolean {
  if (
    !Array.isArray(communitiesValue) ||
    !Number.isSafeInteger(totalValue) ||
    Number(totalValue) < communitiesValue.length
  ) {
    return false;
  }
  const ids = new Set<string>();
  for (const community of communitiesValue) {
    if (!validCommunityV2(community, projectId) || ids.has(community.id)) return false;
    ids.add(community.id);
  }
  return true;
}

function validCommunityV2(value: unknown, projectId: string): value is ProjectCommunity {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, COMMUNITY_KEYS_V2) &&
    canonicalIdentifierV2(value.id) &&
    canonicalIdentifierV2(value.name) &&
    typeof value.summary === 'string' &&
    Number.isSafeInteger(value.memberCount) &&
    Number(value.memberCount) >= 0 &&
    (value.projectId === null || value.projectId === projectId) &&
    (value.createdAt === null || typeof value.createdAt === 'string')
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
  return Array.isArray(value) && value.length === 2 && value[0] === 'view' && value[1] === 'list';
}

function invalidInputV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_communities_operation_input_invalid',
    'desktop project communities operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_communities_service_contract_invalid',
    'desktop project communities authority returned an invalid result',
  );
}

function hasExactOptionalKeysV2(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
): boolean {
  return Object.keys(value).every((key) => allowed.has(key));
}

function hasExactKeysV2(
  value: Record<string, unknown>,
  expected: ReadonlySet<string>,
): boolean {
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
