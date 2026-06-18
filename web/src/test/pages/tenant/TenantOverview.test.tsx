import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Route, Routes } from 'react-router-dom';

import { TenantOverview } from '../../../pages/tenant/TenantOverview';
import { tenantAPI } from '../../../services/api';
import { useTenantStore } from '../../../stores/tenant';
import { screen, render, waitFor } from '../../utils';

vi.mock('../../../stores/tenant');
vi.mock('../../../services/api');

describe('TenantOverview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders tenant information', async () => {
    vi.mocked(useTenantStore).mockReturnValue({
      currentTenant: {
        id: 't1',
        name: 'Test Corp',
        description: 'A test tenant',
        plan: 'basic',
        created_at: '2023-01-01',
      },
      tenants: [{ id: 't1' }],
      listTenants: vi.fn(),
      setCurrentTenant: vi.fn(),
    } as any);

    vi.mocked(tenantAPI.getStats).mockResolvedValue({
      storage: { used: 100, total: 1000, percentage: 10 },
      projects: { active: 5, new_this_week: 1, list: [] },
      members: { total: 10, new_added: 2 },
      memory_history: [
        {
          date: '2026-05-14',
          used: 100,
          daily_added: 100,
          memory_count: 1,
          percentage: 10,
        },
        {
          date: '2026-05-15',
          used: 200,
          daily_added: 100,
          memory_count: 1,
          percentage: 20,
        },
      ],
      tenant_info: {
        organization_id: 'ORG-123',
        plan: 'basic',
        region: 'US-East',
        next_billing_date: '2023-02-01',
      },
    });

    render(<TenantOverview />);

    await waitFor(() => {
      expect(screen.getByText('Overview')).toBeInTheDocument();
      expect(screen.getByText('ORG-123')).toBeInTheDocument();
      expect(screen.getByText('basic')).toBeInTheDocument();
      expect(
        screen.getByRole('img', { name: 'Tenant memory usage history chart' })
      ).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'View All' })).toHaveAttribute(
        'href',
        '/tenant/t1/projects'
      );
      expect(screen.getByRole('link', { name: 'View Invoice' })).toHaveAttribute(
        'href',
        '/tenant/t1/billing'
      );
    });
  });

  it('uses the route tenant while the current tenant store value is stale', async () => {
    const setCurrentTenant = vi.fn();
    vi.mocked(useTenantStore).mockReturnValue({
      currentTenant: {
        id: 'old-tenant',
        name: 'Old Tenant',
        description: 'Old tenant',
        plan: 'basic',
        created_at: '2023-01-01',
      },
      tenants: [
        { id: 'old-tenant', name: 'Old Tenant' },
        { id: 'route-tenant', name: 'Route Tenant' },
      ],
      listTenants: vi.fn(),
      setCurrentTenant,
    } as any);

    vi.mocked(tenantAPI.getStats).mockResolvedValue({
      storage: { used: 100, total: 1000, percentage: 10 },
      projects: { active: 0, new_this_week: 0, list: [] },
      members: { total: 0, new_added: 0 },
      memory_history: [],
      tenant_info: {
        organization_id: 'ORG-ROUTE',
        plan: 'basic',
        region: 'US-East',
        next_billing_date: '2023-02-01',
      },
    });

    render(
      <Routes>
        <Route path="/tenant/:tenantId/overview" element={<TenantOverview />} />
      </Routes>,
      { route: '/tenant/route-tenant/overview' }
    );

    await waitFor(() => {
      expect(tenantAPI.getStats).toHaveBeenCalledWith('route-tenant');
    });
    expect(tenantAPI.getStats).not.toHaveBeenCalledWith('old-tenant');
    expect(setCurrentTenant).toHaveBeenCalledWith({ id: 'route-tenant', name: 'Route Tenant' });
    expect(screen.getByRole('link', { name: 'View All' })).toHaveAttribute(
      'href',
      '/tenant/route-tenant/projects'
    );
    expect(screen.getByRole('link', { name: 'View Invoice' })).toHaveAttribute(
      'href',
      '/tenant/route-tenant/billing'
    );
  });

  it('shows unavailable labels instead of backend placeholder gaps', async () => {
    vi.mocked(useTenantStore).mockReturnValue({
      currentTenant: {
        id: 't1',
        name: 'Test Corp',
        description: 'A test tenant',
        plan: 'basic',
        created_at: '2023-01-01',
      },
      tenants: [{ id: 't1' }],
      listTenants: vi.fn(),
      setCurrentTenant: vi.fn(),
    } as any);

    vi.mocked(tenantAPI.getStats).mockResolvedValue({
      storage: { used: 100, total: 1000, percentage: 10 },
      projects: {
        active: 1,
        new_this_week: 0,
        list: [
          {
            id: 'project-1',
            name: 'Project One',
            owner: 'Owner',
            memory_consumed: '12.0 KB',
            status: null,
          },
        ],
      },
      members: { total: 2, new_added: 0 },
      memory_history: [],
      tenant_info: {
        organization_id: 'ORG-123',
        plan: 'basic',
        region: null,
        next_billing_date: null,
      },
    });

    render(<TenantOverview />);

    await waitFor(() => {
      expect(screen.getAllByText('Unavailable')).toHaveLength(3);
      expect(screen.getByText('12.0 KB')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Open project Project One' })).toHaveAttribute(
        'href',
        '/tenant/t1/project/project-1'
      );
    });
  });

  it('renders loading state when no tenant', () => {
    vi.mocked(useTenantStore).mockReturnValue({
      currentTenant: null,
      tenants: [],
      listTenants: vi.fn(),
    } as any);

    render(<TenantOverview />);

    expect(screen.getByText('Loading tenant information...')).toBeInTheDocument();
  });
});
