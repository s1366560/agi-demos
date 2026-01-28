/**
 * Tenant Service - Tenant management API
 *
 * Provides methods for managing tenants and their members, including:
 * - Creating and updating tenants
 * - Managing tenant membership and roles
 * - Getting tenant details
 *
 * @packageDocumentation
 *
 * @example
 * ```typescript
 * import { tenantService } from '@/services/tenantService';
 *
 * // Create a new tenant
 * const tenant = await tenantService.createTenant('My Tenant', 'Description');
 *
 * // List tenant members
 * const { users } = await tenantService.listMembers('tenant-123');
 *
 * // Update tenant
 * const updated = await tenantService.updateTenant('tenant-123', {
 *   name: 'Updated Name'
 * });
 * ```
 */

import { apiFetch } from './client/urlUtils';

/**
 * Tenant user with role
 *
 * Represents a user who is a member of a tenant.
 *
 * @example
 * ```typescript
 * const user: User = {
 *   id: 'user-123',
 *   email: 'user@example.com',
 *   name: 'John Doe',
 *   role: 'admin',
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
 * Tenant entity
 *
 * Represents a tenant with its configuration.
 *
 * @example
 * ```typescript
 * const tenant: Tenant = {
 *   id: 'tenant-123',
 *   name: 'My Tenant',
 *   description: 'Tenant description',
 *   owner_id: 'user-456',
 *   plan: 'pro',
 *   created_at: '2024-01-01T00:00:00Z'
 * };
 * ```
 */
interface Tenant {
  id: string;
  name: string;
  description?: string;
  owner_id: string;
  plan: string;
  created_at: string;
}

export const tenantService = {
  /**
   * List all members of a tenant
   *
   * Retrieves all users who are members of a tenant.
   *
   * @param tenantId - The tenant ID
   * @returns Promise resolving to a list of users
   * @throws {ApiError} If tenant doesn't exist or user lacks access
   *
   * @example
   * ```typescript
   * const { users } = await tenantService.listMembers('tenant-123');
   * console.log('Members:', users);
   * ```
   */
  listMembers: async (tenantId: string): Promise<{ users: User[] }> => {
    const response = await apiFetch.get(`/tenants/${tenantId}/members`);
    return response.json();
  },

  /**
   * Add a member to a tenant
   *
   * Adds a user as a member of a tenant with the specified role.
   *
   * @param tenantId - The tenant ID
   * @param userId - The user ID to add as a member
   * @param role - The role to assign ("owner" | "admin" | "member" | "viewer")
   * @returns Promise that resolves when the member is added
   * @throws {ApiError} If tenant or user doesn't exist
   *
   * @example
   * ```typescript
   * await tenantService.addMember('tenant-123', 'user-456', 'member');
   * console.log('Member added');
   * ```
   */
  addMember: async (tenantId: string, userId: string, role: string): Promise<void> => {
    await apiFetch.post(`/tenants/${tenantId}/members`, { user_id: userId, role });
  },

  /**
   * Remove a member from a tenant
   *
   * Removes a user from a tenant's membership.
   *
   * @param tenantId - The tenant ID
   * @param userId - The user ID to remove
   * @returns Promise that resolves when the member is removed
   * @throws {ApiError} If tenant doesn't exist or user is not a member
   *
   * @example
   * ```typescript
   * await tenantService.removeMember('tenant-123', 'user-456');
   * console.log('Member removed');
   * ```
   */
  removeMember: async (tenantId: string, userId: string): Promise<void> => {
    await apiFetch.delete(`/tenants/${tenantId}/members/${userId}`);
  },

  /**
   * Update a member's role in a tenant
   *
   * Changes the role of an existing tenant member.
   *
   * @param tenantId - The tenant ID
   * @param userId - The user ID whose role to update
   * @param role - The new role ("owner" | "admin" | "member" | "viewer")
   * @returns Promise that resolves when the role is updated
   * @throws {ApiError} If tenant doesn't exist or user is not a member
   *
   * @example
   * ```typescript
   * await tenantService.updateMemberRole('tenant-123', 'user-456', 'admin');
   * console.log('Role updated');
   * ```
   */
  updateMemberRole: async (tenantId: string, userId: string, role: string): Promise<void> => {
    await apiFetch.patch(`/tenants/${tenantId}/members/${userId}`, { role });
  },

  /**
   * Get tenant details
   *
   * Retrieves detailed information about a tenant.
   *
   * @param tenantId - The tenant ID
   * @returns Promise resolving to the tenant
   * @throws {ApiError} If tenant doesn't exist or user lacks access
   *
   * @example
   * ```typescript
   * const tenant = await tenantService.getTenant('tenant-123');
   * console.log('Tenant name:', tenant.name);
   * ```
   */
  getTenant: async (tenantId: string): Promise<Tenant> => {
    const response = await apiFetch.get(`/tenants/${tenantId}`);
    return response.json();
  },

  /**
   * Create a new tenant
   *
   * Creates a new tenant with the specified name and optional description.
   *
   * @param name - The tenant name
   * @param description - Optional tenant description
   * @returns Promise resolving to the created tenant
   * @throws {ApiError} If creation fails (e.g., duplicate name)
   *
   * @example
   * ```typescript
   * const tenant = await tenantService.createTenant(
   *   'My Tenant',
   *   'A description for my tenant'
   * );
   * console.log('Created tenant ID:', tenant.id);
   * ```
   */
  createTenant: async (name: string, description?: string): Promise<Tenant> => {
    const response = await apiFetch.post('/tenants', { name, description });
    return response.json();
  },

  /**
   * Update tenant details
   *
   * Updates one or more fields of a tenant.
   *
   * @param tenantId - The tenant ID
   * @param updates - Partial tenant data to update
   * @returns Promise resolving to the updated tenant
   * @throws {ApiError} If tenant doesn't exist or update fails
   *
   * @example
   * ```typescript
   * const updated = await tenantService.updateTenant('tenant-123', {
   *   name: 'New Tenant Name',
   *   description: 'Updated description'
   * });
   * ```
   */
  updateTenant: async (tenantId: string, updates: Partial<Tenant>): Promise<Tenant> => {
    const response = await apiFetch.patch(`/tenants/${tenantId}`, updates);
    return response.json();
  },
};
