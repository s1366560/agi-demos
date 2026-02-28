/**
 * SWR-based Data Fetching Hooks
 *
 * Provides SWR (stale-while-revalidate) hooks for data fetching with:
 * - Automatic caching and request deduplication
 * - Error handling and retry mechanism
 * - Optimistic updates support
 *
 * @packageDocumentation
 *
 * @example
 * ```typescript
 * import { useProjectStats, useMemories, useProject } from '@/hooks/useSwr';
 *
 * function MyComponent() {
 *   const { data: stats, isLoading, error, mutate } = useProjectStats('proj-123');
 *
 *   if (isLoading) return <div>Loading...</div>;
 *   if (error) return <div>Error: {error.message}</div>;
 *
 *   return <div>Memory count: {stats?.memory_count}</div>;
 * }
 * ```
 */

import useSWR, { SWRConfiguration, mutate as globalMutate } from 'swr';

import { schemaAPI } from '@/services/api';
import { httpClient } from '@/services/client/httpClient';

import type {
  MemoryListResponse,
  Project,
  SchemaEntityType,
  SchemaEdgeType,
  EdgeMapping,
} from '@/types/memory';

/**
 * SWR Configuration Options
 *
 * Default configuration for all SWR hooks:
 * - dedupingInterval: 2000ms - deduplicate requests within 2 seconds
 * - revalidateOnFocus: false - don't revalidate when window regains focus
 * - revalidateOnReconnect: false - don't revalidate on network reconnect
 * - errorRetryCount: 3 - retry failed requests up to 3 times
 * - errorRetryInterval: 5000 - wait 5 seconds between retries
 */
const swrConfig: SWRConfiguration = {
  dedupingInterval: 2000,
  revalidateOnFocus: false,
  revalidateOnReconnect: false,
  errorRetryCount: 3,
  errorRetryInterval: 5000,
};

/**
 * Generate SWR cache key for API requests
 *
 * Creates a consistent key format for SWR cache.
 * Returns null if projectId is falsy, preventing the request.
 *
 * @param base - Base URL path
 * @param projectId - Project ID (optional)
 * @param params - Additional query parameters
 * @returns Cache key array or null
 */
function generateCacheKey(
  base: string,
  projectId: string | null | undefined,
  params: Record<string, unknown> = {}
): [string, Record<string, unknown>] | null {
  if (!projectId) {
    return null;
  }
  return [base, { ...params, project_id: projectId }];
}

/**
 * Hook return type extending SWR response
 */
export interface SwrHookResponse<T> {
  /** The fetched data */
  data: T | undefined;
  /** Error object if request failed */
  error: Error | undefined;
  /** Whether the request is in progress */
  isLoading: boolean;
  /** Whether a revalidation is in progress */
  isValidating: boolean;
  /** Function to manually revalidate or mutate the cache */
  mutate: (
    data?: T | Promise<T> | MutatorCallback<T>,
    shouldRevalidate?: boolean
  ) => Promise<T | undefined>;
}

/**
 * useProjectStats Hook
 *
 * Fetches project statistics including memory count, storage usage,
 * active nodes, and collaborator count.
 *
 * @param projectId - The project ID to fetch stats for
 * @param config - Optional SWR configuration overrides
 * @returns SWR response with project stats
 *
 * @example
 * ```typescript
 * const { data: stats, isLoading, error } = useProjectStats('proj-123');
 *
 * if (stats) {
 *   console.log('Memory count:', stats.memory_count);
 *   console.log('Storage used:', stats.storage_used);
 * }
 * ```
 */
export function useProjectStats(
  projectId: string | null | undefined,
  config?: SWRConfiguration
): SwrHookResponse<ProjectStats> {
  const cacheKey = generateCacheKey(
    `/projects/${projectId}/stats`,
    projectId ? projectId.toString() : null
  );

  const swrResponse = useSWR<ProjectStats>(
    cacheKey,
    () => httpClient.get<ProjectStats>(`/projects/${projectId}/stats`),
    { ...swrConfig, ...config }
  );

  return {
    data: swrResponse.data,
    error: swrResponse.error,
    isLoading: swrResponse.isLoading,
    isValidating: swrResponse.isValidating,
    mutate: swrResponse.mutate,
  };
}

