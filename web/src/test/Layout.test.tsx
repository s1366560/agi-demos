import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { TenantLayout } from '@/layouts/TenantLayout';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'tenant.welcome': 'Welcome',
        'tenant.noTenantDescription': 'Create a workspace to get started',
        'tenant.create': 'Create Workspace',
        'common.logout': 'Logout',
        'common.search': 'Search',
      };
      return translations[key] || key;
    },
    i18n: {
      language: 'en-US',
      changeLanguage: vi.fn(),
    },
  }),
}));

vi.mock('@/stores/tenant', () => {
  const state = {
    tenants: [{ id: 't1', name: 'Test Tenant' }],
    currentTenant: { id: 't1', name: 'Test Tenant' },
    setCurrentTenant: vi.fn(),
    getTenant: vi.fn().mockResolvedValue(undefined),
    listTenants: vi.fn().mockResolvedValue(undefined),
    createTenant: vi.fn().mockResolvedValue(undefined),
  };
  const hook = ((selector?: any) => (selector ? selector(state) : state)) as any;
  hook.getState = () => state;
  hook.setState = vi.fn();
  hook.subscribe = vi.fn();
  return { useTenantStore: hook };
});

vi.mock('@/stores/auth', () => ({
  useAuthStore: vi.fn(() => ({
    user: { name: 'Test User', email: 'test@example.com' },
    logout: vi.fn(),
  })),
}));

vi.mock('@/stores/project', () => {
  const state = {
    currentProject: null,
    projects: [],
    setCurrentProject: vi.fn(),
    getProject: vi.fn(),
  };
  const hook = ((selector?: any) => (selector ? selector(state) : state)) as any;
  hook.getState = () => state;
  hook.setState = vi.fn();
  hook.subscribe = vi.fn();
  return { useProjectStore: hook };
});

vi.mock('@/components/layout/TenantChatSidebar', () => ({
  TenantChatSidebar: () => <div data-testid="tenant-sidebar">Sidebar</div>,
}));

vi.mock('@/components/layout/TenantHeader', () => ({
  __esModule: true,
  default: () => <div data-testid="tenant-header">Header</div>,
}));

vi.mock('@/components/common/RouteErrorBoundary', () => ({
  RouteErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('@/pages/tenant/TenantCreate', () => ({
  TenantCreateModal: () => null,
}));

vi.mock('@/components/agent/BackgroundSubAgentPanel', () => ({
  BackgroundSubAgentPanel: () => null,
}));

vi.mock('@/components/agent/chat/MobileSidebarDrawer', () => ({
  MobileSidebarDrawer: () => null,
}));

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/tenant/t1']}>
      <Routes>
        <Route path="/tenant/:tenantId" element={<TenantLayout />}>
          <Route index element={<div>Test Content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

describe('Layout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render layout with children', async () => {
    renderLayout();

    await waitFor(() => {
      expect(screen.getByText('Test Content')).toBeInTheDocument();
    });
  });

  it('should render sidebar', async () => {
    renderLayout();

    await waitFor(() => {
      expect(screen.getByTestId('tenant-sidebar')).toBeInTheDocument();
    });
  });

  it('should render header', async () => {
    renderLayout();

    await waitFor(() => {
      expect(screen.getByTestId('tenant-header')).toBeInTheDocument();
    });
  });

  it('should render content area', async () => {
    renderLayout();

    await waitFor(() => {
      const content = screen.getByText('Test Content');
      expect(content).toBeInTheDocument();
    });
  });

  it('should have skip to main content link', async () => {
    renderLayout();

    await waitFor(() => {
      expect(screen.getByText('Skip to main content')).toBeInTheDocument();
    });
  });

  it('should render main content area with correct id', async () => {
    renderLayout();

    await waitFor(() => {
      const main = document.getElementById('main-content');
      expect(main).toBeTruthy();
    });
  });
});
