/**
 * Memory Service - API calls for memory management
 *
 * Uses apiFetch which automatically throws ApiError for non-success responses.
 * No manual error handling needed - errors propagate to callers.
 */

import { apiFetch } from './client/urlUtils';

interface MemoryUpdate {
  title?: string;
  content?: string;
  tags?: string[];
  entities?: any[];
  relationships?: any[];
  metadata?: Record<string, any>;
  version: number;
}

interface MemoryShareCreate {
  target_type: 'user' | 'project';
  target_id: string;
  permission_level: 'view' | 'edit';
  expires_at?: string;
}

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
   */
  updateMemory: async (memoryId: string, updates: MemoryUpdate): Promise<unknown> => {
    const response = await apiFetch.patch(`/memories/${memoryId}`, updates);
    return response.json();
  },

  /**
   * Share a memory with a user or project
   */
  shareMemory: async (memoryId: string, shareData: MemoryShareCreate): Promise<MemoryShareResponse> => {
    const response = await apiFetch.post(`/memories/${memoryId}/shares`, shareData);
    return response.json();
  },

  /**
   * Delete a memory share
   */
  deleteMemoryShare: async (memoryId: string, shareId: string): Promise<void> => {
    await apiFetch.delete(`/memories/${memoryId}/shares/${shareId}`);
  },
};
