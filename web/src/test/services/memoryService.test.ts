/**
 * Tests for memoryService
 *
 * apiFetch automatically throws ApiError for non-success responses,
 * so services can be simplified without manual error handling.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ApiError, ApiErrorType } from '../../services/client/ApiError';
import { memoryService } from '../../services/memoryService';

// Mock apiFetch
vi.mock('../../services/client/urlUtils', () => ({
  apiFetch: {
    patch: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe('memoryService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('updateMemory', () => {
    it('should call PATCH endpoint with correct data', async () => {
      const memoryId = 'memory-1';
      const updates = {
        title: 'Updated Title',
        content: 'Updated Content',
        version: 1,
      };

      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.patch).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: memoryId, ...updates }),
        status: 200,
        statusText: 'OK',
        headers: new Headers(),
      } as Response);

      const result = await memoryService.updateMemory(memoryId, updates);

      expect(apiFetch.patch).toHaveBeenCalledWith(`/memories/${memoryId}`, updates);
      expect(result).toEqual({ id: memoryId, ...updates });
    });

    it('should propagate ApiError on failed response', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.CONFLICT,
        'VERSION_CONFLICT',
        'Version conflict',
        409
      );
      vi.mocked(apiFetch.patch).mockRejectedValueOnce(mockError);

      await expect(
        memoryService.updateMemory('memory-1', { title: 'Test', version: 1 })
      ).rejects.toThrow(ApiError);
    });
  });

  describe('shareMemory', () => {
    it('should call POST endpoint with share data', async () => {
      const memoryId = 'memory-1';
      const shareData = {
        target_type: 'user' as const,
        target_id: 'user-2',
        permission_level: 'view' as const,
      };

      const mockResponse = {
        id: 'share-1',
        memory_id: memoryId,
        permission_level: 'view',
      };

      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.post).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
        status: 200,
        statusText: 'OK',
        headers: new Headers(),
      } as Response);

      const result = await memoryService.shareMemory(memoryId, shareData);

      expect(apiFetch.post).toHaveBeenCalledWith(`/memories/${memoryId}/shares`, shareData);
      expect(result).toEqual(mockResponse);
    });

    it('should propagate ApiError on failed share', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(
        ApiErrorType.VALIDATION,
        'INVALID_INPUT',
        'Invalid share data',
        400
      );
      vi.mocked(apiFetch.post).mockRejectedValueOnce(mockError);

      await expect(
        memoryService.shareMemory('memory-1', {
          target_type: 'user',
          target_id: 'user-2',
          permission_level: 'view',
        })
      ).rejects.toThrow(ApiError);
    });
  });

  describe('deleteMemoryShare', () => {
    it('should call DELETE endpoint with correct IDs', async () => {
      const memoryId = 'memory-1';
      const shareId = 'share-1';

      const { apiFetch } = await import('../../services/client/urlUtils');
      vi.mocked(apiFetch.delete).mockResolvedValueOnce({
        ok: true,
        status: 204,
        statusText: 'No Content',
        json: async () => ({}),
        headers: new Headers(),
      } as Response);

      await memoryService.deleteMemoryShare(memoryId, shareId);

      expect(apiFetch.delete).toHaveBeenCalledWith(`/memories/${memoryId}/shares/${shareId}`);
    });

    it('should propagate ApiError on failed deletion', async () => {
      const { apiFetch } = await import('../../services/client/urlUtils');
      const mockError = new ApiError(ApiErrorType.NOT_FOUND, 'NOT_FOUND', 'Share not found', 404);
      vi.mocked(apiFetch.delete).mockRejectedValueOnce(mockError);

      await expect(memoryService.deleteMemoryShare('memory-1', 'share-1')).rejects.toThrow(
        ApiError
      );
    });
  });
});
