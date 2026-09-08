import { createDesktopNativeKnowledgeConnectionHttpV2 } from './desktopNativeKnowledgeConnectionHttpV2';
import type { NativeKnowledgeCloudConnectionAuthority } from '../features/project-knowledge/nativeKnowledgeCloudConnectionClient';
import {
  createDesktopNativeKnowledgeProcessingHttpV2,
  type DesktopNativeKnowledgeProcessingHttpV2,
  type NativeKnowledgeProcessingCapabilityGetter,
} from './desktopNativeKnowledgeProcessingHttpV2';
import type {
  CloudMemoryCommand,
  CloudMemoryOptions,
  CloudMemoryResponse,
} from '../features/project-knowledge/cloudMemoryClient';
import { createDesktopCloudMemoryHttpV2 } from './desktopCloudMemoryHttpV2';
import { parseMemoryV2 } from '../features/project-knowledge/cloudMemoryProjection';
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
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  requireIdentifier,
  requireNonnegativeInteger,
  requireProjectKnowledgeScope,
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import { DesktopApiError } from '../api/client';
import { parseCloudMemoryCapabilities } from '../features/project-knowledge/cloudMemoryCapabilities';
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
  Partial<NativeKnowledgeCloudConnectionAuthority> &
  Partial<DesktopNativeKnowledgeProcessingHttpV2> &
  Readonly<{
    executeCloudMemory?: <C extends CloudMemoryCommand>(
      command: C,
      options: CloudMemoryOptions,
    ) => Promise<CloudMemoryResponse<C>>;
    load: (
      signal?: AbortSignal,
      options?: ProjectMemoriesPageOptions,
    ) => Promise<ProjectMemoriesSnapshot>;
  }>;

export function createDesktopProjectMemoriesHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
  getCapability?: NativeKnowledgeProcessingCapabilityGetter,
): DesktopProjectMemoriesHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectMemoriesRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectMemoriesScopeV2(scope, runtimeConfig);
  if (runtimeConfig.mode === 'local') {
    return Object.freeze({
      ...createDesktopProjectMemoriesLocalAuthorityV2(runtimeConfig, operationScope),
      ...createDesktopNativeKnowledgeConnectionHttpV2(runtimeConfig, operationScope),
      ...createDesktopNativeKnowledgeProcessingHttpV2(runtimeConfig, operationScope, getCapability),
    });
  }
  const cloud = createDesktopCloudMemoryHttpV2(runtimeConfig);
  return Object.freeze({
    executeCloudMemory<C extends CloudMemoryCommand>(
      command: C,
      options: CloudMemoryOptions,
    ): Promise<CloudMemoryResponse<C>> {
      return cloud.execute(operationScope, command, options);
    },
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
      let commandCapabilities = null;
      if (isRecord(payload) && isRecord(payload.command_capabilities)) {
        const identity = await requestProjectKnowledgeJson(runtimeConfig, '/api/v1/auth/me', {
          signal,
        }).catch((error: unknown) => {
          signal?.throwIfAborted();
          if (error instanceof DesktopApiError && (error.status === 404 || error.status >= 500))
            return null;
          throw error;
        });
        signal?.throwIfAborted();
        if (identity !== null) {
          if (!isRecord(identity)) throw projectKnowledgeError('project_memory_identity_invalid');
          const actorId = requireIdentifier(identity.user_id, 'project_memory_identity_invalid');
          commandCapabilities = parseCloudMemoryCapabilities(
            payload.command_capabilities,
            currentScope,
            page.memories,
            actorId,
          );
        }
      }
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_MEMORIES_DEGRADED_REASON,
        allowedActions: ACTIONS_V2,
        ...page,
        ...(commandCapabilities === null ? {} : { commandCapabilities }),
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
): Readonly<{
  memories: readonly ProjectMemory[];
  total: number;
  page: number;
  pageSize: number;
}> {
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
