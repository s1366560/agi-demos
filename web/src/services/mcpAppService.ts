/**
 * MCP App API Service
 *
 * Provides API methods for MCP App management including listing,
 * resource fetching, tool call proxying, and lifecycle operations.
 */

import { httpClient, type HttpRequestConfig } from './client/httpClient';

export type MCPAppRequestOptions = Pick<HttpRequestConfig, 'operation' | 'signal'>;

import type {
  MCPApp,
  MCPAppResource,
  MCPAppDirectToolCallRequest,
  MCPAppToolCallRequest,
  MCPAppToolCallResponse,
} from '../types/mcpApp';

const api = httpClient;
const BASE_URL = '/mcp/apps';

export const mcpAppAPI = {
  /** List MCP Apps, optionally filtered by project */
  async list(
    projectId?: string,
    includeDisabled = false,
    options?: MCPAppRequestOptions
  ): Promise<MCPApp[]> {
    const params = new URLSearchParams();
    if (projectId) params.set('project_id', projectId);
    if (includeDisabled) params.set('include_disabled', 'true');

    const qs = params.toString();
    return await api.get<MCPApp[]>(`${BASE_URL}${qs ? `?${qs}` : ''}`, options);
  },

  /** Get MCP App details */
  async get(appId: string): Promise<MCPApp> {
    return await api.get<MCPApp>(`${BASE_URL}/${appId}`);
  },

  /** Get the resolved HTML resource for an MCP App */
  async getResource(appId: string): Promise<MCPAppResource> {
    return await api.get<MCPAppResource>(`${BASE_URL}/${appId}/resource`);
  },

  /** Proxy a tool call from an MCP App iframe to its MCP server */
  async proxyToolCall(
    appId: string,
    request: MCPAppToolCallRequest,
    options?: MCPAppRequestOptions
  ): Promise<MCPAppToolCallResponse> {
    return await api.post<MCPAppToolCallResponse>(
      `${BASE_URL}/${appId}/tool-call`,
      request,
      options
    );
  },

  /** Direct tool-call proxy without requiring a DB app record.
   *  Used for auto-discovered MCP Apps (synthetic app_id). */
  async proxyToolCallDirect(
    request: MCPAppDirectToolCallRequest,
    options?: MCPAppRequestOptions
  ): Promise<MCPAppToolCallResponse> {
    return await api.post<MCPAppToolCallResponse>(`${BASE_URL}/proxy/tool-call`, request, options);
  },

  /** Delete an MCP App */
  async delete(appId: string): Promise<void> {
    await api.delete(`${BASE_URL}/${appId}`);
  },

  /** Re-fetch the HTML resource for an MCP App */
  async refresh(appId: string): Promise<MCPApp> {
    return await api.post<MCPApp>(`${BASE_URL}/${appId}/refresh`);
  },

  /** Proxy a resources/read request (standard MCP protocol) */
  async readResource(
    uri: string,
    projectId: string,
    serverName?: string,
    options?: MCPAppRequestOptions
  ): Promise<{ contents: Array<{ uri: string; mimeType: string; text: string }> }> {
    return await api.post(
      `${BASE_URL}/resources/read`,
      {
        uri,
        project_id: projectId,
        server_name: serverName,
      },
      options
    );
  },

  /** Proxy a resources/list request (standard MCP protocol) */
  async listResources(
    projectId: string,
    serverName?: string,
    options?: MCPAppRequestOptions
  ): Promise<{
    resources: Array<{
      uri: string;
      name?: string | undefined;
      mimeType?: string | undefined;
      description?: string | undefined;
    }>;
  }> {
    return await api.post(
      `${BASE_URL}/resources/list`,
      {
        project_id: projectId,
        server_name: serverName,
      },
      options
    );
  },
};
