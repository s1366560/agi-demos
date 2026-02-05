/**
 * Tests for tenantService using apiFetch
 *
 * apiFetch automatically throws ApiError for non-success responses,
 * so services can be simplified without manual error handling.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ApiError, ApiErrorType } from '../../services/client/ApiError';
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

    it('should propagate ApiError on failed response', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.SERVER,
        'INTERNAL_ERROR',
        'Failed to list members',
        500
      );
      vi.mocked(apiFetch.get).mockRejectedValueOnce(mockError);

      await expect(
        tenantService.listMembers('tenant-1')
      ).rejects.toThrow(ApiError);
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

    it('should propagate ApiError on failed add', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.VALIDATION,
        'BAD_REQUEST',
        'Failed to add member',
        400
      );
      vi.mocked(apiFetch.post).mockRejectedValueOnce(mockError);

      await expect(
        tenantService.addMember('tenant-1', 'user-2', 'member')
      ).rejects.toThrow(ApiError);
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

    it('should propagate ApiError on failed removal', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.NOT_FOUND,
        'NOT_FOUND',
        'Failed to remove member',
        404
      );
      vi.mocked(apiFetch.delete).mockRejectedValueOnce(mockError);

      await expect(
        tenantService.removeMember('tenant-1', 'user-2')
      ).rejects.toThrow(ApiError);
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

    it('should propagate ApiError on failed update', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.AUTHORIZATION,
        'FORBIDDEN',
        'Failed to update role',
        403
      );
      vi.mocked(apiFetch.patch).mockRejectedValueOnce(mockError);

      await expect(
        tenantService.updateMemberRole('tenant-1', 'user-2', 'admin')
      ).rejects.toThrow(ApiError);
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

    it('should propagate ApiError on failed creation', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.VALIDATION,
        'BAD_REQUEST',
        'Failed to create tenant',
        400
      );
      vi.mocked(apiFetch.post).mockRejectedValueOnce(mockError);

      await expect(
        tenantService.createTenant('Test', 'Description')
      ).rejects.toThrow(ApiError);
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

    it('should propagate ApiError on failed update', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.VALIDATION,
        'BAD_REQUEST',
        'Failed to update tenant',
        400
      );
      vi.mocked(apiFetch.patch).mockRejectedValueOnce(mockError);

      await expect(
        tenantService.updateTenant('tenant-1', { name: 'Test' })
      ).rejects.toThrow(ApiError);
    });
  });
});
