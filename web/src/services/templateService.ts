/**
 * Service for prompt template CRUD operations.
 */

import { apiFetch } from './client/urlUtils';

export interface TemplateVariable {
  name: string;
  description: string;
  default_value: string;
  required: boolean;
}

export interface PromptTemplateData {
  id: string;
  tenant_id: string;
  project_id?: string;
  created_by: string;
  title: string;
  content: string;
  category: string;
  variables: TemplateVariable[];
  is_system: boolean;
  usage_count: number;
  created_at: string;
  updated_at: string;
}

export interface CreateTemplateRequest {
  title: string;
  content: string;
  category?: string;
  project_id?: string;
  variables?: TemplateVariable[];
}

export interface UpdateTemplateRequest {
  title?: string;
  content?: string;
  category?: string;
  variables?: TemplateVariable[];
}

export const templateService = {
  async list(tenantId: string, category?: string): Promise<PromptTemplateData[]> {
    const params = new URLSearchParams({ tenant_id: tenantId });
    if (category) {
      params.set('category', category);
    }
    const res = await apiFetch.get(`/agent/templates?${params.toString()}`);
    return res.json();
  },

  async create(tenantId: string, data: CreateTemplateRequest): Promise<PromptTemplateData> {
    const params = new URLSearchParams({ tenant_id: tenantId });
    const res = await apiFetch.post(`/agent/templates?${params.toString()}`, data);
    return res.json();
  },

  async update(templateId: string, data: UpdateTemplateRequest): Promise<PromptTemplateData> {
    const res = await apiFetch.put(`/agent/templates/${templateId}`, data);
    return res.json();
  },

  async delete(templateId: string): Promise<void> {
    await apiFetch.delete(`/agent/templates/${templateId}`);
  },
};
