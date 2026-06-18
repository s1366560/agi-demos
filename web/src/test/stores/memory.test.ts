import { describe, it, expect, vi, beforeEach } from 'vitest';

import { memoryAPI } from '../../services/api';
import { useMemoryStore } from '../../stores/memory';

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
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

describe('MemoryStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useMemoryStore.getState().reset();
  });

  it('listMemories should update state on success', async () => {
    const mockResponse = {
      memories: [{ id: '1', title: 'Memory 1' }],
      total: 1,
      page: 1,
      page_size: 20,
    };
    (memoryAPI.list as any).mockResolvedValue(mockResponse);

    await useMemoryStore.getState().listMemories('project-1');

    expect(memoryAPI.list).toHaveBeenCalledWith('project-1', {});
    expect(useMemoryStore.getState().memories).toEqual(mockResponse.memories);
    expect(useMemoryStore.getState().total).toBe(1);
  });

  it('listMemories should ignore stale responses from older project requests', async () => {
    const oldProjectResponse = deferred<Awaited<ReturnType<typeof memoryAPI.list>>>();
    const newProjectResponse = {
      memories: [{ id: 'new-memory', title: 'New Project Memory' }],
      total: 1,
      page: 1,
      page_size: 20,
    };

    vi.mocked(memoryAPI.list)
      .mockReturnValueOnce(oldProjectResponse.promise)
      .mockResolvedValueOnce(newProjectResponse as never);

    const oldLoad = useMemoryStore.getState().listMemories('project-old');
    const newLoad = useMemoryStore.getState().listMemories('project-new');

    await newLoad;
    oldProjectResponse.resolve({
      memories: [{ id: 'old-memory', title: 'Old Project Memory' }],
      total: 1,
      page: 1,
      page_size: 20,
    });
    await oldLoad;

    expect(useMemoryStore.getState().memories).toEqual(newProjectResponse.memories);
    expect(useMemoryStore.getState().total).toBe(1);
    expect(useMemoryStore.getState().isLoading).toBe(false);
  });

  it('createMemory should add memory to list', async () => {
    const newMemory = { id: '2', title: 'New Memory' };
    (memoryAPI.create as any).mockResolvedValue(newMemory);

    await useMemoryStore.getState().createMemory('project-1', { title: 'New Memory' } as any);

    expect(memoryAPI.create).toHaveBeenCalledWith('project-1', { title: 'New Memory' });
    expect(useMemoryStore.getState().memories).toContainEqual(newMemory);
  });

  it('updateMemory should update memory in list', async () => {
    useMemoryStore.setState({ memories: [{ id: '1', title: 'Old Title' } as any] });
    const updatedMemory = { id: '1', title: 'New Title' };
    (memoryAPI.update as any).mockResolvedValue(updatedMemory);

    await useMemoryStore.getState().updateMemory('project-1', '1', { title: 'New Title' } as any);

    expect(memoryAPI.update).toHaveBeenCalledWith('project-1', '1', { title: 'New Title' });
    expect(useMemoryStore.getState().memories[0]).toEqual(updatedMemory);
  });

  it('deleteMemory should remove memory from list', async () => {
    useMemoryStore.setState({ memories: [{ id: '1', title: 'Memory 1' } as any] });
    (memoryAPI.delete as any).mockResolvedValue({});

    await useMemoryStore.getState().deleteMemory('project-1', '1');

    expect(memoryAPI.delete).toHaveBeenCalledWith('project-1', '1');
    expect(useMemoryStore.getState().memories).toHaveLength(0);
  });

  it('getGraphData should update state', async () => {
    const mockGraph = { nodes: [], edges: [], entities: [], relationships: [] };
    (memoryAPI.getGraphData as any).mockResolvedValue(mockGraph);

    await useMemoryStore.getState().getGraphData('project-1');

    expect(memoryAPI.getGraphData).toHaveBeenCalledWith('project-1', {});
    expect(useMemoryStore.getState().graphData).toEqual(mockGraph);
  });

  it('getGraphData should ignore stale responses from older project requests', async () => {
    const oldGraphResponse = deferred<Awaited<ReturnType<typeof memoryAPI.getGraphData>>>();
    const newGraph = {
      entities: [{ id: 'new-entity', name: 'New', type: 'topic', properties: {}, confidence: 1 }],
      relationships: [],
    };

    vi.mocked(memoryAPI.getGraphData)
      .mockReturnValueOnce(oldGraphResponse.promise)
      .mockResolvedValueOnce(newGraph);

    const oldLoad = useMemoryStore.getState().getGraphData('project-old');
    const newLoad = useMemoryStore.getState().getGraphData('project-new');

    await newLoad;
    oldGraphResponse.resolve({
      entities: [{ id: 'old-entity', name: 'Old', type: 'topic', properties: {}, confidence: 1 }],
      relationships: [],
    });
    await oldLoad;

    expect(useMemoryStore.getState().graphData).toEqual(newGraph);
    expect(useMemoryStore.getState().entities).toEqual(newGraph.entities);
    expect(useMemoryStore.getState().isLoading).toBe(false);
  });
});
