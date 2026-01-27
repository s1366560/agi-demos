/**
 * Tests for tenantService using apiFetch
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { tenantService } from '../../services/tenantService';

// Mock apiFetch
vi.mock('../../services/client/urlUtils', () => ({
  apiFetch: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

describe('tenantService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('listMembers', () => {
    it('should fetch members for a tenant', async () => {
      const tenantId = 'tenant-1';
      const mockMembers = {
        users: [
          { id: 'user-1', email: 'user1@test.com', role: 'owner' },
          { id: 'user-2', email: 'user2@test.com', role: 'admin' },
        ],
      };

      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.get).mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => mockMembers,
        headers: new Headers(),
      } as Response);

      const result = await tenantService.listMembers(tenantId);

      expect(apiFetch.get).toHaveBeenCalledWith(`/tenants/${tenantId}/members`);
      expect(result).toEqual(mockMembers);
    });

    it('should throw error on failed response', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.get).mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: async () => ({ detail: 'Failed to list members' }),
        headers: new Headers(),
      } as Response);

      await expect(
        tenantService.listMembers('tenant-1')
      ).rejects.toThrow('Failed to list tenant members');
    });
  });

  describe('addMember', () => {
    it('should add member to tenant', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.post).mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({}),
        headers: new Headers(),
      } as Response);

      await tenantService.addMember('tenant-1', 'user-2', 'member');

      expect(apiFetch.post).toHaveBeenCalledWith(
        `/tenants/tenant-1/members`,
        { user_id: 'user-2', role: 'member' }
      );
    });

    it('should throw error on failed add', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.post).mockResolvedValueOnce({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        json: async () => ({ detail: 'Failed to add member' }),
        headers: new Headers(),
      } as Response);

      await expect(
        tenantService.addMember('tenant-1', 'user-2', 'member')
      ).rejects.toThrow('Failed to add tenant member');
    });
  });

  describe('removeMember', () => {
    it('should remove member from tenant', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.delete).mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({}),
        headers: new Headers(),
      } as Response);

      await tenantService.removeMember('tenant-1', 'user-2');

      expect(apiFetch.delete).toHaveBeenCalledWith(
        `/tenants/tenant-1/members/user-2`
      );
    });

    it('should throw error on failed removal', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.delete).mockResolvedValueOnce({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: async () => ({ detail: 'Failed to remove member' }),
        headers: new Headers(),
      } as Response);

      await expect(
        tenantService.removeMember('tenant-1', 'user-2')
      ).rejects.toThrow('Failed to remove tenant member');
    });
  });

  describe('updateMemberRole', () => {
    it('should update member role', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.patch).mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({}),
        headers: new Headers(),
      } as Response);

      await tenantService.updateMemberRole('tenant-1', 'user-2', 'admin');

      expect(apiFetch.patch).toHaveBeenCalledWith(
        `/tenants/tenant-1/members/user-2`,
        { role: 'admin' }
      );
    });

    it('should throw error on failed update', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.patch).mockResolvedValueOnce({
        ok: false,
        status: 403,
        statusText: 'Forbidden',
        json: async () => ({ detail: 'Failed to update role' }),
        headers: new Headers(),
      } as Response);

      await expect(
        tenantService.updateMemberRole('tenant-1', 'user-2', 'admin')
      ).rejects.toThrow('Failed to update member role');
    });
  });

  describe('getTenant', () => {
    it('should fetch tenant details', async () => {
      const tenantId = 'tenant-1';
      const mockTenant = {
        id: tenantId,
        name: 'Test Tenant',
        description: 'Test Description',
        owner_id: 'user-1',
        plan: 'free',
        created_at: '2024-01-01T00:00:00Z',
      };

      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.get).mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => mockTenant,
        headers: new Headers(),
      } as Response);

      const result = await tenantService.getTenant(tenantId);

      expect(apiFetch.get).toHaveBeenCalledWith(`/tenants/${tenantId}`);
      expect(result).toEqual(mockTenant);
    });
  });

  describe('createTenant', () => {
    it('should create new tenant', async () => {
      const name = 'New Tenant';
      const description = 'New Description';
      const mockTenant = {
        id: 'tenant-new',
        name,
        description,
        owner_id: 'user-1',
        plan: 'free',
        created_at: '2024-01-01T00:00:00Z',
      };

      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.post).mockResolvedValueOnce({
        ok: true,
        status: 201,
        statusText: 'Created',
        json: async () => mockTenant,
        headers: new Headers(),
      } as Response);

      const result = await tenantService.createTenant(name, description);

      expect(apiFetch.post).toHaveBeenCalledWith('/tenants', {
        name,
        description,
      });
      expect(result).toEqual(mockTenant);
    });

    it('should throw error on failed creation', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.post).mockResolvedValueOnce({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        json: async () => ({ detail: 'Failed to create tenant' }),
        headers: new Headers(),
      } as Response);

      await expect(
        tenantService.createTenant('Test', 'Description')
      ).rejects.toThrow('Failed to create tenant');
    });
  });

  describe('updateTenant', () => {
    it('should update tenant details', async () => {
      const tenantId = 'tenant-1';
      const updates = {
        name: 'Updated Tenant',
        description: 'Updated Description',
      };

      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.patch).mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({ id: tenantId, ...updates }),
        headers: new Headers(),
      } as Response);

      await tenantService.updateTenant(tenantId, updates);

      expect(apiFetch.patch).toHaveBeenCalledWith(`/tenants/${tenantId}`, updates);
    });

    it('should throw error on failed update', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.patch).mockResolvedValueOnce({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        json: async () => ({ detail: 'Failed to update tenant' }),
        headers: new Headers(),
      } as Response);

      await expect(
        tenantService.updateTenant('tenant-1', { name: 'Test' })
      ).rejects.toThrow('Failed to update tenant');
    });
  });
});
