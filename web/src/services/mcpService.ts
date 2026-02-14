/**
 * MCP Server API Service
 *
 * Provides API methods for MCP (Model Context Protocol) server management
 * including CRUD operations, tool sync, connection testing, and tool calls.
 */

import { httpClient } from './client/httpClient';

import type {
  MCPServerResponse,
  MCPServerCreate,
  MCPServerUpdate,
  MCPServerTestResponse,
  MCPToolCallRequest,
  MCPToolCallResponse,
  MCPToolInfo,
} from '../types/agent';

// Use centralized HTTP client
const api = httpClient;

export interface MCPServerListParams {
  project_id?: string;
  enabled_only?: boolean;
  skip?: number;
  limit?: number;
}

export const mcpAPI = {
  /**
   * List MCP servers, optionally filtered by project
   */
  list: async (params: MCPServerListParams = {}): Promise<MCPServerResponse[]> => {
    return await api.get<MCPServerResponse[]>('/mcp', { params });
  },

  /**
   * Create a new MCP server (project_id is in request body)
   */
  create: async (data: MCPServerCreate): Promise<MCPServerResponse> => {
    return await api.post<MCPServerResponse>('/mcp', data);
  },

  /**
   * Get an MCP server by ID
   */
  get: async (serverId: string): Promise<MCPServerResponse> => {
    return await api.get<MCPServerResponse>(`/mcp/${serverId}`);
  },

  /**
   * Update an MCP server
   */
  update: async (serverId: string, data: MCPServerUpdate): Promise<MCPServerResponse> => {
    return await api.put<MCPServerResponse>(`/mcp/${serverId}`, data);
  },

  /**
   * Delete an MCP server
   */
  delete: async (serverId: string): Promise<void> => {
    await api.delete(`/mcp/${serverId}`);
  },

  /**
   * Sync tools from an MCP server
   * Uses stored project_id from DB for sandbox context
   */
  sync: async (serverId: string): Promise<MCPServerResponse> => {
    return await api.post<MCPServerResponse>(`/mcp/${serverId}/sync`);
  },

  /**
   * Test connection to an MCP server
   * Uses stored project_id from DB for sandbox context
   */
  test: async (serverId: string): Promise<MCPServerTestResponse> => {
    return await api.post<MCPServerTestResponse>(`/mcp/${serverId}/test`);
  },

  /**
   * Toggle server enabled status
   */
  toggleEnabled: async (serverId: string, enabled: boolean): Promise<MCPServerResponse> => {
    return await api.put<MCPServerResponse>(`/mcp/${serverId}`, { enabled });
  },

  /**
   * Get all tools from all enabled MCP servers, optionally filtered by project.
   * Backend returns paginated response; this fetches the first page (up to 200 items).
   */
  listAllTools: async (projectId?: string): Promise<MCPToolInfo[]> => {
    const params: Record<string, string | number> = { per_page: 200 };
    if (projectId) params.project_id = projectId;
    const resp = await api.get<{ items: MCPToolInfo[]; total: number }>(
      '/mcp/tools/all',
      { params },
    );
    return resp.items;
  },

  /**
   * Call a tool on an MCP server
   */
  callTool: async (request: MCPToolCallRequest): Promise<MCPToolCallResponse> => {
    return await api.post<MCPToolCallResponse>('/mcp/tools/call', request);
  },
};

export default mcpAPI;
