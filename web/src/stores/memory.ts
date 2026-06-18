import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

import { memoryAPI } from '../services/api';

import type { UnknownError } from '../types/common';
import type {
  Memory,
  MemoryCreate,
  MemoryUpdate,
  MemoryQuery,
  MemorySearchResponse,
  Entity,
  Relationship,
  GraphData,
} from '../types/memory';

/**
 * Helper function to extract error message from unknown error
 */
function getErrorMessage(error: unknown, fallback: string): string {
  const err = error as UnknownError;
  if (err.response?.data?.detail) {
    const detail = err.response.data.detail;
    return typeof detail === 'string' ? detail : JSON.stringify(detail);
  }
  if (err.message) {
    return err.message;
  }
  return fallback;
}

interface MemoryState {
  memories: Memory[];
  currentMemory: Memory | null;
  isLoading: boolean;
  error: string | null;
  total: number;
  page: number;
  pageSize: number;

  // Graph data
  graphData: GraphData | null;
  entities: Entity[];
  relationships: Relationship[];

  // Actions
  listMemories: (
    projectId: string,
    params?: {
      page?: number | undefined;
      page_size?: number | undefined;
      search?: string | undefined;
      entity?: string | undefined;
      relationship?: string | undefined;
    }
  ) => Promise<void>;
  createMemory: (projectId: string, data: MemoryCreate) => Promise<void>;
  updateMemory: (projectId: string, memoryId: string, data: MemoryUpdate) => Promise<void>;
  deleteMemory: (projectId: string, memoryId: string) => Promise<void>;
  searchMemories: (projectId: string, query: MemoryQuery) => Promise<MemorySearchResponse>;
  getMemory: (projectId: string, memoryId: string) => Promise<Memory>;

  // Graph operations
  getGraphData: (
    projectId: string,
    options?: { limit?: number | undefined; entity_types?: string[] | undefined }
  ) => Promise<GraphData>;
  extractEntities: (projectId: string, text: string) => Promise<Entity[]>;
  extractRelationships: (projectId: string, text: string) => Promise<Relationship[]>;

  clearError: () => void;
  setCurrentMemory: (memory: Memory | null) => void;
  reset: () => void;
}

const initialState = {
  memories: [] as Memory[],
  currentMemory: null as Memory | null,
  isLoading: false,
  error: null as string | null,
  total: 0,
  page: 1,
  pageSize: 20,
  graphData: null as GraphData | null,
  entities: [] as Entity[],
  relationships: [] as Relationship[],
};

let latestListMemoriesRequest = 0;
let latestGraphDataRequest = 0;
let latestExtractEntitiesRequest = 0;
let latestExtractRelationshipsRequest = 0;

function invalidateMemoryReadRequests(): void {
  latestListMemoriesRequest += 1;
  latestGraphDataRequest += 1;
  latestExtractEntitiesRequest += 1;
  latestExtractRelationshipsRequest += 1;
}

