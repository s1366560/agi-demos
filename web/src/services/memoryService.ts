/**
 * Memory Service - API calls for memory management
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
  updateMemory: async (memoryId: string, updates: MemoryUpdate): Promise<Response> => {
    const response = await fetch(`/api/v1/memories/${memoryId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(updates),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to update memory');
    }

    return response.json();
  },

  /**
   * Share a memory with a user or project
   */
  shareMemory: async (memoryId: string, shareData: MemoryShareCreate): Promise<MemoryShareResponse> => {
    const response = await fetch(`/api/v1/memories/${memoryId}/shares`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(shareData),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to share memory');
    }

    return response.json();
  },

  /**
   * Delete a memory share
   */
  deleteMemoryShare: async (memoryId: string, shareId: string): Promise<void> => {
    const response = await fetch(`/api/v1/memories/${memoryId}/shares/${shareId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to delete share');
    }
  },
};
