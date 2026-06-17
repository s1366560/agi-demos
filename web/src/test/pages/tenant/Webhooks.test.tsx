import { Route, Routes } from 'react-router-dom';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { WebhookCreatedSecretModal, Webhooks } from '../../../pages/tenant/Webhooks';
import { eventService } from '../../../services/eventService';
import { webhookService, type Webhook } from '../../../services/webhookService';
import { fireEvent, render, screen, waitFor } from '../../utils';

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
  const webhook: Webhook = {
    id: 'webhook-1',
    tenant_id: 'tenant-selected',
    name: 'Deploy',
    url: 'https://example.com/hook',
    secret: null,
    events: ['gene.installed'],
    is_active: true,
    created_at: '2026-06-17T00:00:00Z',
    updated_at: '2026-06-17T00:00:00Z',
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(eventService.getEventTypes).mockResolvedValue(['gene.installed']);
    vi.mocked(webhookService.listWebhooks).mockResolvedValue([]);
    vi.mocked(webhookService.createWebhook).mockResolvedValue({
      ...webhook,
      secret: 'whsec_created',
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
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

  it('shows a visible error when webhooks fail to load', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.mocked(webhookService.listWebhooks).mockRejectedValueOnce(new Error('webhooks down'));

    render(
      <Routes>
        <Route path="/tenant/:tenantId/webhooks" element={<Webhooks />} />
      </Routes>,
      { route: '/tenant/tenant-selected/webhooks' }
    );

    expect(await screen.findAllByText('Failed to fetch webhooks')).not.toHaveLength(0);
  });

  it('shows a warning when webhook event types fail to load', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.mocked(eventService.getEventTypes).mockRejectedValueOnce(new Error('types down'));

    render(
      <Routes>
        <Route path="/tenant/:tenantId/webhooks" element={<Webhooks />} />
      </Routes>,
      { route: '/tenant/tenant-selected/webhooks' }
    );

    expect(await screen.findByText('Failed to load webhook event types')).toBeInTheDocument();
  });

  it('renders the generated secret in a one-time modal', async () => {
    const onClose = vi.fn();
    const onCopy = vi.fn();

    render(<WebhookCreatedSecretModal secret="whsec_created" onClose={onClose} onCopy={onCopy} />);

    expect(
      await screen.findByRole('dialog', { name: 'Webhook signing secret' })
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue('whsec_created')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Copy secret' }));
    expect(onCopy).toHaveBeenCalledOnce();
  });

  it('does not render stored secrets in the edit dialog', async () => {
    vi.mocked(webhookService.listWebhooks).mockResolvedValue([
      {
        ...webhook,
        secret: 'whsec_should_not_render',
      },
    ]);

    render(
      <Routes>
        <Route path="/tenant/:tenantId/webhooks" element={<Webhooks />} />
      </Routes>,
      { route: '/tenant/tenant-selected/webhooks' }
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));

    expect(
      await screen.findByText('Signing secrets are shown only once when a webhook is created.')
    ).toBeInTheDocument();
    expect(screen.queryByDisplayValue('whsec_should_not_render')).not.toBeInTheDocument();
  });
});
