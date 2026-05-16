import { httpClient } from './client/httpClient';

const BASE_URL = '/instance-templates';

export interface TemplateItemCreate {
  template_id?: string;
  item_type?: 'gene' | 'genome';
  item_slug: string;
  display_order?: number;
}

export interface TemplateItemResponse {
  id: string;
  template_id: string;
  item_type: string;
  item_slug: string;
  display_order: number;
  created_at: string;
}

export interface InstanceTemplateCreate {
  name: string;
  slug: string;
  tenant_id?: string | null;
  description?: string | null;
  icon?: string | null;
  image_version?: string | null;
  default_config?: Record<string, unknown>;
  is_published?: boolean;
}

export interface InstanceTemplateUpdate {
  name?: string;
  slug?: string;
  description?: string | null;
  icon?: string | null;
  image_version?: string | null;
  default_config?: Record<string, unknown>;
  is_published?: boolean;
}

export interface InstanceTemplateResponse {
  id: string;
  name: string;
  slug: string;
  tenant_id: string | null;
  description: string | null;
  icon: string | null;
  image_version: string | null;
  default_config: Record<string, unknown>;
  is_published: boolean;
  is_featured: boolean;
  install_count: number;
  created_by: string | null;
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
    httpClient.get<InstanceTemplateListResponse>(`${BASE_URL}/`, { params }),

  create: (data: InstanceTemplateCreate) =>
    httpClient.post<InstanceTemplateResponse>(`${BASE_URL}/`, data),

  getById: (id: string) => httpClient.get<InstanceTemplateResponse>(`${BASE_URL}/${id}`),

  update: (id: string, data: InstanceTemplateUpdate) =>
    httpClient.put<InstanceTemplateResponse>(`${BASE_URL}/${id}`, data),

  delete: (id: string) => httpClient.delete(`${BASE_URL}/${id}`),

  publish: (id: string) => httpClient.post<InstanceTemplateResponse>(`${BASE_URL}/${id}/publish`),

  clone: (id: string, newName: string) =>
    httpClient.post<InstanceTemplateResponse>(`${BASE_URL}/${id}/clone`, { new_name: newName }),

  listItems: (id: string) => httpClient.get<TemplateItemResponse[]>(`${BASE_URL}/${id}/items`),

  addItem: (id: string, data: TemplateItemCreate) =>
    httpClient.post<TemplateItemResponse>(`${BASE_URL}/${id}/items`, {
      ...data,
      template_id: data.template_id ?? id,
      item_type: data.item_type ?? 'gene',
      display_order: data.display_order ?? 0,
    }),

  removeItem: (id: string, itemId: string) =>
    httpClient.delete(`${BASE_URL}/${id}/items/${itemId}`),
};
