/**
 * Tests for tenantService
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { tenantService } from '../../services/tenantService';

// Mock global fetch and localStorage
global.fetch = vi.fn() as any;
vi.stubGlobal('localStorage', {
  getItem: vi.fn(() => null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
});

describe('tenantService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (global.fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });
  });

  describe('listMembers', () => {
    it('should fetch members for a tenant', async () => {
      // Arrange
      const tenantId = 'tenant-1';
      const mockMembers = {
        users: [
          { id: 'user-1', email: 'user1@test.com', role: 'owner' },
          { id: 'user-2', email: 'user2@test.com', role: 'admin' },
        ],
      };

      (global.fetch as any).mockResolvedValue({
        ok: true,
        json: async () => mockMembers,
      });

      // Act
      const result = await tenantService.listMembers(tenantId);

      // Assert - fetch should be called with /api/v1 prefix added by createApiUrl
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/tenants/tenant-1/members'),
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      );
      expect(result).toEqual(mockMembers);
    });

    it('should throw error on failed response', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValue({
        ok: false,
        json: async () => ({ detail: 'Failed to list members' }),
      });

      // Act & Assert
      await expect(
        tenantService.listMembers('tenant-1')
      ).rejects.toThrow('Failed to list tenant members');
    });
  });

  describe('addMember', () => {
    it('should add member to tenant', async () => {
      // Arrange
      const tenantId = 'tenant-1';
      const userId = 'user-2';
      const role = 'member';

      // Act
      await tenantService.addMember(tenantId, userId, role);

      // Assert
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/tenants/tenant-1/members'),
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      );
    });

    it('should throw error on failed add', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValue({
        ok: false,
        json: async () => ({ detail: 'Failed to add member' }),
      });

      // Act & Assert
      await expect(
        tenantService.addMember('tenant-1', 'user-2', 'member')
      ).rejects.toThrow('Failed to add tenant member');
    });
  });

  describe('removeMember', () => {
    it('should remove member from tenant', async () => {
      // Arrange
      const tenantId = 'tenant-1';
      const userId = 'user-2';

      // Act
      await tenantService.removeMember(tenantId, userId);

      // Assert
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/v1/tenants/${tenantId}/members/${userId}`),
        expect.objectContaining({
          method: 'DELETE',
        })
      );
    });

    it('should throw error on failed removal', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValue({
        ok: false,
        json: async () => ({ detail: 'Failed to remove member' }),
      });

      // Act & Assert
      await expect(
        tenantService.removeMember('tenant-1', 'user-2')
      ).rejects.toThrow('Failed to remove tenant member');
    });
  });

  describe('updateMemberRole', () => {
    it('should update member role', async () => {
      // Arrange
      const tenantId = 'tenant-1';
      const userId = 'user-2';
      const role = 'admin';

      // Act
      await tenantService.updateMemberRole(tenantId, userId, role);

      // Assert
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/v1/tenants/${tenantId}/members/${userId}`),
        expect.objectContaining({
          method: 'PATCH',
        })
      );
    });

    it('should throw error on failed update', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValue({
        ok: false,
        json: async () => ({ detail: 'Failed to update role' }),
      });

      // Act & Assert
      await expect(
        tenantService.updateMemberRole('tenant-1', 'user-2', 'admin')
      ).rejects.toThrow('Failed to update member role');
    });
  });

  describe('getTenant', () => {
    it('should fetch tenant details', async () => {
      // Arrange
      const tenantId = 'tenant-1';
      const mockTenant = {
        id: tenantId,
        name: 'Test Tenant',
        description: 'Test Description',
        owner_id: 'user-1',
        plan: 'free',
        created_at: '2024-01-01T00:00:00Z',
      };

      (global.fetch as any).mockResolvedValue({
        ok: true,
        json: async () => mockTenant,
      });

      // Act
      const result = await tenantService.getTenant(tenantId);

      // Assert
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/v1/tenants/${tenantId}`),
        expect.objectContaining({
          method: 'GET',
        })
      );
      expect(result).toEqual(mockTenant);
    });
  });

  describe('createTenant', () => {
    it('should create new tenant', async () => {
      // Arrange
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

      (global.fetch as any).mockResolvedValue({
        ok: true,
        json: async () => mockTenant,
      });

      // Act
      const result = await tenantService.createTenant(name, description);

      // Assert
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/tenants'),
        expect.objectContaining({
          method: 'POST',
        })
      );
      expect(result).toEqual(mockTenant);
    });

    it('should throw error on failed creation', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValue({
        ok: false,
        json: async () => ({ detail: 'Failed to create tenant' }),
      });

      // Act & Assert
      await expect(
        tenantService.createTenant('Test', 'Description')
      ).rejects.toThrow('Failed to create tenant');
    });
  });

  describe('updateTenant', () => {
    it('should update tenant details', async () => {
      // Arrange
      const tenantId = 'tenant-1';
      const updates = {
        name: 'Updated Tenant',
        description: 'Updated Description',
      };

      (global.fetch as any).mockResolvedValue({
        ok: true,
        json: async () => ({ id: tenantId, ...updates }),
      });

      // Act
      await tenantService.updateTenant(tenantId, updates);

      // Assert
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining(`/api/v1/tenants/${tenantId}`),
        expect.objectContaining({
          method: 'PATCH',
        })
      );
    });

    it('should throw error on failed update', async () => {
      // Arrange
      (global.fetch as any).mockResolvedValue({
        ok: false,
        json: async () => ({ detail: 'Failed to update tenant' }),
      });

      // Act & Assert
      await expect(
        tenantService.updateTenant('tenant-1', { name: 'Test' })
      ).rejects.toThrow('Failed to update tenant');
    });
  });
});
