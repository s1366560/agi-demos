import { httpClient } from './client/httpClient';

const BASE_URL = '/instance-templates';

export interface TemplateItemCreate {
  gene_id: string;
  config_override?: Record<string, unknown>;
  order?: number;
}

export interface TemplateItemResponse {
  id: string;
  template_id: string;
  gene_id: string;
  config_override: Record<string, unknown>;
  order: number;
  created_at: string;
}

export interface InstanceTemplateCreate {
  name: string;
  description?: string | null;
  base_config?: Record<string, unknown>;
  tags?: string[];
  is_published?: boolean;
}

export interface InstanceTemplateUpdate {
  name?: string;
  description?: string | null;
  base_config?: Record<string, unknown>;
  tags?: string[];
  is_published?: boolean;
}

export interface InstanceTemplateResponse {
  id: string;
  name: string;
  description: string | null;
  base_config: Record<string, unknown>;
  tags: string[];
  is_published: boolean;
  author_id: string | null;
  clone_count: number;
  created_at: string;
  updated_at: string | null;
}

export interface InstanceTemplateListResponse {
  templates: InstanceTemplateResponse[];
  total: number;
  page: number;
  page_size: number;
}

export const instanceTemplateService = {
  list: (params?: { page?: number; page_size?: number; is_published?: boolean }) =>
    httpClient.get<InstanceTemplateListResponse>(BASE_URL, { params }),

  create: (data: InstanceTemplateCreate) =>
    httpClient.post<InstanceTemplateResponse>(BASE_URL, data),

  getById: (id: string) => httpClient.get<InstanceTemplateResponse>(`${BASE_URL}/${id}`),

  update: (id: string, data: InstanceTemplateUpdate) =>
    httpClient.put<InstanceTemplateResponse>(`${BASE_URL}/${id}`, data),

  delete: (id: string) => httpClient.delete(`${BASE_URL}/${id}`),

  publish: (id: string) => httpClient.post<InstanceTemplateResponse>(`${BASE_URL}/${id}/publish`),

  clone: (id: string) => httpClient.post<InstanceTemplateResponse>(`${BASE_URL}/${id}/clone`),

  listItems: (id: string) => httpClient.get<TemplateItemResponse[]>(`${BASE_URL}/${id}/items`),

  addItem: (id: string, data: TemplateItemCreate) =>
    httpClient.post<TemplateItemResponse>(`${BASE_URL}/${id}/items`, data),

  removeItem: (id: string, itemId: string) =>
    httpClient.delete(`${BASE_URL}/${id}/items/${itemId}`),
};
