/**
 * SubAgent template marketplace API service.
 * Communicates with /api/v1/subagents/templates/ endpoints.
 */

import { apiFetch } from './client/urlUtils';

export interface SubAgentTemplateListItem {
  id: string;
  tenant_id: string;
  name: string;
  version: string;
  display_name: string;
  description: string;
  category: string;
  tags: string[];
  author: string;
  is_builtin: boolean;
  is_published: boolean;
  install_count: number;
  rating: number;
  created_at: string;
  updated_at: string | null;
}

export interface SubAgentTemplateDetail extends SubAgentTemplateListItem {
  system_prompt: string;
  trigger_description: string;
  trigger_keywords: string[];
  trigger_examples: string[];
  model: string;
  max_tokens: number;
  temperature: number;
  max_iterations: number;
  allowed_tools: string[];
  metadata: Record<string, unknown> | null;
}

export interface SubAgentTemplateCreateRequest {
  name: string;
  display_name?: string;
  description?: string;
  category?: string;
  tags?: string[];
  system_prompt: string;
  trigger_description?: string;
  trigger_keywords?: string[];
  trigger_examples?: string[];
  model?: string;
  max_tokens?: number;
  temperature?: number;
  max_iterations?: number;
  allowed_tools?: string[];
  author?: string;
  is_published?: boolean;
  metadata?: Record<string, unknown>;
}

export interface SubAgentTemplateUpdateRequest {
  display_name?: string;
  description?: string;
  category?: string;
  tags?: string[];
  system_prompt?: string;
  trigger_description?: string;
  trigger_keywords?: string[];
  trigger_examples?: string[];
  model?: string;
  max_tokens?: number;
  temperature?: number;
  max_iterations?: number;
  allowed_tools?: string[];
  is_published?: boolean;
  metadata?: Record<string, unknown>;
}

export interface SubAgentTemplateListResponse {
  templates: SubAgentTemplateListItem[];
  total: number;
  page: number;
  page_size: number;
}

export const subagentTemplateService = {
  list: async (params?: {
    category?: string;
    search?: string;
    page?: number;
    page_size?: number;
  }): Promise<SubAgentTemplateListResponse> => {
    const query = new URLSearchParams();
    if (params?.category) query.set('category', params.category);
    if (params?.search) query.set('search', params.search);
    if (params?.page) query.set('page', String(params.page));
    if (params?.page_size) query.set('page_size', String(params.page_size));

    const qs = query.toString();
    const url = `/subagents/templates/list${qs ? `?${qs}` : ''}`;
    const response = await apiFetch.get(url);
    return response.json();
  },

  getCategories: async (): Promise<string[]> => {
    const response = await apiFetch.get('/subagents/templates/categories');
    const data = await response.json();
    return data.categories || [];
  },

  get: async (templateId: string): Promise<SubAgentTemplateDetail> => {
    const response = await apiFetch.get(`/subagents/templates/${templateId}`);
    return response.json();
  },

  create: async (data: SubAgentTemplateCreateRequest): Promise<SubAgentTemplateDetail> => {
    const response = await apiFetch.post('/subagents/templates/', data);
    return response.json();
  },

  update: async (
    templateId: string,
    data: SubAgentTemplateUpdateRequest
  ): Promise<SubAgentTemplateDetail> => {
    const response = await apiFetch.put(`/subagents/templates/${templateId}`, data);
    return response.json();
  },

  delete: async (templateId: string): Promise<void> => {
    await apiFetch.delete(`/subagents/templates/${templateId}`);
  },

  install: async (
    templateId: string,
    projectId: string
  ): Promise<{ subagent_id: string; name: string }> => {
    const response = await apiFetch.post(`/subagents/templates/${templateId}/install`, {
      project_id: projectId,
    });
    return response.json();
  },

  exportFromSubAgent: async (subagentId: string): Promise<SubAgentTemplateDetail> => {
    const response = await apiFetch.post(`/subagents/templates/from-subagent/${subagentId}`);
    return response.json();
  },

  seed: async (): Promise<{ seeded: number }> => {
    const response = await apiFetch.post('/subagents/templates/seed');
    return response.json();
  },
};
