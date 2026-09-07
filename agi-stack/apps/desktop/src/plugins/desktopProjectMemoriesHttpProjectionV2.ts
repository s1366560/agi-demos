import {
  PROJECT_MEMORIES_DEGRADED_REASON,
  PROJECT_MEMORIES_LOCAL_REASON,
  type ProjectMemoriesSnapshot,
  type ProjectMemory,
  type ProjectMemoriesPageOptions,
} from '../features/project-knowledge/projectMemoriesClient';
import {
  isRecord,
  observeProjectKnowledgeScope,
  optionalText,
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  requireIdentifier,
  requireNonnegativeInteger,
  requireProjectKnowledgeScope,
  requireText,
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import { createDesktopProjectMemoriesLocalAuthorityV2 } from './desktopProjectMemoriesLocalProjectionV2';
import type { NativeKnowledgeSyncAuthority } from '../features/project-knowledge/nativeKnowledgeContracts';
import { createDesktopNativeKnowledgeSyncHttpV2 } from './desktopNativeKnowledgeSyncHttpV2';
import {
  cloneDesktopProjectMemoriesRuntimeConfigV2,
  cloneDesktopProjectMemoriesScopeV2,
  normalizeDesktopProjectMemoriesPageV2,
} from './desktopProjectMemoriesOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view', 'list']);

export type DesktopProjectMemoriesHttpAuthorityV2 = NativeKnowledgeSyncAuthority &
  Readonly<{
    load: (
      signal?: AbortSignal,
      options?: ProjectMemoriesPageOptions,
    ) => Promise<ProjectMemoriesSnapshot>;
  }>;

export function createDesktopProjectMemoriesHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
): DesktopProjectMemoriesHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectMemoriesRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectMemoriesScopeV2(scope, runtimeConfig);
  if (runtimeConfig.mode === 'local') {
    return createDesktopProjectMemoriesLocalAuthorityV2(runtimeConfig, operationScope);
  }
  return Object.freeze({
    ...createDesktopNativeKnowledgeSyncHttpV2(runtimeConfig, operationScope),
    async load(signal?: AbortSignal, options?: ProjectMemoriesPageOptions) {
      const pagination = normalizeDesktopProjectMemoriesPageV2(options);
      signal?.throwIfAborted();
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        operationScope,
        PROJECT_MEMORIES_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectKnowledgeScope(runtimeConfig, currentScope, {
        signal,
      });
      signal?.throwIfAborted();
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        memoryListPathV2(currentScope, pagination),
        { signal },
      );
      signal?.throwIfAborted();
      const page = parseMemoryPageV2(payload, currentScope, pagination);
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_MEMORIES_DEGRADED_REASON,
        allowedActions: ACTIONS_V2,
        ...page,
      });
    },
  });
}

function memoryListPathV2(
  scope: ProjectKnowledgeScope,
  pagination: Readonly<{ page: number; pageSize: number }>,
): string {
  return (
    '/api/v1/memories/?project_id=' +
    encodeURIComponent(scope.projectId) +
    `&page=${pagination.page}&page_size=${pagination.pageSize}`
  );
}

function parseMemoryPageV2(
  payload: unknown,
  scope: ProjectKnowledgeScope,
  pagination: Readonly<{ page: number; pageSize: number }>,
): Readonly<{ memories: readonly ProjectMemory[]; total: number; page: number; pageSize: number }> {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.memories) ||
    payload.page !== pagination.page ||
    payload.page_size !== pagination.pageSize ||
    payload.memories.length > pagination.pageSize
  ) {
    throw projectKnowledgeError('project_memories_page_contract_invalid');
  }
  const memories = Object.freeze(payload.memories.map((value) => parseMemoryV2(value, scope)));
  const total = requireNonnegativeInteger(payload.total, 'project_memories_page_contract_invalid');
  if (total < memories.length) {
    throw projectKnowledgeError('project_memories_page_contract_invalid');
  }
  return Object.freeze({ memories, total, ...pagination });
}

function parseMemoryV2(payload: unknown, scope: ProjectKnowledgeScope): ProjectMemory {
  if (!isRecord(payload) || payload.project_id !== scope.projectId) {
    throw projectKnowledgeError('project_memory_scope_conflict', 409);
  }
  return Object.freeze({
    id: requireIdentifier(payload.id, 'project_memory_contract_invalid'),
    projectId: scope.projectId,
    title: requireIdentifier(payload.title, 'project_memory_contract_invalid'),
    content: requireText(payload.content, 'project_memory_contract_invalid'),
    contentType: requireIdentifier(payload.content_type, 'project_memory_contract_invalid'),
    version: requireNonnegativeInteger(payload.version, 'project_memory_contract_invalid'),
    status: requireIdentifier(payload.status, 'project_memory_contract_invalid'),
    processingStatus: requireIdentifier(
      payload.processing_status,
      'project_memory_contract_invalid',
    ),
    createdAt: requireIdentifier(payload.created_at, 'project_memory_contract_invalid'),
    updatedAt: optionalText(payload.updated_at, 'project_memory_contract_invalid'),
  });
}
