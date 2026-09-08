import type {
  CloudMemoryCommand,
  CloudMemoryOptions,
} from '../features/project-knowledge/cloudMemoryClient';
import {
  prepareCloudMemoryCommand,
  prepareCloudMemoryOptions,
} from '../features/project-knowledge/cloudMemoryValidation';
import { RuntimeV2Error } from '@agistack/plugin-runtime';
import { validCloudMemoryCapabilitySnapshot } from '../features/project-knowledge/cloudMemoryCapabilities';

import {
  PROJECT_MEMORIES_DEGRADED_REASON,
  type ProjectMemoriesSnapshot,
  type ProjectMemory,
  type ProjectMemoriesPageOptions,
} from '../features/project-knowledge/projectMemoriesClient';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import type {
  NativeKnowledgeCommand,
  NativeKnowledgeSyncOptions,
} from '../features/project-knowledge/nativeKnowledgeContracts';
import {
  prepareNativeKnowledgeCommand,
  requireNativeKnowledgeCommandOptions,
} from '../features/project-knowledge/nativeKnowledgeValidation';
import { requireNativeKnowledgeTransportV2 } from './desktopNativeKnowledgeSyncHttpV2';

export type DesktopProjectMemoriesLoadOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectKnowledgeScope;
  signal?: AbortSignal;
  page?: number;
  pageSize?: number;
}>;

export type DesktopProjectMemoriesSyncOperationInputV2<
  C extends NativeKnowledgeCommand = NativeKnowledgeCommand,
> = NativeKnowledgeSyncOptions &
  Readonly<{
    config: DesktopRuntimeConfig;
    scope: ProjectKnowledgeScope;
    command: C;
  }>;

export type DesktopProjectMemoriesCloudOperationInputV2<
  C extends CloudMemoryCommand = CloudMemoryCommand,
> = CloudMemoryOptions &
  Readonly<{ config: DesktopRuntimeConfig; scope: ProjectKnowledgeScope; command: C }>;

export type DesktopProjectMemoriesAuthorityOperationInputV2 =
  | (DesktopProjectMemoriesCloudOperationInputV2 & Readonly<{ kind: 'cloud' }>)
  | (DesktopProjectMemoriesLoadOperationInputV2 & Readonly<{ kind: 'load' }>)
  | (DesktopProjectMemoriesSyncOperationInputV2 & Readonly<{ kind: 'sync' }>);

export type PreparedDesktopProjectMemoriesAuthorityOperationV2 =
  DesktopProjectMemoriesAuthorityOperationInputV2;

const CLOUD_INPUT_KEYS_V2 = new Set([
  'kind',
  'config',
  'scope',
  'command',
  'signal',
  'expectedActorId',
  'expectedContextRevision',
]);
const INPUT_KEYS_V2 = new Set(['kind', 'config', 'scope', 'signal', 'page', 'pageSize']);
const SYNC_INPUT_KEYS_V2 = new Set([
  'kind',
  'config',
  'scope',
  'signal',
  'expectedScope',
  'command',
]);
const SCOPE_KEYS_V2 = new Set(['authority', 'tenantId', 'projectId']);
const SNAPSHOT_KEYS_V2 = new Set([
  'scope',
  'scopeRevision',
  'authority',
  'availability',
  'reasonCode',
  'allowedActions',
  'memories',
  'total',
  'page',
  'pageSize',
]);
const LOCAL_SNAPSHOT_KEYS_V2 = new Set([...SNAPSHOT_KEYS_V2, 'hasMore']);
const CLOUD_CAPABILITY_SNAPSHOT_KEYS_V2 = new Set([...SNAPSHOT_KEYS_V2, 'commandCapabilities']);
const MEMORY_KEYS_V2 = new Set([
  'id',
  'projectId',
  'title',
  'content',
  'contentType',
  'version',
  'status',
  'processingStatus',
  'createdAt',
  'updatedAt',
]);

