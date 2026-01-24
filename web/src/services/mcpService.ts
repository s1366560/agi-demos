/**
 * MCP Server API Service
 *
 * Provides API methods for MCP (Model Context Protocol) server management
 * including CRUD operations, tool sync, connection testing, and tool calls.
 */

import axios from "axios";
import type {
  MCPServerResponse,
  MCPServerCreate,
  MCPServerUpdate,
  MCPServerTestResponse,
  MCPToolCallRequest,
  MCPToolCallResponse,
  MCPToolInfo,
} from "../types/agent";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "/api/v1",
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor to add auth token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor to handle errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export interface MCPServerListParams {
  enabled_only?: boolean;
  skip?: number;
  limit?: number;
}

export const mcpAPI = {
  /**
   * List all MCP servers
   */
  list: async (
    params: MCPServerListParams = {}
  ): Promise<MCPServerResponse[]> => {
    const response = await api.get("/mcp", { params });
    return response.data;
  },

  /**
   * Create a new MCP server
   */
  create: async (data: MCPServerCreate): Promise<MCPServerResponse> => {
    const response = await api.post("/mcp", data);
    return response.data;
  },

  /**
   * Get an MCP server by ID
   */
  get: async (serverId: string): Promise<MCPServerResponse> => {
    const response = await api.get(`/mcp/${serverId}`);
    return response.data;
  },

  /**
   * Update an MCP server
   */
  update: async (
    serverId: string,
    data: MCPServerUpdate
  ): Promise<MCPServerResponse> => {
    const response = await api.put(`/mcp/${serverId}`, data);
    return response.data;
  },

  /**
   * Delete an MCP server
   */
  delete: async (serverId: string): Promise<void> => {
    await api.delete(`/mcp/${serverId}`);
  },

  /**
   * Sync tools from an MCP server
   * Discovers and updates the list of available tools
   */
  sync: async (serverId: string): Promise<MCPServerResponse> => {
    const response = await api.post(`/mcp/${serverId}/sync`);
    return response.data;
  },

  /**
   * Test connection to an MCP server
   */
  test: async (serverId: string): Promise<MCPServerTestResponse> => {
    const response = await api.post(`/mcp/${serverId}/test`);
    return response.data;
  },

  /**
   * Toggle server enabled status
   */
  toggleEnabled: async (
    serverId: string,
    enabled: boolean
  ): Promise<MCPServerResponse> => {
    const response = await api.put(`/mcp/${serverId}`, { enabled });
    return response.data;
  },

  /**
   * Get all tools from all enabled MCP servers
   */
  listAllTools: async (): Promise<MCPToolInfo[]> => {
    const response = await api.get("/mcp/tools/all");
    return response.data;
  },

  /**
   * Call a tool on an MCP server
   */
  callTool: async (
    request: MCPToolCallRequest
  ): Promise<MCPToolCallResponse> => {
    const response = await api.post("/mcp/tools/call", request);
    return response.data;
  },
};

export default mcpAPI;
