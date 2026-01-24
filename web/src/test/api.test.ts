import { describe, it, expect, vi, beforeEach } from 'vitest'
import { authAPI, tenantAPI, projectAPI, memoryAPI } from '../services/api'

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
                data: {
                    access_token: 'test-token',
                    token_type: 'bearer'
                }
            }
            const mockUserResponse = {
                data: {
                    id: 'user-1',
                    email: 'test@example.com'
                }
            }

            mockApiInstance.post.mockResolvedValueOnce(mockTokenResponse)
            mockApiInstance.get.mockResolvedValueOnce(mockUserResponse)

            const result = await authAPI.login('test@example.com', 'password')

            expect(mockApiInstance.post).toHaveBeenCalledWith('/auth/token', expect.any(FormData), expect.any(Object))
            expect(mockApiInstance.get).toHaveBeenCalledWith('/auth/me', expect.any(Object))
            expect(result).toEqual({ token: 'test-token', user: mockUserResponse.data })
        })

        it('verifyToken should return user', async () => {
            const mockResponse = { data: { id: '1' } }
            mockApiInstance.get.mockResolvedValue(mockResponse)
            const result = await authAPI.verifyToken('token')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/auth/me')
            expect(result).toEqual(mockResponse.data)
        })
    })

    describe('tenantAPI', () => {
        it('list should return tenants', async () => {
            const mockResponse = {
                data: {
                    tenants: [{ id: 't1', name: 'Tenant 1' }],
                    total: 1
                }
            }
            mockApiInstance.get.mockResolvedValue(mockResponse)

            const result = await tenantAPI.list()

            expect(mockApiInstance.get).toHaveBeenCalledWith('/tenants/', { params: {} })
            expect(result).toEqual(mockResponse.data)
        })

        it('create should create tenant', async () => {
            const mockResponse = { data: { id: '1' } }
            mockApiInstance.post.mockResolvedValue(mockResponse)
            const result = await tenantAPI.create({ name: 'T1' } as any)
            expect(mockApiInstance.post).toHaveBeenCalledWith('/tenants/', { name: 'T1' })
            expect(result).toEqual(mockResponse.data)
        })

        it('update should update tenant', async () => {
            const mockResponse = { data: { id: '1' } }
            mockApiInstance.put.mockResolvedValue(mockResponse)
            const result = await tenantAPI.update('1', { name: 'T2' })
            expect(mockApiInstance.put).toHaveBeenCalledWith('/tenants/1', { name: 'T2' })
            expect(result).toEqual(mockResponse.data)
        })

        it('delete should delete tenant', async () => {
            mockApiInstance.delete.mockResolvedValue({})
            await tenantAPI.delete('1')
            expect(mockApiInstance.delete).toHaveBeenCalledWith('/tenants/1')
        })

        it('get should get tenant', async () => {
            const mockResponse = { data: { id: '1' } }
            mockApiInstance.get.mockResolvedValue(mockResponse)
            const result = await tenantAPI.get('1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/tenants/1')
            expect(result).toEqual(mockResponse.data)
        })

        it('addMember should add member', async () => {
            mockApiInstance.post.mockResolvedValue({})
            await tenantAPI.addMember('t1', 'u1', 'admin')
            expect(mockApiInstance.post).toHaveBeenCalledWith('/tenants/t1/members', { user_id: 'u1', role: 'admin' })
        })

        it('removeMember should remove member', async () => {
            mockApiInstance.delete.mockResolvedValue({})
            await tenantAPI.removeMember('t1', 'u1')
            expect(mockApiInstance.delete).toHaveBeenCalledWith('/tenants/t1/members/u1')
        })

        it('listMembers should list members', async () => {
            const mockResponse = { data: [] }
            mockApiInstance.get.mockResolvedValue(mockResponse)
            await tenantAPI.listMembers('t1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/tenants/t1/members')
        })
    })

    describe('projectAPI', () => {
        it('list should return projects for tenant', async () => {
            const mockResponse = {
                data: {
                    projects: [{ id: 'p1', name: 'Project 1' }],
                    total: 1
                }
            }
            mockApiInstance.get.mockResolvedValue(mockResponse)

            const result = await projectAPI.list('tenant-1')

            expect(mockApiInstance.get).toHaveBeenCalledWith('/projects/', { params: { tenant_id: 'tenant-1' } })
            expect(result).toEqual(mockResponse.data)
        })

        it('create should create project', async () => {
            const mockResponse = { data: { id: '1' } }
            mockApiInstance.post.mockResolvedValue(mockResponse)
            const result = await projectAPI.create('t1', { name: 'P1' } as any)
            expect(mockApiInstance.post).toHaveBeenCalledWith('/projects/', { name: 'P1', tenant_id: 't1' })
            expect(result).toEqual(mockResponse.data)
        })

        it('update should update project', async () => {
            const mockResponse = { data: { id: '1' } }
            mockApiInstance.put.mockResolvedValue(mockResponse)
            const result = await projectAPI.update('t1', 'p1', { name: 'P2' } as any)
            expect(mockApiInstance.put).toHaveBeenCalledWith('/projects/p1', { name: 'P2' })
            expect(result).toEqual(mockResponse.data)
        })

        it('delete should delete project', async () => {
            mockApiInstance.delete.mockResolvedValue({})
            await projectAPI.delete('t1', 'p1')
            expect(mockApiInstance.delete).toHaveBeenCalledWith('/projects/p1')
        })

        it('get should get project', async () => {
            const mockResponse = { data: { id: '1' } }
            mockApiInstance.get.mockResolvedValue(mockResponse)
            const result = await projectAPI.get('t1', 'p1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/projects/p1')
            expect(result).toEqual(mockResponse.data)
        })
    })

    describe('memoryAPI', () => {
        it('list should list memories', async () => {
            const mockResponse = { data: [] }
            mockApiInstance.get.mockResolvedValue(mockResponse)
            await memoryAPI.list('p1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/memories/', { params: { project_id: 'p1' } })
        })

        it('create should create memory', async () => {
            const mockResponse = { data: { id: '1' } }
            mockApiInstance.post.mockResolvedValue(mockResponse)
            await memoryAPI.create('p1', { title: 'M1' } as any)
            expect(mockApiInstance.post).toHaveBeenCalledWith('/memories/', { title: 'M1', project_id: 'p1' })
        })

        it('update should update memory', async () => {
            const mockResponse = { data: { id: '1' } }
            mockApiInstance.patch.mockResolvedValue(mockResponse)
            await memoryAPI.update('p1', 'm1', { title: 'M2' } as any)
            expect(mockApiInstance.patch).toHaveBeenCalledWith('/memories/m1', { title: 'M2' })
        })

        it('delete should delete memory', async () => {
            mockApiInstance.delete.mockResolvedValue({})
            await memoryAPI.delete('p1', 'm1')
            expect(mockApiInstance.delete).toHaveBeenCalledWith('/memories/m1')
        })

        it('get should get memory', async () => {
            const mockResponse = { data: { id: '1' } }
            mockApiInstance.get.mockResolvedValue(mockResponse)
            await memoryAPI.get('p1', 'm1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/memories/m1')
        })

        it('search should return results', async () => {
            const mockResponse = {
                data: {
                    results: [{ id: 'm1', content: 'memory 1' }],
                    total: 1
                }
            }
            mockApiInstance.post.mockResolvedValue(mockResponse)

            const result = await memoryAPI.search('project-1', { query: 'test' })

            expect(mockApiInstance.post).toHaveBeenCalledWith('/memory/search', { query: 'test', project_id: 'project-1' })
            expect(result).toEqual(mockResponse.data)
        })

        it('getGraphData should get graph', async () => {
            const mockResponse = { data: {} }
            mockApiInstance.get.mockResolvedValue(mockResponse)
            await memoryAPI.getGraphData('p1')
            expect(mockApiInstance.get).toHaveBeenCalledWith('/memory/graph', { params: { project_id: 'p1' } })
        })

        it('extractEntities should extract', async () => {
            const mockResponse = { data: [] }
            mockApiInstance.post.mockResolvedValue(mockResponse)
            await memoryAPI.extractEntities('p1', 'text')
            expect(mockApiInstance.post).toHaveBeenCalledWith('/memories/extract-entities', { text: 'text', project_id: 'p1' })
        })

        it('extractRelationships should extract', async () => {
            const mockResponse = { data: [] }
            mockApiInstance.post.mockResolvedValue(mockResponse)
            await memoryAPI.extractRelationships('p1', 'text')
            expect(mockApiInstance.post).toHaveBeenCalledWith('/memories/extract-relationships', { text: 'text', project_id: 'p1' })
        })
    })
})
