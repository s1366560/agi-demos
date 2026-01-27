/**
 * Tests for memoryService
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { memoryService } from '../../services/memoryService';

// Mock global fetch and localStorage
global.fetch = vi.fn() as any;
vi.stubGlobal('localStorage', {
  getItem: vi.fn(() => null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
});

describe('memoryService', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        (global.fetch as any).mockResolvedValue({
            ok: true,
            json: async () => ({}),
        });
    });

    describe('updateMemory', () => {
        it('should call PATCH endpoint with correct data', async () => {
            // Arrange
            const memoryId = 'memory-1';
            const updates = {
                title: 'Updated Title',
                content: 'Updated Content',
                version: 1,
            };

            // Act
            await memoryService.updateMemory(memoryId, updates);

            // Assert
            expect(global.fetch).toHaveBeenCalledWith(
                expect.stringContaining(`/api/v1/memories/${memoryId}`),
                expect.objectContaining({
                    method: 'PATCH',
                })
            );
        });

        it('should throw error on failed response', async () => {
            // Arrange
            (global.fetch as any).mockResolvedValue({
                ok: false,
                json: async () => ({ detail: 'Update failed' }),
            });

            // Act & Assert
            await expect(
                memoryService.updateMemory('memory-1', { title: 'Test', version: 1 })
            ).rejects.toThrow('Update failed');
        });

        it('should handle 409 conflict error', async () => {
            // Arrange
            (global.fetch as any).mockResolvedValue({
                ok: false,
                status: 409,
                json: async () => ({ detail: 'Version conflict' }),
            });

            // Act & Assert
            await expect(
                memoryService.updateMemory('memory-1', { title: 'Test', version: 1 })
            ).rejects.toThrow('Version conflict');
        });
    });

    describe('shareMemory', () => {
        it('should call POST endpoint with share data', async () => {
            // Arrange
            const memoryId = 'memory-1';
            const shareData = {
                target_type: 'user' as const,
                target_id: 'user-2',
                permission_level: 'view' as const,
            };

            // Act
            await memoryService.shareMemory(memoryId, shareData);

            // Assert
            expect(global.fetch).toHaveBeenCalledWith(
                `/api/v1/memories/${memoryId}/shares`,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(shareData),
                }
            );
        });

        it('should return share response on success', async () => {
            // Arrange
            const mockResponse = {
                id: 'share-1',
                memory_id: 'memory-1',
                permission_level: 'view',
            };

            (global.fetch as any).mockResolvedValue({
                ok: true,
                json: async () => mockResponse,
            });

            // Act
            const result = await memoryService.shareMemory('memory-1', {
                target_type: 'user',
                target_id: 'user-2',
                permission_level: 'view',
            });

            // Assert
            expect(result).toEqual(mockResponse);
        });

        it('should throw error on failed share', async () => {
            // Arrange
            (global.fetch as any).mockResolvedValue({
                ok: false,
                json: async () => ({ detail: 'Share failed' }),
            });

            // Act & Assert
            await expect(
                memoryService.shareMemory('memory-1', {
                    target_type: 'user',
                    target_id: 'user-2',
                    permission_level: 'view',
                })
            ).rejects.toThrow('Share failed');
        });
    });

    describe('deleteMemoryShare', () => {
        it('should call DELETE endpoint with correct IDs', async () => {
            // Arrange
            const memoryId = 'memory-1';
            const shareId = 'share-1';

            // Act
            await memoryService.deleteMemoryShare(memoryId, shareId);

            // Assert
            expect(global.fetch).toHaveBeenCalledWith(
                `/api/v1/memories/${memoryId}/shares/${shareId}`,
                {
                    method: 'DELETE',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                }
            );
        });

        it('should handle successful deletion', async () => {
            // Arrange
            (global.fetch as any).mockResolvedValue({
                ok: true,
                status: 204,
            });

            // Act & Assert - should not throw
            await expect(
                memoryService.deleteMemoryShare('memory-1', 'share-1')
            ).resolves.toBeUndefined();
        });

        it('should throw error on failed deletion', async () => {
            // Arrange
            (global.fetch as any).mockResolvedValue({
                ok: false,
                json: async () => ({ detail: 'Delete failed' }),
            });

            // Act & Assert
            await expect(
                memoryService.deleteMemoryShare('memory-1', 'share-1')
            ).rejects.toThrow('Delete failed');
        });
    });
});
