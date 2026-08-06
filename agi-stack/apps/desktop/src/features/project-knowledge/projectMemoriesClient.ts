import type { DesktopRuntimeConfig } from '../../types';
import {
  isRecord,
  observeProjectKnowledgeScope,
  optionalText,
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  requestProjectKnowledgeNoContent,
  requireIdentifier,
  requireNonnegativeInteger,
  requireProjectKnowledgeScope,
  requireText,
  type ProjectKnowledgeClient,
  type ProjectKnowledgeReadOptions,
  type ProjectKnowledgeScope,
  type ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';

export const PROJECT_MEMORIES_ROUTE_ID = 'project-project-memories' as const;
export const PROJECT_MEMORIES_LOCAL_REASON =
  'local_project_memories_authority_unavailable' as const;
export const PROJECT_MEMORIES_DEGRADED_REASON =
  'project_memories_export_file_ipc_unavailable' as const;

export type ProjectMemory = Readonly<{
  id: string;
  projectId: string;
  title: string;
  content: string;
  contentType: string;
  version: number;
  status: string;
  processingStatus: string;
  createdAt: string;
  updatedAt: string | null;
}>;
export type ProjectMemoryInput = Readonly<{
  title: string;
  content: string;
  contentType?: string;
}>;
export type ProjectMemoryUpdate = Readonly<{
  title?: string;
  content?: string;
  version: number;
}>;
export type ProjectMemoriesSnapshot = ProjectKnowledgeSnapshotBase &
  Readonly<{ memories: readonly ProjectMemory[]; total: number }>;
export type ProjectMemoriesClient = ProjectKnowledgeClient<ProjectMemoriesSnapshot> &
  Readonly<{
    create(
      scope: ProjectKnowledgeScope,
      input: ProjectMemoryInput,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<ProjectMemory>;
    update(
      scope: ProjectKnowledgeScope,
      memoryId: string,
      input: ProjectMemoryUpdate,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<ProjectMemory>;
    remove(
      scope: ProjectKnowledgeScope,
      memoryId: string,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<void>;
    reprocess(
      scope: ProjectKnowledgeScope,
      memoryId: string,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<ProjectMemory>;
  }>;

const ACTIONS = Object.freeze(['view', 'list', 'create', 'update', 'delete', 'reprocess']);

export function createProjectMemoriesClient(config: DesktopRuntimeConfig): ProjectMemoriesClient {
  const runtimeConfig = Object.freeze({ ...config });
  const withScope = (scope: ProjectKnowledgeScope) =>
    requireProjectKnowledgeScope(runtimeConfig, scope, PROJECT_MEMORIES_LOCAL_REASON);
  const client: ProjectMemoriesClient = {
    async load(scope, options) {
      const currentScope = withScope(scope);
      const scopeRevision = await observeProjectKnowledgeScope(
        runtimeConfig,
        currentScope,
        options,
      );
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        `${memoryRoot()}?project_id=${encodeURIComponent(currentScope.projectId)}` +
          '&page=1&page_size=50',
        options,
      );
      const page = parseMemoryPage(payload, currentScope.projectId);
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_MEMORIES_DEGRADED_REASON,
        allowedActions: ACTIONS,
        ...page,
      });
    },
    async create(scope, input, options) {
      const currentScope = withScope(scope);
      const payload = await requestProjectKnowledgeJson(runtimeConfig, memoryRoot(), {
        ...options,
        method: 'POST',
        body: {
          project_id: currentScope.projectId,
          title: requireIdentifier(input.title, 'project_memory_title_required'),
          content: requireText(input.content, 'project_memory_content_required'),
          content_type: input.contentType ?? 'text',
        },
      });
      return parseMemory(payload, currentScope.projectId);
    },
    async update(scope, memoryId, input, options) {
      const currentScope = withScope(scope);
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        memoryPath(memoryId),
        {
          ...options,
          method: 'PATCH',
          body: {
            ...(input.title === undefined
              ? {}
              : { title: requireIdentifier(input.title, 'project_memory_title_required') }),
            ...(input.content === undefined
              ? {}
              : { content: requireText(input.content, 'project_memory_content_required') }),
            version: requireNonnegativeInteger(input.version, 'project_memory_version_required'),
          },
        },
      );
      return parseMemory(payload, currentScope.projectId);
    },
    async remove(scope, memoryId, options) {
      withScope(scope);
      await requestProjectKnowledgeNoContent(runtimeConfig, memoryPath(memoryId), {
        ...options,
        method: 'DELETE',
      });
    },
    async reprocess(scope, memoryId, options) {
      const currentScope = withScope(scope);
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        `${memoryPath(memoryId)}/reprocess`,
        { ...options, method: 'POST' },
      );
      return parseMemory(payload, currentScope.projectId);
    },
  };
  return Object.freeze(client);
}

function memoryRoot(): string {
  return '/api/v1/memories/';
}

function memoryPath(memoryId: string): string {
  const id = requireIdentifier(memoryId, 'project_memory_id_required');
  return `/api/v1/memories/${encodeURIComponent(id)}`;
}

function parseMemoryPage(
  payload: unknown,
  projectId: string,
): Readonly<{ memories: readonly ProjectMemory[]; total: number }> {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.memories) ||
    payload.page !== 1 ||
    payload.page_size !== 50
  ) {
    throw projectKnowledgeError('project_memories_page_contract_invalid');
  }
  const memories = Object.freeze(payload.memories.map((value) => parseMemory(value, projectId)));
  const total = requireNonnegativeInteger(payload.total, 'project_memories_page_contract_invalid');
  if (total < memories.length) {
    throw projectKnowledgeError('project_memories_page_contract_invalid');
  }
  return Object.freeze({ memories, total });
}

function parseMemory(payload: unknown, projectId: string): ProjectMemory {
  if (!isRecord(payload) || payload.project_id !== projectId) {
    throw projectKnowledgeError('project_memory_scope_conflict', 409);
  }
  return Object.freeze({
    id: requireIdentifier(payload.id, 'project_memory_contract_invalid'),
    projectId,
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
