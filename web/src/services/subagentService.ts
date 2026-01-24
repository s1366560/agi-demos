/**
 * SubAgent API Service
 *
 * Provides API methods for SubAgent management including CRUD operations,
 * template-based creation, and statistics retrieval.
 */

import axios from 'axios';
import type {
  SubAgentResponse,
  SubAgentCreate,
  SubAgentUpdate,
  SubAgentsListResponse,
  SubAgentTemplatesResponse,
  SubAgentStatsResponse,
  SubAgentMatchResponse,
} from '../types/agent';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
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
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export interface SubAgentListParams {
  enabled_only?: boolean;
  skip?: number;
  limit?: number;
}

export const subagentAPI = {
  /**
   * List all SubAgents
   */
  list: async (params: SubAgentListParams = {}): Promise<SubAgentsListResponse> => {
    const response = await api.get('/subagents/', { params });
    return response.data;
  },

  /**
   * Create a new SubAgent
   */
  create: async (data: SubAgentCreate): Promise<SubAgentResponse> => {
    const response = await api.post('/subagents/', data);
    return response.data;
  },

  /**
   * Get a SubAgent by ID
   */
  get: async (subagentId: string): Promise<SubAgentResponse> => {
    const response = await api.get(`/subagents/${subagentId}`);
    return response.data;
  },

  /**
   * Update a SubAgent
   */
  update: async (subagentId: string, data: SubAgentUpdate): Promise<SubAgentResponse> => {
    const response = await api.put(`/subagents/${subagentId}`, data);
    return response.data;
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
    const response = await api.patch(`/subagents/${subagentId}/enable`, null, {
      params: { enabled },
    });
    return response.data;
  },

  /**
   * Get SubAgent statistics
   */
  getStats: async (subagentId: string): Promise<SubAgentStatsResponse> => {
    const response = await api.get(`/subagents/${subagentId}/stats`);
    return response.data;
  },

  /**
   * List available SubAgent templates
   */
  listTemplates: async (): Promise<SubAgentTemplatesResponse> => {
    const response = await api.get('/subagents/templates/list');
    return response.data;
  },

  /**
   * Create a SubAgent from a template
   */
  createFromTemplate: async (templateName: string): Promise<SubAgentResponse> => {
    const response = await api.post(`/subagents/templates/${templateName}`);
    return response.data;
  },

  /**
   * Match a query to find the best SubAgent
   */
  match: async (taskDescription: string): Promise<SubAgentMatchResponse> => {
    const response = await api.post('/subagents/match', {
      task_description: taskDescription,
    });
    return response.data;
  },
};

export default subagentAPI;
