import { describe, it, expect, vi, beforeEach } from 'vitest'
import { projectService } from '../../services/projectService'

// Mock fetch and localStorage globally
global.fetch = vi.fn()
vi.stubGlobal('localStorage', {
  getItem: vi.fn(() => null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
})

describe('projectService - Service Tests', () => {
    const mockProjectId = 'project-123'
    const mockUserId = 'user-456'
    const mockRole = 'admin'

    beforeEach(() => {
        vi.clearAllMocks()
    })

    describe('listMembers', () => {
        it('should fetch project members successfully', async () => {
            const mockUsers = [
                {
                    id: 'user-1',
                    email: 'admin@example.com',
                    name: 'Admin',
                    role: 'admin',
                    created_at: '2024-01-01T00:00:00Z',
                    is_active: true
                },
                {
                    id: 'user-2',
                    email: 'member@example.com',
                    name: 'Member',
                    role: 'viewer',
                    created_at: '2024-01-02T00:00:00Z',
                    is_active: true
                }
            ]

            ;(global.fetch as any).mockResolvedValueOnce({
                ok: true,
                json: async () => ({ users: mockUsers })
            })

            const result = await projectService.listMembers(mockProjectId)

            expect(global.fetch).toHaveBeenCalledWith(
                expect.stringContaining(`/api/v1/projects/${mockProjectId}/members`),
                expect.objectContaining({
                    method: 'GET',
                })
            )
            expect(result).toEqual({ users: mockUsers })
        })

        it('should throw error when API call fails', async () => {
            ;(global.fetch as any).mockResolvedValueOnce({
                ok: false,
                statusText: 'Not Found'
            })

            await expect(projectService.listMembers(mockProjectId)).rejects.toThrow(
                'Failed to list project members: Not Found'
            )
        })

        it('should throw error when network fails', async () => {
            ;(global.fetch as any).mockRejectedValueOnce(new Error('Network error'))

            await expect(projectService.listMembers(mockProjectId)).rejects.toThrow(
                'Network error'
            )
        })
    })

    describe('addMember', () => {
        it('should add member to project successfully', async () => {
            ;(global.fetch as any).mockResolvedValueOnce({
                ok: true,
                json: async () => ({ success: true })
            })

            await projectService.addMember(mockProjectId, mockUserId, mockRole)

            expect(global.fetch).toHaveBeenCalledWith(
                `/api/v1/projects/${mockProjectId}/members`,
                expect.objectContaining({
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ user_id: mockUserId, role: mockRole })
                })
            )
        })

        it('should throw error when add member fails', async () => {
            ;(global.fetch as any).mockResolvedValueOnce({
                ok: false,
                statusText: 'Bad Request'
            })

            await expect(
                projectService.addMember(mockProjectId, mockUserId, mockRole)
            ).rejects.toThrow('Failed to add project member: Bad Request')
        })
    })

    describe('removeMember', () => {
        it('should remove member from project successfully', async () => {
            ;(global.fetch as any).mockResolvedValueOnce({
                ok: true,
                json: async () => ({ success: true })
            })

            await projectService.removeMember(mockProjectId, mockUserId)

            expect(global.fetch).toHaveBeenCalledWith(
                `/api/v1/projects/${mockProjectId}/members/${mockUserId}`,
                expect.objectContaining({
                    method: 'DELETE',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                })
            )
        })

        it('should throw error when remove member fails', async () => {
            ;(global.fetch as any).mockResolvedValueOnce({
                ok: false,
                statusText: 'Not Found'
            })

            await expect(
                projectService.removeMember(mockProjectId, mockUserId)
            ).rejects.toThrow('Failed to remove project member: Not Found')
        })
    })

    describe('updateMemberRole', () => {
        it('should update member role successfully', async () => {
            const newRole = 'viewer'

            ;(global.fetch as any).mockResolvedValueOnce({
                ok: true,
                json: async () => ({ success: true })
            })

            await projectService.updateMemberRole(mockProjectId, mockUserId, newRole)

            expect(global.fetch).toHaveBeenCalledWith(
                `/api/v1/projects/${mockProjectId}/members/${mockUserId}`,
                expect.objectContaining({
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ role: newRole })
                })
            )
        })

        it('should throw error when update role fails', async () => {
            ;(global.fetch as any).mockResolvedValueOnce({
                ok: false,
                statusText: 'Forbidden'
            })

            await expect(
                projectService.updateMemberRole(mockProjectId, mockUserId, mockRole)
            ).rejects.toThrow('Failed to update member role: Forbidden')
        })
    })

    describe('updateProject', () => {
        it('should update project details successfully', async () => {
            const updates = {
                name: 'Updated Project Name',
                description: 'Updated description'
            }

            const updatedProject = {
                id: mockProjectId,
                name: 'Updated Project Name',
                description: 'Updated description',
                tenant_id: 'tenant-1',
                owner_id: 'user-1',
                member_ids: [],
                is_public: false,
                created_at: '2024-01-01T00:00:00Z'
            }

            ;(global.fetch as any).mockResolvedValueOnce({
                ok: true,
                json: async () => updatedProject
            })

            const result = await projectService.updateProject(mockProjectId, updates)

            expect(global.fetch).toHaveBeenCalledWith(
                `/api/v1/projects/${mockProjectId}`,
                expect.objectContaining({
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(updates)
                })
            )
            expect(result).toEqual(updatedProject)
        })

        it('should throw error when update project fails', async () => {
            ;(global.fetch as any).mockResolvedValueOnce({
                ok: false,
                statusText: 'Bad Request'
            })

            await expect(
                projectService.updateProject(mockProjectId, { name: 'New Name' })
            ).rejects.toThrow('Failed to update project: Bad Request')
        })
    })

    describe('deleteProject', () => {
        it('should delete project successfully', async () => {
            ;(global.fetch as any).mockResolvedValueOnce({
                ok: true,
                json: async () => ({ success: true })
            })

            await projectService.deleteProject(mockProjectId)

            expect(global.fetch).toHaveBeenCalledWith(
                `/api/v1/projects/${mockProjectId}`,
                expect.objectContaining({
                    method: 'DELETE',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                })
            )
        })

        it('should throw error when delete project fails', async () => {
            ;(global.fetch as any).mockResolvedValueOnce({
                ok: false,
                statusText: 'Forbidden'
            })

            await expect(projectService.deleteProject(mockProjectId)).rejects.toThrow(
                'Failed to delete project: Forbidden'
            )
        })
    })
})
