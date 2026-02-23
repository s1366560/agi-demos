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

export interface SubAgentListParams {
  enabled_only?: boolean;
  source?: 'filesystem' | 'database';
  include_filesystem?: boolean;
  skip?: number;
  limit?: number;
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
    return await api.get<SubAgentsListResponse>('/subagents/', { params });
  },

  /**
   * List filesystem-only SubAgents
   */
  listFilesystem: async (): Promise<FilesystemSubAgentListResponse> => {
    return await api.get<FilesystemSubAgentListResponse>('/subagents/filesystem');
  },

  /**
   * Import a filesystem SubAgent into the database for customization
   */
  importFilesystem: async (name: string, projectId?: string): Promise<SubAgentResponse> => {
    return await api.post<SubAgentResponse>(
      `/subagents/filesystem/${encodeURIComponent(name)}/import`,
      null,
      { params: projectId ? { project_id: projectId } : undefined }
    );
  },

  /**
   * Create a new SubAgent
   */
  create: async (data: SubAgentCreate): Promise<SubAgentResponse> => {
    return await api.post<SubAgentResponse>('/subagents/', data);
  },

  /**
   * Get a SubAgent by ID
   */
  get: async (subagentId: string): Promise<SubAgentResponse> => {
    return await api.get<SubAgentResponse>(`/subagents/${subagentId}`);
  },

  /**
   * Update a SubAgent
   */
  update: async (subagentId: string, data: SubAgentUpdate): Promise<SubAgentResponse> => {
    return await api.put<SubAgentResponse>(`/subagents/${subagentId}`, data);
  },

  /**
   * Delete a SubAgent
   */
  delete: async (subagentId: string): Promise<void> => {
    await api.delete(`/subagents/${subagentId}`);
  },

  /**
   * Enable or disable a SubAgent
   */
  toggle: async (subagentId: string, enabled: boolean): Promise<SubAgentResponse> => {
    return await api.patch<SubAgentResponse>(`/subagents/${subagentId}/enable`, null, {
      params: { enabled },
    });
  },

  /**
   * Get SubAgent statistics
   */
  getStats: async (subagentId: string): Promise<SubAgentStatsResponse> => {
    return await api.get<SubAgentStatsResponse>(`/subagents/${subagentId}/stats`);
  },

  /**
   * List available SubAgent templates
   */
  listTemplates: async (): Promise<SubAgentTemplatesResponse> => {
    return await api.get<SubAgentTemplatesResponse>('/subagents/templates/list');
  },

  /**
   * Create a SubAgent from a template
   */
  createFromTemplate: async (templateName: string): Promise<SubAgentResponse> => {
    return await api.post<SubAgentResponse>(`/subagents/templates/${templateName}`);
  },

  /**
   * Match a query to find the best SubAgent
   */
  match: async (taskDescription: string): Promise<SubAgentMatchResponse> => {
    return await api.post<SubAgentMatchResponse>('/subagents/match', {
      task_description: taskDescription,
    });
  },
};

export default subagentAPI;
