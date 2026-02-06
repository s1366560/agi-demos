import { BrowserRouter } from 'react-router-dom';

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SpaceListPage } from '../../pages/SpaceListPage';
import { useTenantStore } from '../../stores/tenant';

// Mock AppLayout
vi.mock('../../components/AppLayout', () => ({
  AppLayout: ({ children, title }: any) => (
    <div data-testid="app-layout">
      <h1>{title}</h1>
      {children}
    </div>
  ),
}));

// Mock TenantCreateModal
vi.mock('../../components/tenant/TenantCreateModal', () => ({
  TenantCreateModal: ({ isOpen, onClose }: any) =>
    isOpen ? (
      <div data-testid="create-modal">
        <button onClick={onClose}>Close</button>
      </div>
    ) : null,
}));

// Mock store
vi.mock('../../stores/tenant', () => ({
  useTenantStore: vi.fn(),
}));

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe('SpaceListPage', () => {
  const mockListTenants = vi.fn();
  const mockSetCurrentTenant = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    (useTenantStore as any).mockReturnValue({
      tenants: [],
      listTenants: mockListTenants,
      setCurrentTenant: mockSetCurrentTenant,
    });
  });

  it('should render empty state when no tenants', () => {
    render(
      <BrowserRouter>
        <SpaceListPage />
      </BrowserRouter>
    );

    // "My Spaces" appears in both title and welcome text
    expect(screen.getAllByText('My Spaces').length).toBeGreaterThan(0);
    expect(screen.getByText('Create First Space')).toBeInTheDocument();
  });

  it('should render tenant list', () => {
    const mockTenants = [
      { id: '1', name: 'Tenant 1', plan: 'free', max_projects: 3, max_users: 10 },
      { id: '2', name: 'Tenant 2', plan: 'pro', max_projects: 10, max_users: 50 },
    ];

    (useTenantStore as any).mockReturnValue({
      tenants: mockTenants,
      listTenants: mockListTenants,
      setCurrentTenant: mockSetCurrentTenant,
    });

    render(
      <BrowserRouter>
        <SpaceListPage />
      </BrowserRouter>
    );

    expect(screen.getByText('Tenant 1')).toBeInTheDocument();
    expect(screen.getByText('Tenant 2')).toBeInTheDocument();
  });

  it('should navigate to space dashboard on click', () => {
    const mockTenant = { id: '1', name: 'Tenant 1', plan: 'free' };
    (useTenantStore as any).mockReturnValue({
      tenants: [mockTenant],
      listTenants: mockListTenants,
      setCurrentTenant: mockSetCurrentTenant,
    });

    render(
      <BrowserRouter>
        <SpaceListPage />
      </BrowserRouter>
    );

    fireEvent.click(screen.getByText('Tenant 1'));
    expect(mockSetCurrentTenant).toHaveBeenCalledWith(mockTenant);
    expect(mockNavigate).toHaveBeenCalledWith('/space/1');
  });

  it('should open create modal', () => {
    render(
      <BrowserRouter>
        <SpaceListPage />
      </BrowserRouter>
    );

    fireEvent.click(screen.getByText('Create New Space'));
    expect(screen.getByTestId('create-modal')).toBeInTheDocument();
  });
});
