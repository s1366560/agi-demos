import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type {
  ProjectEntitiesSnapshot,
  ProjectEntity,
  ProjectEntityRelationship,
} from '../features/project-knowledge/projectEntitiesClient';
import { PROJECT_ENTITIES_DEGRADED_REASON } from '../features/project-knowledge/projectEntitiesClient';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopProjectEntitiesLoadOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectKnowledgeScope;
  signal?: AbortSignal;
}>;

export type DesktopProjectEntityRelationshipsOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectKnowledgeScope;
  entityId: string;
  signal?: AbortSignal;
}>;

export type DesktopProjectEntitiesAuthorityOperationInputV2 =
  | (DesktopProjectEntitiesLoadOperationInputV2 & Readonly<{ kind: 'load' }>)
  | (DesktopProjectEntityRelationshipsOperationInputV2 &
      Readonly<{ kind: 'relationships' }>);

export type PreparedDesktopProjectEntitiesAuthorityOperationV2 =
  DesktopProjectEntitiesAuthorityOperationInputV2;

const LOAD_INPUT_KEYS_V2 = new Set(['kind', 'config', 'scope', 'signal']);
const RELATIONSHIPS_INPUT_KEYS_V2 = new Set([
  'kind',
  'config',
  'scope',
  'entityId',
  'signal',
]);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);
const SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'scopeRevision',
  'authority',
  'availability',
  'reasonCode',
  'allowedActions',
  'entities',
  'total',
  'entityTypes',
]);
const ENTITY_KEYS_V2 = new Set([
  'id',
  'name',
  'entityType',
  'summary',
  'projectId',
  'createdAt',
]);
const ENTITY_TYPE_KEYS_V2 = new Set(['entityType', 'count']);
const RELATIONSHIP_KEYS_V2 = new Set([
  'edgeId',
  'relationType',
  'direction',
  'fact',
  'relatedEntity',
]);

export function prepareDesktopProjectEntitiesAuthorityOperationV2(
  input: DesktopProjectEntitiesAuthorityOperationInputV2,
): PreparedDesktopProjectEntitiesAuthorityOperationV2 {
  if (!isPlainRecordV2(input)) throw invalidInputV2();
  const allowedKeys =
    input.kind === 'load'
      ? LOAD_INPUT_KEYS_V2
      : input.kind === 'relationships'
        ? RELATIONSHIPS_INPUT_KEYS_V2
        : null;
  if (
    allowedKeys === null ||
    !hasExactOptionalKeysV2(input, allowedKeys) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidInputV2();
  }
  const config = cloneDesktopProjectEntitiesRuntimeConfigV2(input.config);
  const scope = cloneDesktopProjectEntitiesScopeV2(input.scope, config);
  if (input.kind === 'relationships') {
    return Object.freeze({
      kind: 'relationships',
      config,
      scope,
      entityId: requireCanonicalIdentifierV2(input.entityId),
      ...(input.signal === undefined ? {} : { signal: input.signal }),
    });
  }
  return Object.freeze({
    kind: 'load',
    config,
    scope,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function cloneDesktopProjectEntitiesRuntimeConfigV2(
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

export function cloneDesktopProjectEntitiesScopeV2(
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

export function requireDesktopProjectEntitiesSnapshotV2(
  value: unknown,
  scope: ProjectKnowledgeScope,
): ProjectEntitiesSnapshot {
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(value, SNAPSHOT_KEYS_V2) ||
    value.authority !== scope.authority ||
    value.availability !== 'degraded' ||
    value.reasonCode !== PROJECT_ENTITIES_DEGRADED_REASON ||
    !exactActionsV2(value.allowedActions) ||
    !Number.isSafeInteger(value.scopeRevision) ||
    Number(value.scopeRevision) < 0 ||
    !sameScopeV2(value.scope, scope) ||
    !validEntityPageV2(value.entities, value.total, scope.projectId) ||
    !validEntityTypesV2(value.entityTypes)
  ) {
    throw invalidServiceContractV2();
  }
  return deepFreezeV2(structuredClone(value)) as ProjectEntitiesSnapshot;
}

export function requireDesktopProjectEntityRelationshipsV2(
  value: unknown,
  scope: ProjectKnowledgeScope,
): readonly ProjectEntityRelationship[] {
  if (
    !Array.isArray(value) ||
    value.some((relationship) => !validRelationshipV2(relationship, scope.projectId))
  ) {
    throw invalidServiceContractV2();
  }
  return deepFreezeV2(structuredClone(value)) as readonly ProjectEntityRelationship[];
}

function validEntityPageV2(
  entitiesValue: unknown,
  totalValue: unknown,
  projectId: string,
): boolean {
  if (
    !Array.isArray(entitiesValue) ||
    !Number.isSafeInteger(totalValue) ||
    Number(totalValue) < entitiesValue.length
  ) {
    return false;
  }
  const ids = new Set<string>();
  for (const entity of entitiesValue) {
    if (!validEntityV2(entity, projectId) || ids.has(entity.id)) return false;
    ids.add(entity.id);
  }
  return true;
}

function validEntityTypesV2(value: unknown): boolean {
  if (!Array.isArray(value)) return false;
  const types = new Set<string>();
  for (const item of value) {
    if (
      !isPlainRecordV2(item) ||
      !hasExactKeysV2(item, ENTITY_TYPE_KEYS_V2) ||
      !canonicalIdentifierV2(item.entityType) ||
      !Number.isSafeInteger(item.count) ||
      Number(item.count) < 0 ||
      types.has(item.entityType)
    ) {
      return false;
    }
    types.add(item.entityType);
  }
  return true;
}

function validRelationshipV2(value: unknown, projectId: string): boolean {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, RELATIONSHIP_KEYS_V2) &&
    canonicalIdentifierV2(value.edgeId) &&
    canonicalIdentifierV2(value.relationType) &&
    (value.direction === 'outgoing' || value.direction === 'incoming') &&
    typeof value.fact === 'string' &&
    validEntityV2(value.relatedEntity, projectId)
  );
}

function validEntityV2(value: unknown, projectId: string): value is ProjectEntity {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, ENTITY_KEYS_V2) &&
    canonicalIdentifierV2(value.id) &&
    canonicalIdentifierV2(value.name) &&
    canonicalIdentifierV2(value.entityType) &&
    typeof value.summary === 'string' &&
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
    'desktop_project_entities_operation_input_invalid',
    'desktop project entities operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_entities_service_contract_invalid',
    'desktop project entities authority returned an invalid result',
  );
}

function requireCanonicalIdentifierV2(value: unknown): string {
  if (!canonicalIdentifierV2(value)) throw invalidInputV2();
  return value;
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
