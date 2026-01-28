/**
 * Project Service - Project management API
 *
 * Provides methods for managing projects and their members, including:
 * - Creating, updating, and deleting projects
 * - Managing project membership and roles
 * - Listing projects in a tenant
 *
 * @packageDocumentation
 *
 * @example
 * ```typescript
 * import { projectService } from '@/services/projectService';
 *
 * // List projects in a tenant
 * const projects = await projectService.listProjects('tenant-123');
 *
 * // Update a project
 * const updated = await projectService.updateProject('proj-123', {
 *   name: 'New Name',
 *   description: 'New description'
 * });
 *
 * // Add a member
 * await projectService.addMember('proj-123', 'user-456', 'member');
 * ```
 */

import { apiFetch } from './client/urlUtils';

/**
 * Project user with role
 *
 * Represents a user who is a member of a project.
 *
 * @example
 * ```typescript
 * const user: User = {
 *   id: 'user-123',
 *   email: 'user@example.com',
 *   name: 'John Doe',
 *   role: 'member',
 *   created_at: '2024-01-01T00:00:00Z',
 *   last_login: '2024-01-15T10:30:00Z',
 *   is_active: true
 * };
 * ```
 */
interface User {
  id: string;
  email: string;
  name: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  created_at: string;
  last_login?: string;
  is_active: boolean;
}

/**
 * Project entity
 *
 * Represents a project with its configuration and membership.
 *
 * @example
 * ```typescript
 * const project: Project = {
 *   id: 'proj-123',
 *   name: 'My Project',
 *   description: 'Project description',
 *   tenant_id: 'tenant-456',
 *   owner_id: 'user-789',
 *   member_ids: ['user-789', 'user-456'],
 *   is_public: false,
 *   created_at: '2024-01-01T00:00:00Z',
 *   updated_at: '2024-01-15T10:30:00Z'
 * };
 * ```
 */
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
   *
   * Retrieves all users who are members of a project.
   *
   * @param projectId - The project ID
   * @returns Promise resolving to a list of users
   * @throws {ApiError} If project doesn't exist or user lacks access
   *
   * @example
   * ```typescript
   * const { users } = await projectService.listMembers('proj-123');
   * console.log('Members:', users);
   * ```
   */
  listMembers: async (projectId: string): Promise<{ users: User[] }> => {
    const response = await apiFetch.get(`/projects/${projectId}/members`);
    return response.json();
  },

  /**
   * Add a member to a project
   *
   * Adds a user as a member of a project with the specified role.
   *
   * @param projectId - The project ID
   * @param userId - The user ID to add as a member
   * @param role - The role to assign ("owner" | "admin" | "member" | "viewer")
   * @returns Promise that resolves when the member is added
   * @throws {ApiError} If project or user doesn't exist
   *
   * @example
   * ```typescript
   * await projectService.addMember('proj-123', 'user-456', 'member');
   * console.log('Member added');
   * ```
   */
  addMember: async (projectId: string, userId: string, role: string): Promise<void> => {
    await apiFetch.post(`/projects/${projectId}/members`, { user_id: userId, role });
  },

  /**
   * Remove a member from a project
   *
   * Removes a user from a project's membership.
   *
   * @param projectId - The project ID
   * @param userId - The user ID to remove
   * @returns Promise that resolves when the member is removed
   * @throws {ApiError} If project doesn't exist or user is not a member
   *
   * @example
   * ```typescript
   * await projectService.removeMember('proj-123', 'user-456');
   * console.log('Member removed');
   * ```
   */
  removeMember: async (projectId: string, userId: string): Promise<void> => {
    await apiFetch.delete(`/projects/${projectId}/members/${userId}`);
  },

  /**
   * Update a member's role in a project
   *
   * Changes the role of an existing project member.
   *
   * @param projectId - The project ID
   * @param userId - The user ID whose role to update
   * @param role - The new role ("owner" | "admin" | "member" | "viewer")
   * @returns Promise that resolves when the role is updated
   * @throws {ApiError} If project doesn't exist or user is not a member
   *
   * @example
   * ```typescript
   * await projectService.updateMemberRole('proj-123', 'user-456', 'admin');
   * console.log('Role updated');
   * ```
   */
  updateMemberRole: async (projectId: string, userId: string, role: string): Promise<void> => {
    await apiFetch.patch(`/projects/${projectId}/members/${userId}`, { role });
  },

  /**
   * Get project details
   *
   * Retrieves detailed information about a project.
   *
   * @param projectId - The project ID
   * @returns Promise resolving to the project
   * @throws {ApiError} If project doesn't exist or user lacks access
   *
   * @example
   * ```typescript
   * const project = await projectService.getProject('proj-123');
   * console.log('Project name:', project.name);
   * ```
   */
  getProject: async (projectId: string): Promise<Project> => {
    const response = await apiFetch.get(`/projects/${projectId}`);
    return response.json();
  },

  /**
   * Update project details
   *
   * Updates one or more fields of a project.
   *
   * @param projectId - The project ID
   * @param updates - Partial project data to update
   * @returns Promise resolving to the updated project
   * @throws {ApiError} If project doesn't exist or update fails
   *
   * @example
   * ```typescript
   * const updated = await projectService.updateProject('proj-123', {
   *   name: 'New Project Name',
   *   description: 'Updated description'
   * });
   * ```
   */
  updateProject: async (projectId: string, updates: Partial<Project>): Promise<Project> => {
    const response = await apiFetch.patch(`/projects/${projectId}`, updates);
    return response.json();
  },

  /**
   * Delete a project
   *
   * Permanently deletes a project and all its associated data.
   * This action cannot be undone.
   *
   * @param projectId - The project ID to delete
   * @returns Promise that resolves when the project is deleted
   * @throws {ApiError} If project doesn't exist or user lacks permission
   *
   * @example
   * ```typescript
   * await projectService.deleteProject('proj-123');
   * console.log('Project deleted');
   * ```
   */
  deleteProject: async (projectId: string): Promise<void> => {
    await apiFetch.delete(`/projects/${projectId}`);
  },

  /**
   * List projects in a tenant
   *
   * Retrieves all projects that belong to a tenant.
   *
   * @param tenantId - The tenant ID
   * @returns Promise resolving to an array of projects
   * @throws {ApiError} If tenant doesn't exist or user lacks access
   *
   * @example
   * ```typescript
   * const projects = await projectService.listProjects('tenant-123');
   * console.log('Projects:', projects.length);
   * ```
   */
  listProjects: async (tenantId: string): Promise<Project[]> => {
    const response = await apiFetch.get(`/tenants/${tenantId}/projects`);
    const data = await response.json();
    return data.projects || [];
  },
};
