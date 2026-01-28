/**
 * Memory Service - Memory management API
 *
 * Provides methods for managing memories, including:
 * - Updating memory content and metadata
 * - Sharing memories with users and projects
 * - Managing memory sharing permissions
 *
 * @packageDocumentation
 *
 * @example
 * ```typescript
 * import { memoryService } from '@/services/memoryService';
 *
 * // Update a memory
 * await memoryService.updateMemory('mem-123', {
 *   title: 'Updated Title',
 *   content: 'Updated content',
 *   version: 1
 * });
 *
 * // Share a memory with a user
 * const share = await memoryService.shareMemory('mem-123', {
 *   target_type: 'user',
 *   target_id: 'user-456',
 *   permission_level: 'view'
 * });
 * ```
 */

import { apiFetch } from './client/urlUtils';

/**
 * Memory update data
 *
 * Used for updating an existing memory's content and metadata.
 * The version field is used for optimistic locking.
 *
 * @example
 * ```typescript
 * const update: MemoryUpdate = {
 *   title: 'New Title',
 *   content: 'New content',
 *   version: 1
 * };
 * ```
 */
interface MemoryUpdate {
  title?: string;
  content?: string;
  tags?: string[];
  entities?: any[];
  relationships?: any[];
  metadata?: Record<string, any>;
  version: number;
}

/**
 * Memory share creation data
 *
 * Used to share a memory with a user or project.
 *
 * @example
 * ```typescript
 * const share: MemoryShareCreate = {
 *   target_type: 'user',
 *   target_id: 'user-456',
 *   permission_level: 'view',
 *   expires_at: '2024-12-31T23:59:59Z'
 * };
 * ```
 */
interface MemoryShareCreate {
  target_type: 'user' | 'project';
  target_id: string;
  permission_level: 'view' | 'edit';
  expires_at?: string;
}

/**
 * Memory share response
 *
 * Represents a memory share with its details.
 *
 * @example
 * ```typescript
 * const share: MemoryShareResponse = {
 *   id: 'share-789',
 *   memory_id: 'mem-123',
 *   shared_with_user_id: 'user-456',
 *   shared_with_project_id: null,
 *   permission_level: 'view',
 *   shared_by: 'user-789',
 *   shared_at: '2024-01-01T00:00:00Z',
 *   expires_at: '2024-12-31T23:59:59Z'
 * };
 * ```
 */
interface MemoryShareResponse {
  id: string;
  memory_id: string;
  shared_with_user_id: string | null;
  shared_with_project_id: string | null;
  permission_level: string;
  shared_by: string;
  shared_at: string;
  expires_at: string | null;
}

export const memoryService = {
  /**
   * Update an existing memory
   *
   * Updates the content and metadata of an existing memory.
   * The version field must match the current version for optimistic locking.
   *
   * @param memoryId - The memory ID to update
   * @param updates - The update data including version for optimistic locking
   * @returns Promise resolving to the updated memory
   * @throws {ApiError} If memory doesn't exist or version doesn't match
   *
   * @example
   * ```typescript
   * const updated = await memoryService.updateMemory('mem-123', {
   *   title: 'Updated Title',
   *   content: 'Updated content',
   *   version: 1
   * });
   * ```
   */
  updateMemory: async (memoryId: string, updates: MemoryUpdate): Promise<unknown> => {
    const response = await apiFetch.patch(`/memories/${memoryId}`, updates);
    return response.json();
  },

  /**
   * Share a memory with a user or project
   *
   * Creates a new share for a memory, allowing others to access it.
   * Supports sharing with individual users or entire projects.
   *
   * @param memoryId - The memory ID to share
   * @param shareData - The share configuration
   * @param shareData.target_type - Whether to share with 'user' or 'project'
   * @param shareData.target_id - The user or project ID to share with
   * @param shareData.permission_level - Either 'view' or 'edit' permission
   * @param shareData.expires_at - Optional expiration date for the share
   * @returns Promise resolving to the created share
   * @throws {ApiError} If memory doesn't exist or share already exists
   *
   * @example
   * ```typescript
   * // Share with a user
   * const share = await memoryService.shareMemory('mem-123', {
   *   target_type: 'user',
   *   target_id: 'user-456',
   *   permission_level: 'view'
   * });
   *
   * // Share with a project with expiration
   * const projectShare = await memoryService.shareMemory('mem-123', {
   *   target_type: 'project',
   *   target_id: 'proj-789',
   *   permission_level: 'edit',
   *   expires_at: '2024-12-31T23:59:59Z'
   * });
   * ```
   */
  shareMemory: async (memoryId: string, shareData: MemoryShareCreate): Promise<MemoryShareResponse> => {
    const response = await apiFetch.post(`/memories/${memoryId}/shares`, shareData);
    return response.json();
  },

  /**
   * Delete a memory share
   *
   * Removes a share, revoking access to the memory for the target user or project.
   *
   * @param memoryId - The memory ID
   * @param shareId - The share ID to delete
   * @returns Promise that resolves when the share is deleted
   * @throws {ApiError} If memory or share doesn't exist
   *
   * @example
   * ```typescript
   * await memoryService.deleteMemoryShare('mem-123', 'share-789');
   * console.log('Share deleted');
   * ```
   */
  deleteMemoryShare: async (memoryId: string, shareId: string): Promise<void> => {
    await apiFetch.delete(`/memories/${memoryId}/shares/${shareId}`);
  },
};
