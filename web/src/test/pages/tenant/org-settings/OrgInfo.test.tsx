import { beforeEach, describe, expect, it, vi } from 'vitest';

import { tenantAPI } from '@/services/api';
import { useTenantStore } from '@/stores/tenant';

import { OrgInfo } from '../../../../pages/tenant/org-settings/OrgInfo';
import { fireEvent, render, screen, waitFor } from '../../../utils';

vi.mock('@/stores/tenant');
vi.mock('@/services/api');

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

function mockTenantStore() {
  vi.mocked(useTenantStore).mockImplementation((selector: unknown) => {
    const state = {
      currentTenant: tenant,
      updateTenant,
      isLoading: false,
    };
    return typeof selector === 'function'
      ? (selector as (snapshot: typeof state) => unknown)(state)
      : state;
  });
}

describe('OrgInfo', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    updateTenant = vi.fn().mockResolvedValue(undefined);
    mockTenantStore();
    vi.mocked(tenantAPI.getStats).mockResolvedValue({
      storage: { used: 1024 * 1024, total: 1024 * 1024 * 10, percentage: 10 },
      projects: { active: 7, new_this_week: 0, list: [] },
      members: { total: 12, new_added: 0 },
      tenant_info: {
        organization_id: 'ORG-1',
        plan: 'basic',
        region: 'US-East',
        next_billing_date: '2026-02-01',
      },
    });
  });

  it('renders real organization statistics and no hardcoded stat values', async () => {
    render(<OrgInfo />);

    expect(await screen.findByText('7')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('1 MB')).toBeInTheDocument();
    expect(screen.queryByText('48')).not.toBeInTheDocument();
    expect(screen.queryByText('2.4 GB')).not.toBeInTheDocument();
  });

  it('disables logo upload when no upload API exists', async () => {
    render(<OrgInfo />);

    const uploadButton = screen.getByRole('button', { name: 'Upload Logo' });
    expect(uploadButton).toBeDisabled();
    expect(screen.getByText('Logo upload is not available in this build.')).toBeInTheDocument();
    expect(await screen.findByText('1 MB')).toBeInTheDocument();
  });

  it('saves organization name and description through the tenant store', async () => {
    render(<OrgInfo />);

    fireEvent.change(screen.getByDisplayValue('Test Tenant'), {
      target: { value: 'Renamed Tenant' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(updateTenant).toHaveBeenCalledWith('t1', {
        name: 'Renamed Tenant',
        description: 'Memory org',
      });
    });
    expect(await screen.findByText('1 MB')).toBeInTheDocument();
  });

  it('shows unavailable stats when the stats request fails', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.mocked(tenantAPI.getStats).mockRejectedValueOnce(new Error('stats failed'));

    render(<OrgInfo />);

    expect(await screen.findAllByText('Unavailable')).toHaveLength(4);
    consoleSpy.mockRestore();
  });
});
