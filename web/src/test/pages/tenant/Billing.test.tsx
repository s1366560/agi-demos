import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Billing } from '../../../pages/tenant/Billing';
import { billingService } from '../../../services/billingService';
import { useTenantStore } from '../../../stores/tenant';
import { fireEvent, render, screen, waitFor } from '../../utils';

const confirmActionMock = vi.hoisted(() => vi.fn());

vi.mock('../../../stores/tenant');
vi.mock('../../../services/billingService');
vi.mock('../../../utils/confirmAction', () => ({
  confirmAction: confirmActionMock,
}));

const tenant = {
  id: 't1',
  name: 'Test Tenant',
  description: 'Memory org',
  owner_id: 'owner-1',
  plan: 'free',
  max_projects: 10,
  max_users: 25,
  max_storage: 10 * 1024 * 1024 * 1024,
  created_at: '2026-01-01T00:00:00',
};

const billingInfo = {
  tenant: {
    id: 't1',
    name: 'Test Tenant',
    plan: 'free',
    storage_limit: 10 * 1024 * 1024 * 1024,
  },
  usage: {
    projects: 2,
    memories: 4,
    users: 3,
    storage: 1024 * 1024 * 1024,
  },
  invoices: [],
};

describe('Billing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    confirmActionMock.mockResolvedValue(true);
    vi.mocked(useTenantStore).mockReturnValue({
      currentTenant: tenant,
    } as any);
    vi.mocked(billingService.getBillingInfo).mockResolvedValue(billingInfo);
    vi.mocked(billingService.upgradePlan).mockResolvedValue({
      message: 'Plan upgraded successfully',
      tenant: {
        id: 't1',
        name: 'Test Tenant',
        plan: 'pro',
        storage_limit: 100 * 1024 * 1024 * 1024,
      },
    });
  });

  it('upgrades to the next plan through the billing service', async () => {
    render(<Billing />);

    fireEvent.click(await screen.findByRole('button', { name: 'Upgrade to Pro' }));

    await waitFor(() => {
      expect(billingService.upgradePlan).toHaveBeenCalledWith('t1', 'pro');
    });
    expect(await screen.findByText('Plan upgraded successfully')).toBeInTheDocument();
  });

  it('upgrades to enterprise from the enterprise card', async () => {
    render(<Billing />);

    fireEvent.click(await screen.findByRole('button', { name: 'Upgrade to Enterprise' }));

    await waitFor(() => {
      expect(billingService.upgradePlan).toHaveBeenCalledWith('t1', 'enterprise');
    });
  });

  it('does not expose an unavailable sales contact action', async () => {
    render(<Billing />);

    await screen.findByRole('button', { name: 'Upgrade to Pro' });

    expect(screen.queryByRole('button', { name: 'Contact Sales' })).not.toBeInTheDocument();
    expect(
      screen.queryByText('Sales contact is not configured in this build.')
    ).not.toBeInTheDocument();
    expect(billingService.upgradePlan).not.toHaveBeenCalled();
  });
});