/**
 * useMemories Hook
 *
 * Fetches memories for a project with pagination support.
 *
 * @param projectId - The project ID to fetch memories for
 * @param params - Query parameters (page, page_size, etc.)
 * @param config - Optional SWR configuration overrides
 * @returns SWR response with memories list
 *
 * @example
 * ```typescript
 * const { data: memoriesData, isLoading } = useMemories('proj-123', {
 *   page: 1,
 *   page_size: 20
 * });
 *
 * if (memoriesData) {
 *   console.log('Memories:', memoriesData.memories);
 *   console.log('Total:', memoriesData.total);
 * }
 * ```
 */
export function useMemories(
  projectId: string | null | undefined,
  params: {
    page?: number | undefined;
    page_size?: number | undefined;
    [key: string]: unknown;
  } = {},
  config?: SWRConfiguration
): SwrHookResponse<MemoryListResponse> {
  const cacheKey = generateCacheKey('/memories/', projectId, params);

  const swrResponse = useSWR<MemoryListResponse>(
    cacheKey,
    () =>
      httpClient.get<MemoryListResponse>('/memories/', {
        params: { ...params, project_id: projectId },
      }),
    { ...swrConfig, ...config }
  );

  return {
    data: swrResponse.data,
    error: swrResponse.error,
    isLoading: swrResponse.isLoading,
    isValidating: swrResponse.isValidating,
    mutate: swrResponse.mutate,
  };
}

/**
 * useProject Hook
 *
 * Fetches project details including name, description, and metadata.
 *
 * @param projectId - The project ID to fetch details for
 * @param config - Optional SWR configuration overrides
 * @returns SWR response with project details
 *
 * @example
 * ```typescript
 * const { data: project, isLoading, error } = useProject('proj-123');
 *
 * if (project) {
 *   console.log('Project name:', project.name);
 *   console.log('Description:', project.description);
 * }
 * ```
 */
export function useProject(
  projectId: string | null | undefined,
  config?: SWRConfiguration
): SwrHookResponse<Project> {
  const cacheKey = projectId ? `/projects/${projectId}` : null;

  const swrResponse = useSWR<Project>(
    cacheKey,
    () => httpClient.get<Project>(`/projects/${projectId}`),
    { ...swrConfig, ...config }
  );

  return {
    data: swrResponse.data,
    error: swrResponse.error,
    isLoading: swrResponse.isLoading,
    isValidating: swrResponse.isValidating,
    mutate: swrResponse.mutate,
  };
}

/**
 * useEntityTypes Hook
 *
 * Fetches entity types for a project schema.
 *
 * @param projectId - The project ID to fetch entity types for
 * @param config - Optional SWR configuration overrides
 * @returns SWR response with entity types
 */
export function useEntityTypes(
  projectId: string | null | undefined,
  config?: SWRConfiguration
): SwrHookResponse<SchemaEntityType[]> {
  const cacheKey = projectId ? `/projects/${projectId}/schema/entities` : null;

  const swrResponse = useSWR<SchemaEntityType[]>(
    cacheKey,
    () => schemaAPI.listEntityTypes(projectId!),
    { ...swrConfig, ...config }
  );

  return {
    data: swrResponse.data,
    error: swrResponse.error,
    isLoading: swrResponse.isLoading,
    isValidating: swrResponse.isValidating,
    mutate: swrResponse.mutate,
  };
}

/**
 * useEdgeTypes Hook
 *
 * Fetches edge types for a project schema.
 *
 * @param projectId - The project ID to fetch edge types for
 * @param config - Optional SWR configuration overrides
 * @returns SWR response with edge types
 */
export function useEdgeTypes(
  projectId: string | null | undefined,
  config?: SWRConfiguration
): SwrHookResponse<SchemaEdgeType[]> {
  const cacheKey = projectId ? `/projects/${projectId}/schema/edges` : null;

  const swrResponse = useSWR<SchemaEdgeType[]>(
    cacheKey,
    () => schemaAPI.listEdgeTypes(projectId!),
    { ...swrConfig, ...config }
  );

  return {
    data: swrResponse.data,
    error: swrResponse.error,
    isLoading: swrResponse.isLoading,
    isValidating: swrResponse.isValidating,
    mutate: swrResponse.mutate,
  };
}