export function prepareDesktopProjectMemoriesAuthorityOperationV2<C extends CloudMemoryCommand>(
  input: DesktopProjectMemoriesCloudOperationInputV2<C> & Readonly<{ kind: 'cloud' }>,
): DesktopProjectMemoriesCloudOperationInputV2<C> & Readonly<{ kind: 'cloud' }>;
export function prepareDesktopProjectMemoriesAuthorityOperationV2(
  input: DesktopProjectMemoriesLoadOperationInputV2 & Readonly<{ kind: 'load' }>,
): DesktopProjectMemoriesLoadOperationInputV2 & Readonly<{ kind: 'load' }>;
export function prepareDesktopProjectMemoriesAuthorityOperationV2<C extends NativeKnowledgeCommand>(
  input: DesktopProjectMemoriesSyncOperationInputV2<C> & Readonly<{ kind: 'sync' }>,
): DesktopProjectMemoriesSyncOperationInputV2<C> & Readonly<{ kind: 'sync' }>;
export function prepareDesktopProjectMemoriesAuthorityOperationV2(
  input: DesktopProjectMemoriesAuthorityOperationInputV2,
): PreparedDesktopProjectMemoriesAuthorityOperationV2;
export function prepareDesktopProjectMemoriesAuthorityOperationV2(
  input: DesktopProjectMemoriesAuthorityOperationInputV2,
): PreparedDesktopProjectMemoriesAuthorityOperationV2 {
  if (
    !isPlainRecordV2(input) ||
    (input.kind !== 'load' && input.kind !== 'sync' && input.kind !== 'cloud') ||
    !hasExactOptionalKeysV2(
      input,
      input.kind === 'cloud'
        ? CLOUD_INPUT_KEYS_V2
        : input.kind === 'sync'
          ? SYNC_INPUT_KEYS_V2
          : INPUT_KEYS_V2,
    ) ||
    !Object.hasOwn(input, 'config') ||
    !Object.hasOwn(input, 'scope') ||
    (input.signal !== undefined && !isAbortSignalV2(input.signal))
  ) {
    throw invalidInputV2();
  }
  const config = cloneDesktopProjectMemoriesRuntimeConfigV2(input.config);
  const scope = cloneDesktopProjectMemoriesScopeV2(input.scope, config);
  if (input.kind === 'cloud') {
    if (scope.authority !== 'cloud') throw invalidInputV2();
    return Object.freeze({
      kind: 'cloud',
      config,
      scope,
      command: prepareCloudMemoryCommand(input.command),
      ...prepareCloudMemoryOptions({
        expectedActorId: input.expectedActorId,
        expectedContextRevision: input.expectedContextRevision,
        ...(input.signal === undefined ? {} : { signal: input.signal }),
      }),
    });
  }
  if (input.kind === 'sync') {
    requireNativeKnowledgeTransportV2(config);
    return Object.freeze({
      kind: 'sync',
      config,
      scope,
      command: prepareNativeKnowledgeCommand(input.command),
      ...requireNativeKnowledgeCommandOptions(input.command, {
        signal: input.signal,
        expectedScope: input.expectedScope,
      }),
    });
  }
  return Object.freeze({
    kind: 'load',
    config,
    scope,
    ...normalizeDesktopProjectMemoriesPageV2(input),
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}

export function cloneDesktopProjectMemoriesRuntimeConfigV2(
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

export function cloneDesktopProjectMemoriesScopeV2(
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

export function requireDesktopProjectMemoriesSnapshotV2(
  value: unknown,
  scope: ProjectKnowledgeScope,
  options: ProjectMemoriesPageOptions = {},
): ProjectMemoriesSnapshot {
  const page = normalizeDesktopProjectMemoriesPageV2(options);
  if (
    !isPlainRecordV2(value) ||
    !hasExactKeysV2(
      value,
      scope.authority === 'local'
        ? LOCAL_SNAPSHOT_KEYS_V2
        : Object.hasOwn(value, 'commandCapabilities')
          ? CLOUD_CAPABILITY_SNAPSHOT_KEYS_V2
          : SNAPSHOT_KEYS_V2,
    ) ||
    value.authority !== scope.authority ||
    value.availability !== 'degraded' ||
    value.reasonCode !== PROJECT_MEMORIES_DEGRADED_REASON ||
    !exactActionsV2(value.allowedActions) ||
    !Number.isSafeInteger(value.scopeRevision) ||
    Number(value.scopeRevision) < 0 ||
    !sameScopeV2(value.scope, scope) ||
    value.page !== page.page ||
    value.pageSize !== page.pageSize ||
    !Array.isArray(value.memories) ||
    value.memories.length > page.pageSize ||
    (scope.authority === 'local' &&
      (value.total !== null ||
        typeof value.hasMore !== 'boolean' ||
        (value.hasMore && value.memories.length !== page.pageSize))) ||
    !validMemoryPageV2(
      value.memories,
      scope.authority === 'local' ? value.memories.length : value.total,
      scope.projectId,
    )
  ) {
    throw invalidServiceContractV2();
  }
  if (
    Object.hasOwn(value, 'commandCapabilities') &&
    !validCloudMemoryCapabilitySnapshot(
      value.commandCapabilities,
      scope,
      value.memories as ProjectMemory[],
    )
  ) {
    throw invalidServiceContractV2();
  }
  return deepFreezeV2(structuredClone(value)) as ProjectMemoriesSnapshot;
}

export function normalizeDesktopProjectMemoriesPageV2(
  options: ProjectMemoriesPageOptions = {},
): Readonly<{ page: number; pageSize: number }> {
  if (!isPlainRecordV2(options)) throw invalidInputV2();
  const page = options.page === undefined ? 1 : options.page;
  const pageSize = options.pageSize === undefined ? 50 : options.pageSize;
  if (
    !Number.isSafeInteger(page) ||
    page < 1 ||
    !Number.isSafeInteger(pageSize) ||
    pageSize < 1 ||
    pageSize > 100
  ) {
    throw invalidInputV2();
  }
  return Object.freeze({ page, pageSize });
}

function validMemoryPageV2(
  memoriesValue: unknown,
  totalValue: unknown,
  projectId: string,
): boolean {
  if (
    !Array.isArray(memoriesValue) ||
    !Number.isSafeInteger(totalValue) ||
    Number(totalValue) < memoriesValue.length
  ) {
    return false;
  }
  const ids = new Set<string>();
  for (const memory of memoriesValue) {
    if (!validMemoryV2(memory, projectId) || ids.has(memory.id)) return false;
    ids.add(memory.id);
  }
  return true;
}

function validMemoryV2(value: unknown, projectId: string): value is ProjectMemory {
  return (
    isPlainRecordV2(value) &&
    hasExactKeysV2(value, MEMORY_KEYS_V2) &&
    canonicalIdentifierV2(value.id) &&
    value.projectId === projectId &&
    canonicalIdentifierV2(value.title) &&
    typeof value.content === 'string' &&
    canonicalIdentifierV2(value.contentType) &&
    Number.isSafeInteger(value.version) &&
    Number(value.version) >= 0 &&
    canonicalIdentifierV2(value.status) &&
    canonicalIdentifierV2(value.processingStatus) &&
    canonicalIdentifierV2(value.createdAt) &&
    (value.updatedAt === null || typeof value.updatedAt === 'string')
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
    'desktop_project_memories_operation_input_invalid',
    'desktop project memories operation input is invalid',
  );
}

function invalidServiceContractV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_memories_service_contract_invalid',
    'desktop project memories authority returned an invalid result',
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
