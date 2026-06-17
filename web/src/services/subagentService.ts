/**
 * SubAgent API Service
 *
 * Provides API methods for SubAgent management including CRUD operations,
 * template-based creation, and statistics retrieval.
 */

import { httpClient } from './client/httpClient';

import type {
  SubAgentResponse,
  SubAgentCreate,
  SubAgentUpdate,
  SubAgentsListResponse,
  SubAgentTemplatesResponse,
  SubAgentStatsResponse,
  SubAgentMatchResponse,
} from '../types/agent';

// Use centralized HTTP client
const api = httpClient;

interface TenantScopedOptions {
  tenant_id?: string | null | undefined;
}

const tenantParams = (options: TenantScopedOptions = {}): { tenant_id?: string } =>
  options.tenant_id ? { tenant_id: options.tenant_id } : {};

const tenantConfig = (options: TenantScopedOptions = {}) => {
  const params = tenantParams(options);
  return params.tenant_id ? { params } : undefined;
};

const requestConfig = (params: Record<string, string | boolean | undefined>) => {
  const cleanParams = Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined)
  );
  return Object.keys(cleanParams).length > 0 ? { params: cleanParams } : undefined;
};

export interface SubAgentListParams {
  enabled_only?: boolean | undefined;
  source?: 'filesystem' | 'database' | undefined;
  include_filesystem?: boolean | undefined;
  tenant_id?: string | null | undefined;
  search?: string | undefined;
  sort?: 'name' | 'invocations' | 'success_rate' | 'recent' | undefined;
  skip?: number | undefined;
  offset?: number | undefined;
  limit?: number | undefined;
}

export interface FilesystemSubAgent {
  name: string;
  display_name: string;
  description: string;
  model: string;
  tools: string[];
  file_path: string;
  source_type: string;
  enabled: boolean;
}

export interface FilesystemSubAgentListResponse {
  subagents: FilesystemSubAgent[];
  total: number;
  scanned_dirs: string[];
  errors: string[];
}

export const subagentAPI = {
  /**
   * List all SubAgents (merged: DB + filesystem by default)
   */
  list: async (params: SubAgentListParams = {}): Promise<SubAgentsListResponse> => {
    const { skip, offset, ...rest } = params;
    const queryParams = {
      ...rest,
      offset: offset ?? skip,
    };
    return await api.get<SubAgentsListResponse>('/subagents/', { params: queryParams });
  },

  /**
   * List filesystem-only SubAgents
   */
  listFilesystem: async (
    options: TenantScopedOptions = {}
  ): Promise<FilesystemSubAgentListResponse> => {
    return await api.get<FilesystemSubAgentListResponse>(
      '/subagents/filesystem',
      tenantConfig(options)
    );
  },

  /**
   * Import a filesystem SubAgent into the database for customization
   */
  importFilesystem: async (
    name: string,
    projectId?: string,
    options: TenantScopedOptions = {}
  ): Promise<SubAgentResponse> => {
    const params = {
      ...(projectId ? { project_id: projectId } : {}),
      ...tenantParams(options),
    };
    return await api.post<SubAgentResponse>(
      `/subagents/filesystem/${encodeURIComponent(name)}/import`,
      null,
      requestConfig(params)
    );
  },

  /**
   * Create a new SubAgent
   */
  create: async (
    data: SubAgentCreate,
    options: TenantScopedOptions = {}
  ): Promise<SubAgentResponse> => {
    return await api.post<SubAgentResponse>('/subagents/', data, tenantConfig(options));
  },

  /**
   * Get a SubAgent by ID
   */
  get: async (subagentId: string, options: TenantScopedOptions = {}): Promise<SubAgentResponse> => {
    return await api.get<SubAgentResponse>(`/subagents/${subagentId}`, tenantConfig(options));
  },

  /**
   * Update a SubAgent
   */
  update: async (
    subagentId: string,
    data: SubAgentUpdate,
    options: TenantScopedOptions = {}
  ): Promise<SubAgentResponse> => {
    return await api.put<SubAgentResponse>(`/subagents/${subagentId}`, data, tenantConfig(options));
  },

  /**
   * Delete a SubAgent
   */
  delete: async (subagentId: string, options: TenantScopedOptions = {}): Promise<void> => {
    await api.delete(`/subagents/${subagentId}`, tenantConfig(options));
  },

  /**
   * Enable or disable a SubAgent
   */
  toggle: async (
    subagentId: string,
    enabled: boolean,
    options: TenantScopedOptions = {}
  ): Promise<SubAgentResponse> => {
    return await api.patch<SubAgentResponse>(`/subagents/${subagentId}/enable`, null, {
      params: { enabled, ...tenantParams(options) },
    });
  },

  /**
   * Get SubAgent statistics
   */
  getStats: async (
    subagentId: string,
    options: TenantScopedOptions = {}
  ): Promise<SubAgentStatsResponse> => {
    return await api.get<SubAgentStatsResponse>(
      `/subagents/${subagentId}/stats`,
      tenantConfig(options)
    );
  },

  /**
   * List available SubAgent templates
   */
  listTemplates: async (options: TenantScopedOptions = {}): Promise<SubAgentTemplatesResponse> => {
    return await api.get<SubAgentTemplatesResponse>(
      '/subagents/templates/list',
      tenantConfig(options)
    );
  },

  /**
   * Create a SubAgent from a template
   */
  createFromTemplate: async (
    templateId: string,
    options: TenantScopedOptions = {}
  ): Promise<SubAgentResponse> => {
    const config = tenantConfig(options);
    const path = `/subagents/templates/${templateId}/install`;
    return config
      ? await api.post<SubAgentResponse>(path, undefined, config)
      : await api.post<SubAgentResponse>(path);
  },

  /**
   * Match a query to find the best SubAgent
   */
  match: async (
    taskDescription: string,
    options: TenantScopedOptions = {}
  ): Promise<SubAgentMatchResponse> => {
    return await api.post<SubAgentMatchResponse>(
      '/subagents/match',
      {
        task_description: taskDescription,
      },
      tenantConfig(options)
    );
  },

  /**
   * Cancel a running background SubAgent execution.
   * Sets a Redis cancel signal that the BackgroundExecutor will pick up.
   */
  cancelExecution: async (
    executionId: string,
    conversationId?: string,
    reason?: string
  ): Promise<{ execution_id: string; cancelled: boolean; message: string }> => {
    return await api.post(`/agent/subagent/${executionId}/cancel`, {
      conversation_id: conversationId,
      reason: reason,
    });
  },
};

export default subagentAPI;
