/**
 * MCP Server Zustand Store
 *
 * State management for MCP (Model Context Protocol) server CRUD operations,
 * tool sync, connection testing, and filtering functionality.
 */

import { create } from "zustand";
import { mcpAPI } from "../services/mcpService";
import type {
  MCPServerResponse,
  MCPServerCreate,
  MCPServerUpdate,
  MCPServerType,
  MCPToolInfo,
  MCPServerTestResponse,
} from "../types/agent";

// ============================================================================
// STATE INTERFACE
// ============================================================================

interface MCPFilters {
  search: string;
  enabled: boolean | null;
  serverType: MCPServerType | null;
}

interface MCPState {
  // Data
  servers: MCPServerResponse[];
  currentServer: MCPServerResponse | null;
  allTools: MCPToolInfo[];

  // Pagination
  total: number;

  // Filters
  filters: MCPFilters;

  // Loading states
  isLoading: boolean;
  isSubmitting: boolean;
  syncingServers: Set<string>; // Server IDs currently syncing
  testingServers: Set<string>; // Server IDs currently testing

  // Error state
  error: string | null;

  // Actions - Server CRUD
  listServers: (params?: {
    enabled_only?: boolean;
    skip?: number;
    limit?: number;
  }) => Promise<void>;
  getServer: (id: string) => Promise<MCPServerResponse>;
  createServer: (data: MCPServerCreate) => Promise<MCPServerResponse>;
  updateServer: (
    id: string,
    data: MCPServerUpdate
  ) => Promise<MCPServerResponse>;
  deleteServer: (id: string) => Promise<void>;
  toggleEnabled: (id: string, enabled: boolean) => Promise<void>;
  setCurrentServer: (server: MCPServerResponse | null) => void;

  // Actions - Sync & Test
  syncServer: (id: string) => Promise<void>;
  testServer: (id: string) => Promise<MCPServerTestResponse>;
  listAllTools: () => Promise<void>;

  // Actions - Filters
  setFilters: (filters: Partial<MCPFilters>) => void;
  resetFilters: () => void;

  // Actions - Utility
  clearError: () => void;
  reset: () => void;
}

// ============================================================================
// INITIAL STATE
// ============================================================================

const initialFilters: MCPFilters = {
  search: "",
  enabled: null,
  serverType: null,
};

const initialState = {
  servers: [],
  currentServer: null,
  allTools: [],
  total: 0,
  filters: initialFilters,
  isLoading: false,
  isSubmitting: false,
  syncingServers: new Set<string>(),
  testingServers: new Set<string>(),
  error: null,
};

// ============================================================================
// STORE CREATION
// ============================================================================

