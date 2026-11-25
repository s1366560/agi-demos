import { useParams } from 'react-router-dom';
import type { EventLogListParams, EventLogListResponse } from '../web/services/eventService';
import type {
  Webhook,
  WebhookCreateRequest,
  WebhookUpdateRequest,
} from '../web/services/webhookService';
import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';

export function useCurrentTenant() {
  const { tenantId } = useParams();
  return tenantId ? { id: tenantId } : null;
}

export const eventService = {
  async listEvents({ tenant_id: _tenant, ...filters }: EventLogListParams) {
    return window.memstack.invoke('read-events', filters) as Promise<EventLogListResponse>;
  },
  async getEventTypes() {
    const result = (await window.memstack.invoke('event-types', {})) as { items: string[] };
    return result.items;
  },
};

export const webhookService = {
  async listWebhooks() {
    const result = (await window.memstack.invoke('list-webhooks', {})) as { items: Webhook[] };
    return result.items;
  },
  createWebhook(_tenant: string, data: WebhookCreateRequest) {
    return window.memstack.invoke('create-webhook', { data }) as Promise<Webhook>;
  },
  updateWebhook(id: string, data: WebhookUpdateRequest) {
    return window.memstack.invoke('update-webhook', { id, data }) as Promise<Webhook>;
  },
  deleteWebhook(id: string) {
    return window.memstack.invoke('delete-webhook', { id });
  },
};
