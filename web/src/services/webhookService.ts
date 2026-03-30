import { httpClient } from './client/httpClient';

export interface Webhook {
  id: string;
  tenant_id: string;
  name: string;
  url: string;
  secret: string | null;
  events: string[];
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface WebhookCreateRequest {
  name: string;
  url: string;
  events: string[];
  is_active?: boolean;
}

export interface WebhookUpdateRequest {
  name: string;
  url: string;
  events: string[];
  is_active: boolean;
}

export const webhookService = {
  async listWebhooks(tenantId: string): Promise<Webhook[]> {
    return httpClient.get<Webhook[]>(`/tenant-webhooks/${tenantId}`);
  },

  async createWebhook(tenantId: string, data: WebhookCreateRequest): Promise<Webhook> {
    return httpClient.post<Webhook>(`/tenant-webhooks/${tenantId}`, data);
  },

  async updateWebhook(webhookId: string, data: WebhookUpdateRequest): Promise<Webhook> {
    return httpClient.put<Webhook>(`/tenant-webhooks/${webhookId}`, data);
  },

  async deleteWebhook(webhookId: string): Promise<void> {
    await httpClient.delete(`/tenant-webhooks/${webhookId}`);
  },
};
