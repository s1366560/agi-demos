import {
  PROJECT_MEMORIES_DEGRADED_REASON,
  type ProjectMemory,
  type ProjectMemoriesPageOptions,
} from '../features/project-knowledge/projectMemoriesClient';
import {
  isRecord,
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import type { DesktopProjectMemoriesHttpAuthorityV2 } from './desktopProjectMemoriesHttpProjectionV2';
import { normalizeDesktopProjectMemoriesPageV2 } from './desktopProjectMemoriesOperationContractV2';
import type { NativeKnowledgeScope } from '../features/project-knowledge/nativeKnowledgeContracts';
import { requireNativeKnowledgeScope } from '../features/project-knowledge/nativeKnowledgeValidation';
import { createDesktopNativeKnowledgeSyncHttpV2 } from './desktopNativeKnowledgeSyncHttpV2';

const INVALID = 'local_project_memories_contract_invalid';
const SCOPE_KEYS = [
  'tenant_id',
  'project_id',
  'context_revision',
  'profile_id',
  'generation',
  'digest',
] as const;

export function createDesktopProjectMemoriesLocalAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
): DesktopProjectMemoriesHttpAuthorityV2 {
  return Object.freeze({
    ...createDesktopNativeKnowledgeSyncHttpV2(config, scope),
    async load(signal?: AbortSignal, options?: ProjectMemoriesPageOptions) {
      signal?.throwIfAborted();
      const pagination = normalizeDesktopProjectMemoriesPageV2(options);
      const offset = (pagination.page - 1) * pagination.pageSize;
      if (!Number.isSafeInteger(offset)) throw projectKnowledgeError(INVALID, 422);
      const context = await requestProjectKnowledgeJson(config, '/api/v1/knowledge/context', {
        signal,
      });
      const nativeScope = parseContext(context, scope);
      signal?.throwIfAborted();
      const payload = await requestProjectKnowledgeJson(config, '/api/v1/knowledge/query', {
        signal,
        method: 'POST',
        body: {
          scope: nativeScope,
          query: { operation: 'list', offset, limit: pagination.pageSize },
        },
      });
      signal?.throwIfAborted();
      const returnedScope = parseContext(payload, scope);
      if (SCOPE_KEYS.some((key) => nativeScope[key] !== returnedScope[key])) {
        throw projectKnowledgeError('project_knowledge_scope_conflict', 409);
      }
      if (!isRecord(payload) || !isRecord(payload.result)) throw projectKnowledgeError(INVALID);
      const page = payload.result;
      if (
        !Array.isArray(page.items) ||
        page.items.length > pagination.pageSize ||
        page.offset !== offset ||
        page.limit !== pagination.pageSize ||
        typeof page.has_more !== 'boolean' ||
        (page.has_more && page.items.length !== pagination.pageSize)
      ) {
        throw projectKnowledgeError(INVALID);
      }
      const memories = Object.freeze(page.items.map((item) => parseMemory(item, scope)));
      if (new Set(memories.map((memory) => memory.id)).size !== memories.length) {
        throw projectKnowledgeError(INVALID);
      }
      return Object.freeze({
        scope,
        scopeRevision: Number(nativeScope.context_revision),
        authority: 'local',
        availability: 'degraded',
        reasonCode: PROJECT_MEMORIES_DEGRADED_REASON,
        allowedActions: Object.freeze(['view', 'list']),
        memories,
        total: null,
        hasMore: page.has_more,
        ...pagination,
      });
    },
  });
}

function parseContext(value: unknown, scope: ProjectKnowledgeScope): NativeKnowledgeScope {
  if (!isRecord(value) || value.contract_version !== '1.0.0' || !isRecord(value.scope)) {
    throw projectKnowledgeError(INVALID);
  }
  return requireNativeKnowledgeScope(
    { contract_version: value.contract_version, scope: value.scope },
    scope,
  );
}

function parseMemory(value: unknown, scope: ProjectKnowledgeScope): ProjectMemory {
  if (!isRecord(value) || value.project_id !== scope.projectId) {
    throw projectKnowledgeError('project_memory_scope_conflict', 409);
  }
  if (!Number.isSafeInteger(value.created_at_ms)) throw projectKnowledgeError(INVALID);
  const created = new Date(Number(value.created_at_ms));
  if (!Number.isFinite(created.getTime())) throw projectKnowledgeError(INVALID);
  return Object.freeze({
    id: requireIdentifier(value.id, INVALID),
    projectId: scope.projectId,
    title: requireIdentifier(value.title, INVALID),
    content: requireText(value.content, INVALID),
    contentType: requireIdentifier(value.content_type, INVALID),
    version: requireNonnegativeInteger(value.version, INVALID),
    status: requireIdentifier(value.status, INVALID),
    // The portable record does not publish a processing job status.
    processingStatus: 'unavailable',
    createdAt: created.toISOString(),
    updatedAt: null,
  });
}
