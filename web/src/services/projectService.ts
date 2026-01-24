/**
 * Project Service - API calls for project management
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
    try {
      const response = await fetch(`/api/v1/projects/${projectId}/members`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      });
      if (!response.ok) {
        throw new Error(`Failed to list project members: ${response.statusText}`);
      }
      return response.json();
    } catch (err: any) {
      throw new Error(`Failed to list project members: ${err?.message || String(err)}`);
    }
  },

  /**
   * Add a member to a project
   */
  addMember: async (projectId: string, userId: string, role: string): Promise<void> => {
    const response = await fetch(`/api/v1/projects/${projectId}/members`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ user_id: userId, role }),
    });

    if (!response.ok) {
      throw new Error(`Failed to add project member: ${response.statusText}`);
    }
  },

  /**
   * Remove a member from a project
   */
  removeMember: async (projectId: string, userId: string): Promise<void> => {
    const response = await fetch(`/api/v1/projects/${projectId}/members/${userId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to remove project member: ${response.statusText}`);
    }
  },

  /**
   * Update a member's role in a project
   */
  updateMemberRole: async (projectId: string, userId: string, role: string): Promise<void> => {
    const response = await fetch(`/api/v1/projects/${projectId}/members/${userId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ role }),
    });

    if (!response.ok) {
      throw new Error(`Failed to update member role: ${response.statusText}`);
    }
  },

  /**
   * Get project details
   */
  getProject: async (projectId: string): Promise<Project> => {
    const response = await fetch(`/api/v1/projects/${projectId}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to get project: ${response.statusText}`);
    }

    return response.json();
  },

  /**
   * Update project details
   */
  updateProject: async (projectId: string, updates: Partial<Project>): Promise<Project> => {
    const response = await fetch(`/api/v1/projects/${projectId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(updates),
    });

    if (!response.ok) {
      throw new Error(`Failed to update project: ${response.statusText}`);
    }

    return response.json();
  },

  /**
   * Delete a project
   */
  deleteProject: async (projectId: string): Promise<void> => {
    const response = await fetch(`/api/v1/projects/${projectId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to delete project: ${response.statusText}`);
    }
  },

  /**
   * List projects in a tenant
   */
  listProjects: async (tenantId: string): Promise<Project[]> => {
    const response = await fetch(`/api/v1/tenants/${tenantId}/projects`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to list projects: ${response.statusText}`);
    }

    const data = await response.json();
    return data.projects || [];
  },
};