export const useMemoryStore = create<MemoryState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      listMemories: async (projectId: string, params = {}) => {
        const requestId = latestListMemoriesRequest + 1;
        latestListMemoriesRequest = requestId;
        set({ isLoading: true, error: null });
        try {
          const response = await memoryAPI.list(projectId, params);
          if (requestId !== latestListMemoriesRequest) return;
          set({
            memories: response.memories,
            total: response.total,
            page: response.page,
            pageSize: response.page_size,
            isLoading: false,
          });
        } catch (error: unknown) {
          if (requestId !== latestListMemoriesRequest) return;
          set({
            error: getErrorMessage(error, 'Failed to list memories'),
            isLoading: false,
          });
          throw error;
        }
      },

      createMemory: async (projectId: string, data: MemoryCreate) => {
        set({ isLoading: true, error: null });
        try {
          const response = await memoryAPI.create(projectId, data);
          const { memories } = get();
          set({
            memories: [response, ...memories],
            isLoading: false,
          });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to create memory'),
            isLoading: false,
          });
          throw error;
        }
      },

      updateMemory: async (projectId: string, memoryId: string, data: MemoryUpdate) => {
        set({ isLoading: true, error: null });
        try {
          const response = await memoryAPI.update(projectId, memoryId, data);
          const { memories } = get();
          set({
            memories: memories.map((memory) => (memory.id === memoryId ? response : memory)),
            currentMemory: get().currentMemory?.id === memoryId ? response : get().currentMemory,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to update memory'),
            isLoading: false,
          });
          throw error;
        }
      },

      deleteMemory: async (projectId: string, memoryId: string) => {
        set({ isLoading: true, error: null });
        try {
          await memoryAPI.delete(projectId, memoryId);
          const { memories } = get();
          set({
            memories: memories.filter((memory) => memory.id !== memoryId),
            currentMemory: get().currentMemory?.id === memoryId ? null : get().currentMemory,
            isLoading: false,
          });
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to delete memory'),
            isLoading: false,
          });
          throw error;
        }
      },

      searchMemories: async (projectId: string, query: MemoryQuery) => {
        set({ isLoading: true, error: null });
        try {
          const response = await memoryAPI.search(projectId, query);
          set({ isLoading: false });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to search memories'),
            isLoading: false,
          });
          throw error;
        }
      },

      getMemory: async (projectId: string, memoryId: string) => {
        set({ isLoading: true, error: null });
        try {
          const response = await memoryAPI.get(projectId, memoryId);
          set({ isLoading: false });
          return response;
        } catch (error: unknown) {
          set({
            error: getErrorMessage(error, 'Failed to get memory'),
            isLoading: false,
          });
          throw error;
        }
      },

      getGraphData: async (projectId: string, options = {}) => {
        const requestId = latestGraphDataRequest + 1;
        latestGraphDataRequest = requestId;
        set({ isLoading: true, error: null });
        try {
          const response = await memoryAPI.getGraphData(projectId, options);
          if (requestId !== latestGraphDataRequest) return response;
          set({
            graphData: response,
            entities: response.entities,
            relationships: response.relationships,
            isLoading: false,
          });
          return response;
        } catch (error: unknown) {
          if (requestId !== latestGraphDataRequest) throw error;
          set({
            error: getErrorMessage(error, 'Failed to get graph data'),
            isLoading: false,
          });
          throw error;
        }
      },

      extractEntities: async (projectId: string, text: string) => {
        const requestId = latestExtractEntitiesRequest + 1;
        latestExtractEntitiesRequest = requestId;
        set({ isLoading: true, error: null });
        try {
          const response = await memoryAPI.extractEntities(projectId, text);
          if (requestId !== latestExtractEntitiesRequest) return response;
          set({
            entities: response,
            isLoading: false,
          });
          return response;
        } catch (error: unknown) {
          if (requestId !== latestExtractEntitiesRequest) throw error;
          set({
            error: getErrorMessage(error, 'Failed to extract entities'),
            isLoading: false,
          });
          throw error;
        }
      },

      extractRelationships: async (projectId: string, text: string) => {
        const requestId = latestExtractRelationshipsRequest + 1;
        latestExtractRelationshipsRequest = requestId;
        set({ isLoading: true, error: null });
        try {
          const response = await memoryAPI.extractRelationships(projectId, text);
          if (requestId !== latestExtractRelationshipsRequest) return response;
          set({
            relationships: response,
            isLoading: false,
          });
          return response;
        } catch (error: unknown) {
          if (requestId !== latestExtractRelationshipsRequest) throw error;
          set({
            error: getErrorMessage(error, 'Failed to extract relationships'),
            isLoading: false,
          });
          throw error;
        }
      },

      clearError: () => {
        set({ error: null });
      },
      setCurrentMemory: (memory: Memory | null) => {
        set({ currentMemory: memory });
      },
      reset: () => {
        invalidateMemoryReadRequests();
        set(initialState);
      },
    }),
    {
      name: 'MemoryStore',
      enabled: import.meta.env.DEV,
    }
  )
);

// ============================================================================
// SELECTORS - Fine-grained subscriptions for performance
// ============================================================================

// Memory data selectors
export const useMemories = () => useMemoryStore((state) => state.memories);
export const useCurrentMemory = () => useMemoryStore((state) => state.currentMemory);
export const useMemoryTotal = () => useMemoryStore((state) => state.total);
export const useMemoryPage = () => useMemoryStore((state) => state.page);
export const useMemoryPageSize = () => useMemoryStore((state) => state.pageSize);

// Loading and error selectors
export const useMemoryLoading = () => useMemoryStore((state) => state.isLoading);
export const useMemoryError = () => useMemoryStore((state) => state.error);

// Graph data selectors
export const useGraphData = () => useMemoryStore((state) => state.graphData);
export const useEntities = () => useMemoryStore((state) => state.entities);
export const useRelationships = () => useMemoryStore((state) => state.relationships);

// Action selectors
export const useMemoryActions = () =>
  useMemoryStore(
    useShallow((state) => ({
      listMemories: state.listMemories,
      createMemory: state.createMemory,
      updateMemory: state.updateMemory,
      deleteMemory: state.deleteMemory,
      searchMemories: state.searchMemories,
      getMemory: state.getMemory,
      getGraphData: state.getGraphData,
      extractEntities: state.extractEntities,
      extractRelationships: state.extractRelationships,
      clearError: state.clearError,
      setCurrentMemory: state.setCurrentMemory,
      reset: state.reset,
    }))
  );
