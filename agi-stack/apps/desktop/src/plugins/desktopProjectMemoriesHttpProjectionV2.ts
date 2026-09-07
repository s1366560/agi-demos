import {
  PROJECT_MEMORIES_DEGRADED_REASON,
  PROJECT_MEMORIES_LOCAL_REASON,
  type ProjectMemoriesSnapshot,
  type ProjectMemory,
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
import {
  cloneDesktopProjectMemoriesRuntimeConfigV2,
  cloneDesktopProjectMemoriesScopeV2,
} from './desktopProjectMemoriesOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view', 'list']);

export type DesktopProjectMemoriesHttpAuthorityV2 = Readonly<{
  load: (signal?: AbortSignal) => Promise<ProjectMemoriesSnapshot>;
}>;

export function createDesktopProjectMemoriesHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope
): DesktopProjectMemoriesHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectMemoriesRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectMemoriesScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(signal) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        operationScope,
        PROJECT_MEMORIES_LOCAL_REASON
      );
      const scopeRevision = await observeProjectKnowledgeScope(runtimeConfig, currentScope, {
        signal,
      });
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        memoryListPathV2(currentScope),
        { signal }
      );
      const page = parseMemoryPageV2(payload, currentScope);
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

function memoryListPathV2(scope: ProjectKnowledgeScope): string {
  return (
    '/api/v1/memories/?project_id=' + encodeURIComponent(scope.projectId) + '&page=1&page_size=50'
  );
}

function parseMemoryPageV2(
  payload: unknown,
  scope: ProjectKnowledgeScope
): Readonly<{ memories: readonly ProjectMemory[]; total: number }> {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.memories) ||
    payload.page !== 1 ||
    payload.page_size !== 50
  ) {
    throw projectKnowledgeError('project_memories_page_contract_invalid');
  }
  const memories = Object.freeze(payload.memories.map((value) => parseMemoryV2(value, scope)));
  const total = requireNonnegativeInteger(payload.total, 'project_memories_page_contract_invalid');
  if (total < memories.length) {
    throw projectKnowledgeError('project_memories_page_contract_invalid');
  }
  return Object.freeze({ memories, total });
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
      'project_memory_contract_invalid'
    ),
    createdAt: requireIdentifier(payload.created_at, 'project_memory_contract_invalid'),
    updatedAt: optionalText(payload.updated_at, 'project_memory_contract_invalid'),
  });
}
