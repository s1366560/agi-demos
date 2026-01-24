import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useMemoryStore } from '../../stores/memory'
import { memoryAPI } from '../../services/api'

vi.mock('../../services/api', () => ({
    memoryAPI: {
        list: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        delete: vi.fn(),
        search: vi.fn(),
        get: vi.fn(),
        getGraphData: vi.fn(),
        extractEntities: vi.fn(),
        extractRelationships: vi.fn(),
    }
}))

describe('MemoryStore', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useMemoryStore.setState({
            memories: [],
            currentMemory: null,
            isLoading: false,
            error: null,
            total: 0,
            page: 1,
            pageSize: 20,
            graphData: null,
            entities: [],
            relationships: []
        })
    })

    it('listMemories should update state on success', async () => {
        const mockResponse = {
            memories: [{ id: '1', title: 'Memory 1' }],
            total: 1,
            page: 1,
            page_size: 20
        }
            ; (memoryAPI.list as any).mockResolvedValue(mockResponse)

        await useMemoryStore.getState().listMemories('project-1')

        expect(memoryAPI.list).toHaveBeenCalledWith('project-1', {})
        expect(useMemoryStore.getState().memories).toEqual(mockResponse.memories)
        expect(useMemoryStore.getState().total).toBe(1)
    })

    it('createMemory should add memory to list', async () => {
        const newMemory = { id: '2', title: 'New Memory' }
            ; (memoryAPI.create as any).mockResolvedValue(newMemory)

        await useMemoryStore.getState().createMemory('project-1', { title: 'New Memory' } as any)

        expect(memoryAPI.create).toHaveBeenCalledWith('project-1', { title: 'New Memory' })
        expect(useMemoryStore.getState().memories).toContainEqual(newMemory)
    })

    it('updateMemory should update memory in list', async () => {
        useMemoryStore.setState({ memories: [{ id: '1', title: 'Old Title' } as any] })
        const updatedMemory = { id: '1', title: 'New Title' }
            ; (memoryAPI.update as any).mockResolvedValue(updatedMemory)

        await useMemoryStore.getState().updateMemory('project-1', '1', { title: 'New Title' } as any)

        expect(memoryAPI.update).toHaveBeenCalledWith('project-1', '1', { title: 'New Title' })
        expect(useMemoryStore.getState().memories[0]).toEqual(updatedMemory)
    })

    it('deleteMemory should remove memory from list', async () => {
        useMemoryStore.setState({ memories: [{ id: '1', title: 'Memory 1' } as any] })
            ; (memoryAPI.delete as any).mockResolvedValue({})

        await useMemoryStore.getState().deleteMemory('project-1', '1')

        expect(memoryAPI.delete).toHaveBeenCalledWith('project-1', '1')
        expect(useMemoryStore.getState().memories).toHaveLength(0)
    })

    it('getGraphData should update state', async () => {
        const mockGraph = { nodes: [], edges: [], entities: [], relationships: [] }
            ; (memoryAPI.getGraphData as any).mockResolvedValue(mockGraph)

        await useMemoryStore.getState().getGraphData('project-1')

        expect(memoryAPI.getGraphData).toHaveBeenCalledWith('project-1', {})
        expect(useMemoryStore.getState().graphData).toEqual(mockGraph)
    })
})
