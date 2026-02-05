/**
 * Tests for projectService using apiFetch
 *
 * apiFetch automatically throws ApiError for non-success responses,
 * so services can be simplified without manual error handling.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ApiError, ApiErrorType } from '../../services/client/ApiError';
import { projectService } from '../../services/projectService';

// Mock apiFetch
vi.mock('../../services/client/urlUtils', () => ({
  apiFetch: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

describe('projectService - Service Tests', () => {
  const mockProjectId = 'project-123';
  const mockUserId = 'user-456';
  const mockRole = 'admin';

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('listMembers', () => {
    it('should fetch project members successfully', async () => {
      const mockUsers = [
        {
          id: 'user-1',
          email: 'admin@example.com',
          name: 'Admin',
          role: 'admin',
          created_at: '2024-01-01T00:00:00Z',
          is_active: true,
        },
        {
          id: 'user-2',
          email: 'member@example.com',
          name: 'Member',
          role: 'viewer',
          created_at: '2024-01-02T00:00:00Z',
          is_active: true,
        },
      ];

      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.get).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ users: mockUsers }),
        status: 200,
        statusText: 'OK',
        headers: new Headers(),
      } as Response);

      const result = await projectService.listMembers(mockProjectId);

      expect(apiFetch.get).toHaveBeenCalledWith(
        `/projects/${mockProjectId}/members`
      );
      expect(result).toEqual({ users: mockUsers });
    });

    it('should propagate ApiError when API call fails', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.NOT_FOUND,
        'NOT_FOUND',
        'Project not found',
        404
      );
      vi.mocked(apiFetch.get).mockRejectedValueOnce(mockError);

      await expect(projectService.listMembers(mockProjectId)).rejects.toThrow(ApiError);
    });
  });

  describe('addMember', () => {
    it('should add member to project successfully', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.post).mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({}),
        headers: new Headers(),
      } as Response);

      await projectService.addMember(mockProjectId, mockUserId, mockRole);

      expect(apiFetch.post).toHaveBeenCalledWith(
        `/projects/${mockProjectId}/members`,
        { user_id: mockUserId, role: mockRole }
      );
    });

    it('should propagate ApiError when add member fails', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.VALIDATION,
        'BAD_REQUEST',
        'Invalid input',
        400
      );
      vi.mocked(apiFetch.post).mockRejectedValueOnce(mockError);

      await expect(
        projectService.addMember(mockProjectId, mockUserId, mockRole)
      ).rejects.toThrow(ApiError);
    });
  });

  describe('removeMember', () => {
    it('should remove member from project successfully', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.delete).mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({}),
        headers: new Headers(),
      } as Response);

      await projectService.removeMember(mockProjectId, mockUserId);

      expect(apiFetch.delete).toHaveBeenCalledWith(
        `/projects/${mockProjectId}/members/${mockUserId}`
      );
    });

    it('should propagate ApiError when remove member fails', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.NOT_FOUND,
        'NOT_FOUND',
        'Member not found',
        404
      );
      vi.mocked(apiFetch.delete).mockRejectedValueOnce(mockError);

      await expect(
        projectService.removeMember(mockProjectId, mockUserId)
      ).rejects.toThrow(ApiError);
    });
  });

  describe('updateMemberRole', () => {
    it('should update member role successfully', async () => {
      const newRole = 'viewer';
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.patch).mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({}),
        headers: new Headers(),
      } as Response);

      await projectService.updateMemberRole(mockProjectId, mockUserId, newRole);

      expect(apiFetch.patch).toHaveBeenCalledWith(
        `/projects/${mockProjectId}/members/${mockUserId}`,
        { role: newRole }
      );
    });

    it('should propagate ApiError when update role fails', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.AUTHORIZATION,
        'FORBIDDEN',
        'Insufficient permissions',
        403
      );
      vi.mocked(apiFetch.patch).mockRejectedValueOnce(mockError);

      await expect(
        projectService.updateMemberRole(mockProjectId, mockUserId, mockRole)
      ).rejects.toThrow(ApiError);
    });
  });

  describe('updateProject', () => {
    it('should update project details successfully', async () => {
      const updates = {
        name: 'Updated Project Name',
        description: 'Updated description',
      };

      const updatedProject = {
        id: mockProjectId,
        name: 'Updated Project Name',
        description: 'Updated description',
        tenant_id: 'tenant-1',
        owner_id: 'user-1',
        member_ids: [],
        is_public: false,
        created_at: '2024-01-01T00:00:00Z',
      };

      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.patch).mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => updatedProject,
        headers: new Headers(),
      } as Response);

      const result = await projectService.updateProject(mockProjectId, updates);

      expect(apiFetch.patch).toHaveBeenCalledWith(
        `/projects/${mockProjectId}`,
        updates
      );
      expect(result).toEqual(updatedProject);
    });

    it('should propagate ApiError when update project fails', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.VALIDATION,
        'BAD_REQUEST',
        'Invalid input',
        400
      );
      vi.mocked(apiFetch.patch).mockRejectedValueOnce(mockError);

      await expect(
        projectService.updateProject(mockProjectId, { name: 'New Name' })
      ).rejects.toThrow(ApiError);
    });
  });

  describe('deleteProject', () => {
    it('should delete project successfully', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.delete).mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({}),
        headers: new Headers(),
      } as Response);

      await projectService.deleteProject(mockProjectId);

      expect(apiFetch.delete).toHaveBeenCalledWith(`/projects/${mockProjectId}`);
    });

    it('should propagate ApiError when delete project fails', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.AUTHORIZATION,
        'FORBIDDEN',
        'Cannot delete project',
        403
      );
      vi.mocked(apiFetch.delete).mockRejectedValueOnce(mockError);

      await expect(projectService.deleteProject(mockProjectId)).rejects.toThrow(ApiError);
    });
  });
});
