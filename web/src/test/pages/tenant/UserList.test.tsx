import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Route, Routes } from 'react-router-dom';

import { invitationService } from '@/services/invitationService';
import { useTenantStore } from '@/stores/tenant';

import { UserList } from '../../../pages/tenant/UserList';
import { fireEvent, render, screen, waitFor } from '../../utils';

vi.mock('@/stores/tenant');
vi.mock('@/services/invitationService');
vi.mock('@/utils/confirmAction', () => ({
  confirmAction: vi.fn(() => Promise.resolve(true)),
}));

const tenant = {
  id: 't1',
  name: 'Test Tenant',
  owner_id: 'owner-1',
  plan: 'basic',
  max_projects: 10,
  max_users: 25,
  max_storage: 100,
  created_at: '2026-01-01T00:00:00',
};

let currentTenant = tenant;

const member = {
  id: 'ut1',
  user_id: 'u-1',
  tenant_id: 't1',
  email: 'ada@example.com',
  name: 'Ada Lovelace',
  role: 'admin',
  permissions: {},
  created_at: '2026-01-02T00:00:00',
};

let listMembers: ReturnType<typeof vi.fn>;
let removeMember: ReturnType<typeof vi.fn>;

function mockTenantStore() {
  vi.mocked(useTenantStore).mockImplementation((selector: unknown) => {
    const state = {
      currentTenant,
      listMembers,
      removeMember,
      isLoading: false,
    };
    return typeof selector === 'function'
      ? (selector as (snapshot: typeof state) => unknown)(state)
      : state;
  });
}

function renderUserList(route = '/tenant/t1/users') {
  return render(
    <Routes>
      <Route path="/tenant/:tenantId/users" element={<UserList />} />
      <Route path="/tenant/users" element={<UserList />} />
    </Routes>,
    { route }
  );
}

describe('UserList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentTenant = tenant;
    listMembers = vi.fn().mockResolvedValue({ members: [member], total: 1 });
    removeMember = vi.fn().mockResolvedValue(undefined);
    mockTenantStore();
    vi.mocked(invitationService.listPending).mockResolvedValue({
      items: [],
      total: 2,
      limit: 50,
      offset: 0,
    });
    vi.mocked(invitationService.create).mockResolvedValue({
      id: 'inv-1',
      tenant_id: 't1',
      email: 'new@example.com',
      role: 'admin',
      status: 'pending',
      invited_by: 'owner-1',
      expires_at: '2026-01-09T00:00:00',
      created_at: '2026-01-02T00:00:00',
    });
  });

  it('renders backend member identity and no fake active status', async () => {
    renderUserList();

    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText('ada@example.com')).toBeInTheDocument();
    expect(screen.getByText('Admin Access')).toBeInTheDocument();
    expect(screen.getByText('Awaiting acceptance')).toBeInTheDocument();
    expect(screen.queryByText('Active')).not.toBeInTheDocument();
  });

  it('sends invitations through the invitation service', async () => {
    renderUserList();

    fireEvent.click(screen.getByRole('button', { name: 'Invite Member' }));
    fireEvent.change(screen.getByLabelText('Email Address'), {
      target: { value: 'new@example.com' },
    });
    fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'admin' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send Invitation' }));

    await waitFor(() => {
      expect(invitationService.create).toHaveBeenCalledWith('t1', {
        email: 'new@example.com',
        role: 'admin',
      });
    });
    expect(await screen.findByText('Invitation sent')).toBeInTheDocument();
  });

  it('removes members from the row action menu', async () => {
    renderUserList();

    fireEvent.click(await screen.findByRole('button', { name: 'Open actions for Ada Lovelace' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove User' }));

    await waitFor(() => {
      expect(removeMember).toHaveBeenCalledWith('t1', 'u-1');
    });
  });

  it('uses real client-side pagination controls', async () => {
    listMembers.mockResolvedValue({
      members: Array.from({ length: 11 }, (_, index) => ({
        ...member,
        id: `ut-${String(index + 1)}`,
        user_id: `u-${String(index + 1)}`,
        email: `user${String(index + 1)}@example.com`,
        name: `User ${String(index + 1)}`,
      })),
      total: 11,
    });

    renderUserList();

    expect(await screen.findByText('User 1')).toBeInTheDocument();
    expect(screen.queryByText('User 11')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    expect(await screen.findByText('User 11')).toBeInTheDocument();
    expect(screen.queryByText('User 1')).not.toBeInTheDocument();
  });

  it('uses the route tenant when the tenant store has stale state', async () => {
    currentTenant = { ...tenant, id: 'store-tenant', max_users: 50 };

    renderUserList('/tenant/route-tenant/users');

    await waitFor(() => {
      expect(listMembers).toHaveBeenCalledWith('route-tenant');
      expect(invitationService.listPending).toHaveBeenCalledWith('route-tenant');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Invite Member' }));
    fireEvent.change(screen.getByLabelText('Email Address'), {
      target: { value: 'route@example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send Invitation' }));

    await waitFor(() => {
      expect(invitationService.create).toHaveBeenCalledWith('route-tenant', {
        email: 'route@example.com',
        role: 'member',
      });
    });
  });
});
