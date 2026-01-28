/**
 * Project Service - API calls for project management
 *
 * Uses apiFetch which automatically throws ApiError for non-success responses.
 * No manual error handling needed - errors propagate to callers.
 */

import { apiFetch } from './client/urlUtils';

interface User {
  id: string;
  email: string;
  name: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  created_at: string;
  last_login?: string;
  is_active: boolean;
}

interface Project {
  id: string;
  name: string;
  description?: string;
  tenant_id: string;
  owner_id: string;
  member_ids: string[];
  is_public: boolean;
  created_at: string;
  updated_at?: string;
}

export const projectService = {
  /**
   * List all members of a project
   */
  listMembers: async (projectId: string): Promise<{ users: User[] }> => {
    const response = await apiFetch.get(`/projects/${projectId}/members`);
    return response.json();
  },

  /**
   * Add a member to a project
   */
  addMember: async (projectId: string, userId: string, role: string): Promise<void> => {
    await apiFetch.post(`/projects/${projectId}/members`, { user_id: userId, role });
  },

  /**
   * Remove a member from a project
   */
  removeMember: async (projectId: string, userId: string): Promise<void> => {
    await apiFetch.delete(`/projects/${projectId}/members/${userId}`);
  },

  /**
   * Update a member's role in a project
   */
  updateMemberRole: async (projectId: string, userId: string, role: string): Promise<void> => {
    await apiFetch.patch(`/projects/${projectId}/members/${userId}`, { role });
  },

  /**
   * Get project details
   */
  getProject: async (projectId: string): Promise<Project> => {
    const response = await apiFetch.get(`/projects/${projectId}`);
    return response.json();
  },

  /**
   * Update project details
   */
  updateProject: async (projectId: string, updates: Partial<Project>): Promise<Project> => {
    const response = await apiFetch.patch(`/projects/${projectId}`, updates);
    return response.json();
  },

  /**
   * Delete a project
   */
  deleteProject: async (projectId: string): Promise<void> => {
    await apiFetch.delete(`/projects/${projectId}`);
  },

  /**
   * List projects in a tenant
   */
  listProjects: async (tenantId: string): Promise<Project[]> => {
    const response = await apiFetch.get(`/tenants/${tenantId}/projects`);
    const data = await response.json();
    return data.projects || [];
  },
};
