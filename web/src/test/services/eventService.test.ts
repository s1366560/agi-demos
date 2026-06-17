import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { eventService } from '../../services/eventService';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
  },
}));

describe('eventService', () => {
  const mockHttpClient = httpClient as unknown as {
    get: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists events with the selected tenant query parameter', async () => {
    mockHttpClient.get.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });

    await eventService.listEvents({
      tenant_id: 'tenant-selected',
      event_type: 'gene.installed',
      page: 2,
      page_size: 10,
    });

    expect(mockHttpClient.get).toHaveBeenCalledWith('/events', {
      params: {
        tenant_id: 'tenant-selected',
        event_type: 'gene.installed',
        page: 2,
        page_size: 10,
      },
    });
  });

  it('lists event types with the selected tenant query parameter', async () => {
    mockHttpClient.get.mockResolvedValue(['gene.installed']);

    await eventService.getEventTypes({ tenant_id: 'tenant-selected' });

    expect(mockHttpClient.get).toHaveBeenCalledWith('/events/types', {
      params: { tenant_id: 'tenant-selected' },
    });
  });
});
