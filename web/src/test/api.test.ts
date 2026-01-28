import { describe, it, expect, vi, beforeEach } from 'vitest'
import { authAPI, tenantAPI, projectAPI, memoryAPI } from '../services/api'
import type { MemoryCreate, MemoryUpdate, Entity, Relationship } from '../types/memory'

// Define the mock instance using vi.hoisted to handle hoisting
const { mockApiInstance } = vi.hoisted(() => {
    return {
        mockApiInstance: {
            interceptors: {
                request: { use: vi.fn() },
                response: { use: vi.fn() }
            },
            get: vi.fn(),
            post: vi.fn(),
            put: vi.fn(),
            patch: vi.fn(),
            delete: vi.fn()
        }
    }
})

// Mock axios
vi.mock('axios', () => ({
    default: {
        create: vi.fn(() => mockApiInstance)
    }
}))

describe('API Services', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        localStorage.clear()
    })

    describe('authAPI', () => {
        it('login should return token and user', async () => {
            const mockTokenResponse = {
                access_token: 'test-token',
                token_type: 'bearer'
            }
            const mockUser = {
                id: 'user-1',
                email: 'test@example.com'
            }

            // httpClient.post returns data directly, not { data: ... }
            mockApiInstance.post.mockResolvedValueOnce({ data: mockTokenResponse })
            mockApiInstance.get.mockResolvedValueOnce({ data: mockUser })

            const result = await authAPI.login('test@example.com', 'password')

            expect(mockApiInstance.post).toHaveBeenCalledWith('/auth/token', expect.any(FormData), expect.any(Object))
            expect(mockApiInstance.get).toHaveBeenCalledWith('/auth/me', expect.any(Object))
            expect(result).toEqual({ token: 'test-token', user: mockUser })
        })

        it('verifyToken should return user', async () => {
            const mockData = { id: '1' }
            mockApiInstance.get.mockResolvedValue({ data: mockData })
            const result = await authAPI.verifyToken('token')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/auth/me', undefined)
            expect(result).toEqual(mockData)
        })
    })

    describe('tenantAPI', () => {
        it('list should return tenants', async () => {
            const mockData = {
                tenants: [{ id: 't1', name: 'Tenant 1' }],
                total: 1
            }
            mockApiInstance.get.mockResolvedValue({ data: mockData })

            const result = await tenantAPI.list()

            expect(mockApiInstance.get).toHaveBeenCalledWith('/tenants/', { params: {} })
            expect(result).toEqual(mockData)
        })

        it('create should create tenant', async () => {
            const mockData = { id: '1' }
            mockApiInstance.post.mockResolvedValue({ data: mockData })
            const result = await tenantAPI.create({ name: 'T1' } as any)
            expect(mockApiInstance.post).toHaveBeenCalledWith('/tenants/', { name: 'T1' }, undefined)
            expect(result).toEqual(mockData)
        })

        it('update should update tenant', async () => {
            const mockData = { id: '1' }
            mockApiInstance.put.mockResolvedValue({ data: mockData })
            const result = await tenantAPI.update('1', { name: 'T2' })
            expect(mockApiInstance.put).toHaveBeenCalledWith('/tenants/1', { name: 'T2' }, undefined)
            expect(result).toEqual(mockData)
        })

        it('delete should delete tenant', async () => {
            mockApiInstance.delete.mockResolvedValue({})
            await tenantAPI.delete('1')
            expect(mockApiInstance.delete).toHaveBeenCalledWith('/tenants/1', undefined)
        })

        it('get should get tenant', async () => {
            const mockData = { id: '1' }
            mockApiInstance.get.mockResolvedValue({ data: mockData })
            const result = await tenantAPI.get('1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/tenants/1', undefined)
            expect(result).toEqual(mockData)
        })

        it('addMember should add member', async () => {
            mockApiInstance.post.mockResolvedValue({})
            await tenantAPI.addMember('t1', 'u1', 'admin')
            expect(mockApiInstance.post).toHaveBeenCalledWith('/tenants/t1/members', { user_id: 'u1', role: 'admin' }, undefined)
        })

        it('removeMember should remove member', async () => {
            mockApiInstance.delete.mockResolvedValue({})
            await tenantAPI.removeMember('t1', 'u1')
            expect(mockApiInstance.delete).toHaveBeenCalledWith('/tenants/t1/members/u1', undefined)
        })

        it('listMembers should list members', async () => {
            const mockData: unknown[] = []
            mockApiInstance.get.mockResolvedValue({ data: mockData })
            await tenantAPI.listMembers('t1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/tenants/t1/members', undefined)
        })
    })

    describe('projectAPI', () => {
        it('list should return projects for tenant', async () => {
            const mockData = {
                projects: [{ id: 'p1', name: 'Project 1' }],
                total: 1
            }
            mockApiInstance.get.mockResolvedValue({ data: mockData })

            const result = await projectAPI.list('tenant-1')

            expect(mockApiInstance.get).toHaveBeenCalledWith('/projects/', { params: { tenant_id: 'tenant-1' } })
            expect(result).toEqual(mockData)
        })

        it('create should create project', async () => {
            const mockData = { id: '1' }
            mockApiInstance.post.mockResolvedValue({ data: mockData })
            const result = await projectAPI.create('t1', { name: 'P1' } as any)
            expect(mockApiInstance.post).toHaveBeenCalledWith('/projects/', { name: 'P1', tenant_id: 't1' }, undefined)
            expect(result).toEqual(mockData)
        })

        it('update should update project', async () => {
            const mockData = { id: '1' }
            mockApiInstance.put.mockResolvedValue({ data: mockData })
            const result = await projectAPI.update('t1', 'p1', { name: 'P2' } as any)
            expect(mockApiInstance.put).toHaveBeenCalledWith('/projects/p1', { name: 'P2' }, undefined)
            expect(result).toEqual(mockData)
        })

        it('delete should delete project', async () => {
            mockApiInstance.delete.mockResolvedValue({})
            await projectAPI.delete('t1', 'p1')
            expect(mockApiInstance.delete).toHaveBeenCalledWith('/projects/p1', undefined)
        })

        it('get should get project', async () => {
            const mockData = { id: '1' }
            mockApiInstance.get.mockResolvedValue({ data: mockData })
            const result = await projectAPI.get('t1', 'p1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/projects/p1', undefined)
            expect(result).toEqual(mockData)
        })
    })

    describe('memoryAPI', () => {
        it('list should list memories', async () => {
            const mockData: unknown[] = []
            mockApiInstance.get.mockResolvedValue({ data: mockData })
            await memoryAPI.list('p1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/memories/', { params: { project_id: 'p1' } })
        })

        it('create should create memory', async () => {
            const mockData = { id: '1' }
            mockApiInstance.post.mockResolvedValue({ data: mockData })
            await memoryAPI.create('p1', { title: 'M1' } as MemoryCreate)
            expect(mockApiInstance.post).toHaveBeenCalledWith('/memories/', { title: 'M1', project_id: 'p1' }, undefined)
        })

        it('update should update memory', async () => {
            const mockData = { id: '1' }
            mockApiInstance.patch.mockResolvedValue({ data: mockData })
            await memoryAPI.update('p1', 'm1', { title: 'M2' } as MemoryUpdate)
            expect(mockApiInstance.patch).toHaveBeenCalledWith('/memories/m1', { title: 'M2' }, undefined)
        })

        it('delete should delete memory', async () => {
            mockApiInstance.delete.mockResolvedValue({})
            await memoryAPI.delete('p1', 'm1')
            expect(mockApiInstance.delete).toHaveBeenCalledWith('/memories/m1', undefined)
        })

        it('get should get memory', async () => {
            const mockData = { id: '1' }
            mockApiInstance.get.mockResolvedValue({ data: mockData })
            await memoryAPI.get('p1', 'm1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/memories/m1', undefined)
        })

        it('search should return results', async () => {
            const mockData = {
                results: [{ id: 'm1', content: 'memory 1' }],
                total: 1
            }
            mockApiInstance.post.mockResolvedValue({ data: mockData })

            const result = await memoryAPI.search('project-1', { query: 'test' })

            expect(mockApiInstance.post).toHaveBeenCalledWith('/memory/search', { query: 'test', project_id: 'project-1' }, undefined)
            expect(result).toEqual(mockData)
        })

        it('getGraphData should get graph', async () => {
            const mockData = {}
            mockApiInstance.get.mockResolvedValue({ data: mockData })
            await memoryAPI.getGraphData('p1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/memory/graph', { params: { project_id: 'p1' } })
        })

        it('extractEntities should extract', async () => {
            const mockData: Entity[] = []
            mockApiInstance.post.mockResolvedValue({ data: mockData })
            await memoryAPI.extractEntities('p1', 'text')
            expect(mockApiInstance.post).toHaveBeenCalledWith('/memories/extract-entities', { text: 'text', project_id: 'p1' }, undefined)
        })

        it('extractRelationships should extract', async () => {
            const mockData: Relationship[] = []
            mockApiInstance.post.mockResolvedValue({ data: mockData })
            await memoryAPI.extractRelationships('p1', 'text')
            expect(mockApiInstance.post).toHaveBeenCalledWith('/memories/extract-relationships', { text: 'text', project_id: 'p1' }, undefined)
        })
    })
})
