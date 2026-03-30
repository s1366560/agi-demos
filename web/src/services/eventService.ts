import { httpClient } from './client/httpClient';

export interface EventLog {
  id: string;
  tenant_id: string;
  event_type: string;
  message: string;
  source: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface EventLogListResponse {
  items: EventLog[];
  total: number;
  page: number;
  page_size: number;
}

export const eventService = {
  async listEvents(params: {
    event_type?: string;
    date_from?: string;
    date_to?: string;
    page?: number;
    page_size?: number;
  }): Promise<EventLogListResponse> {
    return httpClient.get<EventLogListResponse>('/events', { params });
  },
  async getEventTypes(): Promise<string[]> {
    return httpClient.get<string[]>('/events/types');
  },
};
