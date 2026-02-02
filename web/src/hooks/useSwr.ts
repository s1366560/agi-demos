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

import useSWR, { SWRConfiguration, mutate as globalMutate } from 'swr'
import { httpClient } from '@/services/client/httpClient'
import type { MemoryListResponse, Project } from '@/types/memory'

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
}

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
    return null
  }
  return [base, { ...params, project_id: projectId }]
}

/**
 * Hook return type extending SWR response
 */
export interface SwrHookResponse<T> {
  /** The fetched data */
  data: T | undefined
  /** Error object if request failed */
  error: Error | undefined
  /** Whether the request is in progress */
  isLoading: boolean
  /** Whether a revalidation is in progress */
  isValidating: boolean
  /** Function to manually revalidate or mutate the cache */
  mutate: (
    data?: T | Promise<T> | MutatorCallback<T>,
    shouldRevalidate?: boolean
  ) => Promise<T | undefined>
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
  const cacheKey = generateCacheKey(`/projects/${projectId}/stats`, projectId ? projectId.toString() : null)

  const swrResponse = useSWR<ProjectStats>(
    cacheKey,
    () => httpClient.get<ProjectStats>(`/projects/${projectId}/stats`),
    { ...swrConfig, ...config }
  )

  return {
    data: swrResponse.data,
    error: swrResponse.error,
    isLoading: swrResponse.isLoading,
    isValidating: swrResponse.isValidating,
    mutate: swrResponse.mutate,
  }
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
  params: { page?: number; page_size?: number; [key: string]: unknown } = {},
  config?: SWRConfiguration
): SwrHookResponse<MemoryListResponse> {
  const cacheKey = generateCacheKey('/memories/', projectId, params)

  const swrResponse = useSWR<MemoryListResponse>(
    cacheKey,
    () => httpClient.get<MemoryListResponse>('/memories/', { params: { ...params, project_id: projectId } }),
    { ...swrConfig, ...config }
  )

  return {
    data: swrResponse.data,
    error: swrResponse.error,
    isLoading: swrResponse.isLoading,
    isValidating: swrResponse.isValidating,
    mutate: swrResponse.mutate,
  }
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
  const cacheKey = projectId ? `/projects/${projectId}` : null

  const swrResponse = useSWR<Project>(
    cacheKey,
    () => httpClient.get<Project>(`/projects/${projectId}`),
    { ...swrConfig, ...config }
  )

  return {
    data: swrResponse.data,
    error: swrResponse.error,
    isLoading: swrResponse.isLoading,
    isValidating: swrResponse.isValidating,
    mutate: swrResponse.mutate,
  }
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
}

// Re-export types for convenience
export type { MemoryListResponse, Project } from '@/types/memory'

/**
 * Project Statistics Response
 */
export interface ProjectStats {
  memory_count: number
  storage_used: number
  storage_limit: number
  active_nodes: number
  collaborators: number
}

/**
 * SWR Mutator Callback Type
 * Re-exported for convenience
 */
export type MutatorCallback<T> = (current?: T) => T
