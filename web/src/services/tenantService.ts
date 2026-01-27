/**
 * Tenant Service - API calls for tenant management
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
   */
  listMembers: async (tenantId: string): Promise<{ users: User[] }> => {
    const response = await apiFetch.get(`/tenants/${tenantId}/members`);

    if (!response.ok) {
      throw new Error(`Failed to list tenant members: ${response.statusText}`);
    }

    return response.json();
  },

  /**
   * Add a member to a tenant
   */
  addMember: async (tenantId: string, userId: string, role: string): Promise<void> => {
    const response = await apiFetch.post(`/tenants/${tenantId}/members`, { user_id: userId, role });

    if (!response.ok) {
      throw new Error(`Failed to add tenant member: ${response.statusText}`);
    }
  },

  /**
   * Remove a member from a tenant
   */
  removeMember: async (tenantId: string, userId: string): Promise<void> => {
    const response = await apiFetch.delete(`/tenants/${tenantId}/members/${userId}`);

    if (!response.ok) {
      throw new Error(`Failed to remove tenant member: ${response.statusText}`);
    }
  },

  /**
   * Update a member's role in a tenant
   */
  updateMemberRole: async (tenantId: string, userId: string, role: string): Promise<void> => {
    const response = await apiFetch.patch(`/tenants/${tenantId}/members/${userId}`, { role });

    if (!response.ok) {
      throw new Error(`Failed to update member role: ${response.statusText}`);
    }
  },

  /**
   * Get tenant details
   */
  getTenant: async (tenantId: string): Promise<Tenant> => {
    const response = await apiFetch.get(`/tenants/${tenantId}`);

    if (!response.ok) {
      throw new Error(`Failed to get tenant: ${response.statusText}`);
    }

    return response.json();
  },

  /**
   * Create a new tenant
   */
  createTenant: async (name: string, description?: string): Promise<Tenant> => {
    const response = await apiFetch.post('/tenants', { name, description });

    if (!response.ok) {
      throw new Error(`Failed to create tenant: ${response.statusText}`);
    }

    return response.json();
  },

  /**
   * Update tenant details
   */
  updateTenant: async (tenantId: string, updates: Partial<Tenant>): Promise<Tenant> => {
    const response = await apiFetch.patch(`/tenants/${tenantId}`, updates);

    if (!response.ok) {
      throw new Error(`Failed to update tenant: ${response.statusText}`);
    }

    return response.json();
  },
};
