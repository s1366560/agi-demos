import { beforeEach, describe, expect, it, vi } from 'vitest';

import { tenantAPI } from '@/services/api';
import { useTenantStore } from '@/stores/tenant';

import { TenantSettings } from '../../../pages/tenant/TenantSettings';
import { fireEvent, render, screen, waitFor } from '../../utils';

vi.mock('@/stores/tenant');
vi.mock('@/services/api');
vi.mock('@/utils/confirmAction', () => ({
  confirmAction: vi.fn(() => Promise.resolve(true)),
}));

const tenant = {
  id: 't1',
  name: 'Test Tenant',
  description: 'Memory org',
  owner_id: 'owner-1',
  plan: 'basic',
  max_projects: 10,
  max_users: 25,
  max_storage: 100,
  created_at: '2026-01-01T00:00:00',
};

let updateTenant: ReturnType<typeof vi.fn>;
let deleteTenant: ReturnType<typeof vi.fn>;

function mockTenantStore() {
  vi.mocked(useTenantStore).mockImplementation((selector: unknown) => {
    const state = {
      currentTenant: tenant,
      updateTenant,
      deleteTenant,
      isLoading: false,
    };
    return typeof selector === 'function'
      ? (selector as (snapshot: typeof state) => unknown)(state)
      : state;
  });
}

describe('TenantSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    updateTenant = vi.fn().mockResolvedValue(undefined);
    deleteTenant = vi.fn().mockResolvedValue(undefined);
    mockTenantStore();
    vi.mocked(tenantAPI.getStats).mockResolvedValue({
      storage: { used: 450, total: 1000, percentage: 45 },
      projects: { active: 3, new_this_week: 0, list: [] },
      members: { total: 4, new_added: 0 },
      tenant_info: {
        organization_id: 'ORG-1',
        plan: 'basic',
        region: 'US-East',
        next_billing_date: '2026-02-01',
      },
    });
  });

  it('renders real usage from tenant stats and links plan changes to billing', async () => {
    render(<TenantSettings />);

    expect(await screen.findByText('3 / 10')).toBeInTheDocument();
    expect(screen.getByText('45%')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Change/ })).toHaveAttribute('href', '/tenant/billing');
  });

  it('saves general settings through the tenant store', async () => {
    render(<TenantSettings />);

    fireEvent.change(screen.getByDisplayValue('Test Tenant'), {
      target: { value: 'Renamed Tenant' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(updateTenant).toHaveBeenCalledWith('t1', {
        name: 'Renamed Tenant',
        description: 'Memory org',
      });
    });
    expect(
      await screen.findByText('Organization settings updated successfully.')
    ).toBeInTheDocument();
  });

  it('deletes the tenant only after confirmation', async () => {
    render(<TenantSettings />);

    fireEvent.click(screen.getByRole('button', { name: 'Delete Organization' }));

    await waitFor(() => {
      expect(deleteTenant).toHaveBeenCalledWith('t1');
    });
  });

  it('shows unavailable usage when stats cannot load', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.mocked(tenantAPI.getStats).mockRejectedValueOnce(new Error('stats failed'));

    render(<TenantSettings />);

    expect(await screen.findAllByText('Unavailable')).toHaveLength(2);
    consoleSpy.mockRestore();
  });
});