export const useMCPStore = create<MCPState>((set, get) => ({
  ...initialState,

  // ========== Server CRUD ==========

  listServers: async (params = {}) => {
    set({ isLoading: true, error: null });
    try {
      const servers = await mcpAPI.list(params);
      set({
        servers: servers || [],
        total: servers?.length || 0,
        isLoading: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to list MCP servers";
      set({ error: errorMessage, isLoading: false });
      throw error;
    }
  },

  getServer: async (id: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await mcpAPI.get(id);
      set({ currentServer: response, isLoading: false });
      return response;
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to get MCP server";
      set({ error: errorMessage, isLoading: false });
      throw error;
    }
  },

  createServer: async (data: MCPServerCreate) => {
    set({ isSubmitting: true, error: null });
    try {
      const response = await mcpAPI.create(data);
      const { servers } = get();
      set({
        servers: [response, ...servers],
        total: get().total + 1,
        isSubmitting: false,
      });
      return response;
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to create MCP server";
      set({ error: errorMessage, isSubmitting: false });
      throw error;
    }
  },

  updateServer: async (id: string, data: MCPServerUpdate) => {
    set({ isSubmitting: true, error: null });
    try {
      const response = await mcpAPI.update(id, data);
      const { servers } = get();
      set({
        servers: servers.map((s) => (s.id === id ? response : s)),
        currentServer: response,
        isSubmitting: false,
      });
      return response;
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to update MCP server";
      set({ error: errorMessage, isSubmitting: false });
      throw error;
    }
  },

  deleteServer: async (id: string) => {
    set({ isSubmitting: true, error: null });
    try {
      await mcpAPI.delete(id);
      const { servers } = get();
      set({
        servers: servers.filter((s) => s.id !== id),
        total: get().total - 1,
        isSubmitting: false,
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to delete MCP server";
      set({ error: errorMessage, isSubmitting: false });
      throw error;
    }
  },

  toggleEnabled: async (id: string, enabled: boolean) => {
    // Optimistic update
    const { servers } = get();
    const originalServers = [...servers];
    set({
      servers: servers.map((s) => (s.id === id ? { ...s, enabled } : s)),
    });

    try {
      await mcpAPI.toggleEnabled(id, enabled);
    } catch (error: any) {
      // Revert on error
      set({ servers: originalServers });
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to toggle server status";
      set({ error: errorMessage });
      throw error;
    }
  },

  setCurrentServer: (server: MCPServerResponse | null) => {
    set({ currentServer: server });
  },

  // ========== Sync & Test ==========

  syncServer: async (id: string) => {
    const { syncingServers } = get();
    const newSyncing = new Set(syncingServers);
    newSyncing.add(id);
    set({ syncingServers: newSyncing, error: null });

    try {
      const updatedServer = await mcpAPI.sync(id);
      const { servers } = get();
      set({
        servers: servers.map((s) => (s.id === id ? updatedServer : s)),
      });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to sync MCP server tools";
      set({ error: errorMessage });
      throw error;
    } finally {
      const { syncingServers: currentSyncing } = get();
      const updated = new Set(currentSyncing);
      updated.delete(id);
      set({ syncingServers: updated });
    }
  },

  testServer: async (id: string) => {
    const { testingServers } = get();
    const newTesting = new Set(testingServers);
    newTesting.add(id);
    set({ testingServers: newTesting, error: null });

    try {
      const response = await mcpAPI.test(id);
      return response;
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to test MCP server connection";
      set({ error: errorMessage });
      throw error;
    } finally {
      const { testingServers: currentTesting } = get();
      const updated = new Set(currentTesting);
      updated.delete(id);
      set({ testingServers: updated });
    }
  },

  listAllTools: async () => {
    try {
      const tools = await mcpAPI.listAllTools();
      set({ allTools: tools });
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail
        ? typeof error.response.data.detail === "string"
          ? error.response.data.detail
          : JSON.stringify(error.response.data.detail)
        : "Failed to list all tools";
      set({ error: errorMessage });
      throw error;
    }
  },

  // ========== Filters ==========

  setFilters: (filters: Partial<MCPFilters>) => {
    set((state) => ({
      filters: { ...state.filters, ...filters },
    }));
  },

  resetFilters: () => {
    set({ filters: initialFilters });
  },

  // ========== Utility ==========

  clearError: () => {
    set({ error: null });
  },

  reset: () => {
    set({
      ...initialState,
      syncingServers: new Set<string>(),
      testingServers: new Set<string>(),
    });
  },
}));

// ============================================================================
// SELECTOR HOOKS
// ============================================================================

/**
 * Get all servers
 */
export const useMCPServers = () => useMCPStore((state) => state.servers);

/**
 * Get filtered servers based on search and filters
 */
export const useFilteredMCPServers = () =>
  useMCPStore((state) => {
    const { servers, filters } = state;
    return servers.filter((server) => {
      // Search filter
      if (filters.search) {
        const search = filters.search.toLowerCase();
        const matchesName = server.name.toLowerCase().includes(search);
        const matchesDescription = server.description
          ?.toLowerCase()
          .includes(search);
        if (!matchesName && !matchesDescription) {
          return false;
        }
      }

      // Enabled filter
      if (filters.enabled !== null && server.enabled !== filters.enabled) {
        return false;
      }

      // Server type filter
      if (filters.serverType && server.server_type !== filters.serverType) {
        return false;
      }

      return true;
    });
  });

/**
 * Get current server
 */
export const useCurrentMCPServer = () =>
  useMCPStore((state) => state.currentServer);

/**
 * Get loading state
 */
export const useMCPLoading = () => useMCPStore((state) => state.isLoading);

/**
 * Get submitting state
 */
export const useMCPSubmitting = () =>
  useMCPStore((state) => state.isSubmitting);

/**
 * Get error state
 */
export const useMCPError = () => useMCPStore((state) => state.error);

/**
 * Get total count
 */
export const useMCPTotal = () => useMCPStore((state) => state.total);

/**
 * Get filters
 */
export const useMCPFilters = () => useMCPStore((state) => state.filters);

/**
 * Get enabled servers count
 */
export const useEnabledMCPServersCount = () =>
  useMCPStore((state) => state.servers.filter((s) => s.enabled).length);

/**
 * Get total tools count from all servers
 */
export const useTotalMCPToolsCount = () =>
  useMCPStore((state) =>
    state.servers.reduce((sum, s) => sum + (s.discovered_tools?.length || 0), 0)
  );

/**
 * Get servers grouped by type
 * Note: Returns a stable reference using JSON stringification for shallow comparison
 */
export const useMCPServersByType = () => {
  const servers = useMCPStore((state) => state.servers);
  const result: Record<MCPServerType, number> = {
    stdio: 0,
    sse: 0,
    http: 0,
    websocket: 0,
  };
  servers.forEach((s) => {
    result[s.server_type]++;
  });
  return result;
};

/**
 * Check if a server is syncing
 */
export const useIsMCPServerSyncing = (serverId: string) =>
  useMCPStore((state) => state.syncingServers.has(serverId));

/**
 * Check if a server is testing
 */
export const useIsMCPServerTesting = (serverId: string) =>
  useMCPStore((state) => state.testingServers.has(serverId));

/**
 * Get all tools from all servers
 */
export const useAllMCPTools = () => useMCPStore((state) => state.allTools);

export default useMCPStore;
