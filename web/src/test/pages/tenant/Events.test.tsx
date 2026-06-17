import { Route, Routes } from 'react-router-dom';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Events } from '../../../pages/tenant/Events';
import { eventService } from '../../../services/eventService';
import { render, waitFor } from '../../utils';

vi.mock('../../../services/eventService', () => ({
  eventService: {
    getEventTypes: vi.fn(),
    listEvents: vi.fn(),
  },
}));

describe('Events', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(eventService.getEventTypes).mockResolvedValue(['gene.installed']);
    vi.mocked(eventService.listEvents).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    });
  });

  it('scopes event queries to the tenant route parameter', async () => {
    render(
      <Routes>
        <Route path="/tenant/:tenantId/events" element={<Events />} />
      </Routes>,
      { route: '/tenant/tenant-selected/events' }
    );

    await waitFor(() => {
      expect(eventService.getEventTypes).toHaveBeenCalledWith({
        tenant_id: 'tenant-selected',
      });
      expect(eventService.listEvents).toHaveBeenCalledWith({
        tenant_id: 'tenant-selected',
        page: 1,
        page_size: 20,
      });
    });
  });
});
