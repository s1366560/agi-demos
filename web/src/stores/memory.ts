import { create } from 'zustand';
import { memoryAPI } from '../services/api';
import type { 
  Memory, 
  MemoryCreate, 
  MemoryUpdate, 
  MemoryQuery, 
  MemorySearchResponse,
  Entity,
  Relationship,
  GraphData
} from '../types/memory';

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
  listMemories: (projectId: string, params?: { page?: number; page_size?: number; search?: string; entity?: string; relationship?: string }) => Promise<void>;
  createMemory: (projectId: string, data: MemoryCreate) => Promise<void>;
  updateMemory: (projectId: string, memoryId: string, data: MemoryUpdate) => Promise<void>;
  deleteMemory: (projectId: string, memoryId: string) => Promise<void>;
  searchMemories: (projectId: string, query: MemoryQuery) => Promise<MemorySearchResponse>;
  getMemory: (projectId: string, memoryId: string) => Promise<Memory>;
  
  // Graph operations
  getGraphData: (projectId: string, options?: { limit?: number; entity_types?: string[] }) => Promise<GraphData>;
  extractEntities: (projectId: string, text: string) => Promise<Entity[]>;
  extractRelationships: (projectId: string, text: string) => Promise<Relationship[]>;
  
  clearError: () => void;
  setCurrentMemory: (memory: Memory | null) => void;
}

export const useMemoryStore = create<MemoryState>((set, get) => ({
  memories: [],
  currentMemory: null,
  isLoading: false,
  error: null,
  total: 0,
  page: 1,
  pageSize: 20,
  graphData: null,
  entities: [],
  relationships: [],

  listMemories: async (projectId: string, params = {}) => {
    set({ isLoading: true, error: null });
    try {
      const response = await memoryAPI.list(projectId, params);
      set({
        memories: response.memories,
        total: response.total,
        page: response.page,
        pageSize: response.page_size,
        isLoading: false,
      });
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || 'Failed to list memories', 
        isLoading: false 
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
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || 'Failed to create memory', 
        isLoading: false 
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
        memories: memories.map(memory => memory.id === memoryId ? response : memory),
        currentMemory: get().currentMemory?.id === memoryId ? response : get().currentMemory,
        isLoading: false,
      });
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || 'Failed to update memory', 
        isLoading: false 
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
        memories: memories.filter(memory => memory.id !== memoryId),
        currentMemory: get().currentMemory?.id === memoryId ? null : get().currentMemory,
        isLoading: false,
      });
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || 'Failed to delete memory', 
        isLoading: false 
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
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || 'Failed to search memories', 
        isLoading: false 
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
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || 'Failed to get memory', 
        isLoading: false 
      });
      throw error;
    }
  },

  getGraphData: async (projectId: string, options = {}) => {
    set({ isLoading: true, error: null });
    try {
      const response = await memoryAPI.getGraphData(projectId, options);
      set({
        graphData: response,
        entities: response.entities,
        relationships: response.relationships,
        isLoading: false,
      });
      return response;
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || 'Failed to get graph data', 
        isLoading: false 
      });
      throw error;
    }
  },

  extractEntities: async (projectId: string, text: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await memoryAPI.extractEntities(projectId, text);
      set({
        entities: response,
        isLoading: false,
      });
      return response;
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || 'Failed to extract entities', 
        isLoading: false 
      });
      throw error;
    }
  },

  extractRelationships: async (projectId: string, text: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await memoryAPI.extractRelationships(projectId, text);
      set({
        relationships: response,
        isLoading: false,
      });
      return response;
    } catch (error: any) {
      set({ 
        error: error.response?.data?.detail || 'Failed to extract relationships', 
        isLoading: false 
      });
      throw error;
    }
  },

  clearError: () => set({ error: null }),
  setCurrentMemory: (memory: Memory | null) => set({ currentMemory: memory }),
}));

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
  useMemoryStore((state) => ({
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
  }));