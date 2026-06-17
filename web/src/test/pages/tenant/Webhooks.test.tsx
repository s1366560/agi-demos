import { Route, Routes } from 'react-router-dom';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Webhooks } from '../../../pages/tenant/Webhooks';
import { eventService } from '../../../services/eventService';
import { webhookService } from '../../../services/webhookService';
import { render, waitFor } from '../../utils';

vi.mock('../../../services/eventService', () => ({
  eventService: {
    getEventTypes: vi.fn(),
  },
}));

vi.mock('../../../services/webhookService', () => ({
  webhookService: {
    listWebhooks: vi.fn(),
    createWebhook: vi.fn(),
    updateWebhook: vi.fn(),
    deleteWebhook: vi.fn(),
  },
}));

vi.mock('../../../stores/tenant', () => ({
  useCurrentTenant: () => ({
    id: 'tenant-store',
    name: 'Store Tenant',
  }),
}));

describe('Webhooks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(eventService.getEventTypes).mockResolvedValue(['gene.installed']);
    vi.mocked(webhookService.listWebhooks).mockResolvedValue([]);
  });

  it('uses the tenant route parameter for webhooks and event types', async () => {
    render(
      <Routes>
        <Route path="/tenant/:tenantId/webhooks" element={<Webhooks />} />
      </Routes>,
      { route: '/tenant/tenant-selected/webhooks' }
    );

    await waitFor(() => {
      expect(webhookService.listWebhooks).toHaveBeenCalledWith('tenant-selected');
      expect(eventService.getEventTypes).toHaveBeenCalledWith({
        tenant_id: 'tenant-selected',
      });
    });
  });
});