/**
 * useEdgeMaps Hook
 *
 * Fetches edge maps for a project schema.
 *
 * @param projectId - The project ID to fetch edge maps for
 * @param config - Optional SWR configuration overrides
 * @returns SWR response with edge maps
 */
export function useEdgeMaps(
  projectId: string | null | undefined,
  config?: SWRConfiguration
): SwrHookResponse<EdgeMapping[]> {
  const cacheKey = projectId ? `/projects/${projectId}/schema/edge-maps` : null;

  const swrResponse = useSWR<EdgeMapping[]>(cacheKey, () => schemaAPI.listEdgeMaps(projectId!), {
    ...swrConfig,
    ...config,
  });

  return {
    data: swrResponse.data,
    error: swrResponse.error,
    isLoading: swrResponse.isLoading,
    isValidating: swrResponse.isValidating,
    mutate: swrResponse.mutate,
  };
}

/**
 * useSchemaData Hook
 *
 * Fetches all schema data (entities, edges, mappings) for a project.
 * Combines multiple hooks for efficient parallel fetching with automatic deduplication.
 *
 * @param projectId - The project ID to fetch schema data for
 * @param config - Optional SWR configuration overrides
 * @returns Combined SWR response with all schema data
 */
export function useSchemaData(
  projectId: string | null | undefined,
  config?: SWRConfiguration
): {
  entities: SchemaEntityType[] | undefined;
  edges: SchemaEdgeType[] | undefined;
  mappings: EdgeMapping[] | undefined;
  isLoading: boolean;
  isValidating: boolean;
  error: Error | undefined;
  mutate: {
    entities: (
      data?: SchemaEntityType[] | Promise<SchemaEntityType[]>
    ) => Promise<SchemaEntityType[] | undefined>;
    edges: (
      data?: SchemaEdgeType[] | Promise<SchemaEdgeType[]>
    ) => Promise<SchemaEdgeType[] | undefined>;
    mappings: (data?: EdgeMapping[] | Promise<EdgeMapping[]>) => Promise<EdgeMapping[] | undefined>;
  };
} {
  const entities = useEntityTypes(projectId, config);
  const edges = useEdgeTypes(projectId, config);
  const mappings = useEdgeMaps(projectId, config);

  return {
    entities: entities.data,
    edges: edges.data,
    mappings: mappings.data,
    isLoading: entities.isLoading || edges.isLoading || mappings.isLoading,
    isValidating: entities.isValidating || edges.isValidating || mappings.isValidating,
    error: entities.error || edges.error || mappings.error,
    mutate: {
      entities: entities.mutate,
      edges: edges.mutate,
      mappings: mappings.mutate,
    },
  };
}

/**
 * Global revalidation utilities
 */
export const swrUtils = {
  /**
   * Revalidate all SWR caches
   */
  revalidateAll: () => globalMutate(() => true, undefined, true),

  /**
   * Clear all SWR caches
   */
  clearCache: () => globalMutate(() => true, undefined, false),

  /**
   * Revalidate a specific cache key
   */
  revalidateKey: (key: string) => globalMutate(key),
};

// Re-export types for convenience
export type { MemoryListResponse, Project } from '@/types/memory';

/**
 * Project Statistics Response
 */
export interface ProjectStats {
  memory_count: number;
  storage_used: number;
  storage_limit: number;
  active_nodes: number;
  collaborators: number;
}

/**
 * Schema Types Response
 */
export interface EntityTypesResponse {
  entities: SchemaEntityType[];
  total: number;
}

export interface EdgeTypesResponse {
  edges: SchemaEdgeType[];
  total: number;
}

export interface EdgeMapsResponse {
  mappings: EdgeMapping[];
  total: number;
}

// Re-export schema types from memory.ts for convenience
export type { SchemaEntityType as EntityType, SchemaEdgeType as EdgeType, EdgeMapping as EdgeMap };

/**
 * SWR Mutator Callback Type
 * Re-exported for convenience
 */
export type MutatorCallback<T> = (current?: T) => T;
