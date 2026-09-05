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
  project_id?: string | undefined;
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
  category?: string | undefined;
  project_id?: string | undefined;
  variables?: TemplateVariable[] | undefined;
}

export interface UpdateTemplateRequest {
  title?: string | undefined;
  content?: string | undefined;
  category?: string | undefined;
  variables?: TemplateVariable[] | undefined;
}

export const templateService = {
  async list(tenantId: string, category?: string): Promise<PromptTemplateData[]> {
    const params = new URLSearchParams({ tenant_id: tenantId });
    if (category) {
      params.set('category', category);
    }
    return apiFetch.get(`/agent/templates?${params.toString()}`, async (res) => {
      return (await res.json()) as PromptTemplateData[];
    });
  },

  async create(tenantId: string, data: CreateTemplateRequest): Promise<PromptTemplateData> {
    const params = new URLSearchParams({ tenant_id: tenantId });
    return apiFetch.post(`/agent/templates?${params.toString()}`, data, async (res) => {
      return (await res.json()) as PromptTemplateData;
    });
  },

  async update(templateId: string, data: UpdateTemplateRequest): Promise<PromptTemplateData> {
    return apiFetch.put(`/agent/templates/${templateId}`, data, async (res) => {
      return (await res.json()) as PromptTemplateData;
    });
  },

  async delete(templateId: string): Promise<void> {
    await apiFetch.delete(`/agent/templates/${templateId}`, () => undefined);
  },
};
