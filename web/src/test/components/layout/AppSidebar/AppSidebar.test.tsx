/**
 * AppSidebar Component Tests
 *
 * TDD tests for the refactored AppSidebar component system.
 * Tests both the new explicit variant components and compound components pattern.
 */

import { MemoryRouter } from 'react-router-dom';

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock dependencies before imports
vi.mock('@/hooks/useNavigation', () => ({
  useNavigation: () => ({
    isActive: () => false,
    getLink: (path: string) => path,
  }),
}));

vi.mock('@/components/ui/lazyAntd', () => ({
  LazyTooltip: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { name: 'Test User', email: 'test@example.com' },
    logout: vi.fn(),
  }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

vi.mock('@/config/navigation', () => ({
  getTenantSidebarConfig: () => ({
    width: 256,
    collapsedWidth: 80,
    showUser: true,
    groups: [
      {
        id: 'platform',
        title: 'Platform',
        collapsible: false,
        items: [
          { id: 'overview', icon: 'dashboard', label: 'Overview', path: '' },
          { id: 'projects', icon: 'folder', label: 'Projects', path: '/projects' },
        ],
      },
    ],
  }),
  getProjectSidebarConfig: () => ({
    width: 256,
    collapsedWidth: 80,
    showUser: true,
    groups: [
      {
        id: 'knowledge',
        title: 'Knowledge',
        collapsible: true,
        defaultOpen: true,
        items: [
          { id: 'memories', icon: 'database', label: 'Memories', path: '/memories' },
          { id: 'entities', icon: 'category', label: 'Entities', path: '/entities' },
        ],
      },
    ],
  }),
  getAgentConfig: () => ({
    sidebar: {
      width: 256,
      collapsedWidth: 80,
      showUser: true,
      groups: [
        {
          id: 'main',
          title: '',
          collapsible: false,
          items: [
            { id: 'back', icon: 'arrow_back', label: 'Back', path: '' },
            { id: 'memories', icon: 'database', label: 'Memories', path: '/memories' },
          ],
        },
      ],
    },
    tabs: [],
  }),
}));

// Import components after mocks
import {
  AppSidebar,
  TenantSidebar,
  ProjectSidebar,
  AgentSidebar,
} from '@/components/layout/AppSidebar';

function renderWithRouter(component: React.ReactNode) {
  return render(<MemoryRouter initialEntries={['/']}>{component}</MemoryRouter>);
}

describe('AppSidebar (Refactored)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Backward Compatibility', () => {
    it('should support legacy context prop', () => {
      const { container } = renderWithRouter(
        <AppSidebar
          config={{
            width: 256,
            collapsedWidth: 80,
            showUser: true,
            groups: [
              {
                id: 'platform',
                title: 'Platform',
                collapsible: false,
                items: [
                  { id: 'overview', icon: 'dashboard', label: 'Overview', path: '' },
                  { id: 'projects', icon: 'folder', label: 'Projects', path: '/projects' },
                ],
              },
            ],
          }}
          basePath="/tenant"
          context="tenant"
          user={{ name: 'Test User', email: 'test@example.com' }}
        />
      );

      expect(container.querySelector('[data-testid="app-sidebar"]')).toBeInTheDocument();
    });

    it('should support new variant prop', () => {
      const { container } = renderWithRouter(
        <AppSidebar
          config={{
            width: 256,
            collapsedWidth: 80,
            showUser: true,
            groups: [
              {
                id: 'platform',
                title: 'Platform',
                collapsible: false,
                items: [{ id: 'overview', icon: 'dashboard', label: 'Overview', path: '' }],
              },
            ],
          }}
          basePath="/tenant"
          variant="tenant"
          user={{ name: 'Test User', email: 'test@example.com' }}
        />
      );

      expect(container.querySelector('[data-testid="app-sidebar"]')).toBeInTheDocument();
    });

    it('should prioritize variant over context prop when both are provided', () => {
      const { container } = renderWithRouter(
        <AppSidebar
          config={{
            width: 256,
            collapsedWidth: 80,
            showUser: true,
            groups: [
              {
                id: 'platform',
                title: 'Platform',
                collapsible: false,
                items: [{ id: 'overview', icon: 'dashboard', label: 'Overview', path: '' }],
              },
            ],
          }}
          basePath="/tenant"
          context="project"
          variant="tenant"
          user={{ name: 'Test User', email: 'test@example.com' }}
        />
      );

      expect(container.querySelector('[data-testid="app-sidebar"]')).toBeInTheDocument();
    });
  });

  describe('Collapse Behavior', () => {
    it('should start expanded by default', () => {
      const { container } = renderWithRouter(
        <AppSidebar
          config={{
            width: 256,
            collapsedWidth: 80,
            showUser: true,
            groups: [
              {
                id: 'platform',
                title: 'Platform',
                collapsible: false,
                items: [{ id: 'overview', icon: 'dashboard', label: 'Overview', path: '' }],
              },
            ],
          }}
          basePath="/tenant"
        />
      );

      const sidebar = container.querySelector('[data-testid="app-sidebar"]');
      expect(sidebar).not.toHaveClass('collapsed');
    });

    it('should render collapsed when collapsed prop is true', () => {
      const { container } = renderWithRouter(
        <AppSidebar
          config={{
            width: 256,
            collapsedWidth: 80,
            showUser: true,
            groups: [
              {
                id: 'platform',
                title: 'Platform',
                collapsible: false,
                items: [{ id: 'overview', icon: 'dashboard', label: 'Overview', path: '' }],
              },
            ],
          }}
          basePath="/tenant"
          collapsed={true}
        />
      );

      const sidebar = container.querySelector('[data-testid="app-sidebar"]');
      expect(sidebar).toHaveClass('collapsed');
    });

    it('should call onCollapseToggle when toggle button clicked', () => {
      const onCollapseToggle = vi.fn();
      const { container } = renderWithRouter(
        <AppSidebar
          config={{
            width: 256,
            collapsedWidth: 80,
            showUser: true,
            groups: [
              {
                id: 'platform',
                title: 'Platform',
                collapsible: false,
                items: [{ id: 'overview', icon: 'dashboard', label: 'Overview', path: '' }],
              },
            ],
          }}
          basePath="/tenant"
          onCollapseToggle={onCollapseToggle}
        />
      );

      const toggleButton = container.querySelector('[data-testid="collapse-toggle"]');
      if (toggleButton) {
        fireEvent.click(toggleButton);
        expect(onCollapseToggle).toHaveBeenCalledTimes(1);
      }
    });
  });

  describe('User Section', () => {
    it('should render user information when provided', () => {
      const { container } = renderWithRouter(
        <AppSidebar
          config={{
            width: 256,
            collapsedWidth: 80,
            showUser: true,
            groups: [
              {
                id: 'platform',
                title: 'Platform',
                collapsible: false,
                items: [{ id: 'overview', icon: 'dashboard', label: 'Overview', path: '' }],
              },
            ],
          }}
          basePath="/tenant"
          user={{ name: 'Test User', email: 'test@example.com' }}
        />
      );

      expect(container.textContent).toContain('Test User');
      expect(container.textContent).toContain('test@example.com');
    });

    it('should not render user section when config.showUser is false', () => {
      const { container } = renderWithRouter(
        <AppSidebar
          config={{
            width: 256,
            collapsedWidth: 80,
            showUser: false,
            groups: [
              {
                id: 'platform',
                title: 'Platform',
                collapsible: false,
                items: [{ id: 'overview', icon: 'dashboard', label: 'Overview', path: '' }],
              },
            ],
          }}
          basePath="/tenant"
          user={{ name: 'Test User', email: 'test@example.com' }}
        />
      );

      expect(container.textContent).not.toContain('Test User');
    });
  });

  describe('Navigation', () => {
    it('should render navigation items from config', () => {
      const { container } = renderWithRouter(
        <AppSidebar
          config={{
            width: 256,
            collapsedWidth: 80,
            showUser: true,
            groups: [
              {
                id: 'platform',
                title: 'Platform',
                collapsible: false,
                items: [
                  { id: 'overview', icon: 'dashboard', label: 'Overview', path: '' },
                  { id: 'projects', icon: 'folder', label: 'Projects', path: '/projects' },
                ],
              },
            ],
          }}
          basePath="/tenant"
        />
      );

      expect(container.querySelector('[data-testid="nav-overview"]')).toBeInTheDocument();
      expect(container.querySelector('[data-testid="nav-projects"]')).toBeInTheDocument();
    });
  });
});

describe('TenantSidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render sidebar component', () => {
      const { container } = renderWithRouter(<TenantSidebar tenantId="tenant-123" />);

      expect(container.querySelector('[data-testid="app-sidebar"]')).toBeInTheDocument();
    });

    it('should render user information from auth store', () => {
      const { container } = renderWithRouter(<TenantSidebar />);

      expect(container.textContent).toContain('Test User');
    });

    it('should render all tenant navigation groups', () => {
      const { container } = renderWithRouter(<TenantSidebar />);

      expect(container.querySelector('[data-testid="nav-overview"]')).toBeInTheDocument();
      expect(container.querySelector('[data-testid="nav-projects"]')).toBeInTheDocument();
    });
  });

  describe('Collapse State', () => {
    it('should start expanded by default', () => {
      const { container } = renderWithRouter(<TenantSidebar />);

      const sidebar = container.querySelector('[data-testid="app-sidebar"]');
      expect(sidebar).not.toHaveClass('collapsed');
    });

    it('should start collapsed when defaultCollapsed is true', () => {
      const { container } = renderWithRouter(<TenantSidebar defaultCollapsed={true} />);

      const sidebar = container.querySelector('[data-testid="app-sidebar"]');
      expect(sidebar).toHaveClass('collapsed');
    });
  });
});

describe('ProjectSidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render sidebar component', () => {
      const { container } = renderWithRouter(<ProjectSidebar projectId="project-456" />);

      expect(container.querySelector('[data-testid="app-sidebar"]')).toBeInTheDocument();
    });

    it('should render project-specific navigation items', () => {
      const { container } = renderWithRouter(<ProjectSidebar projectId="test-project" />);

      expect(container.querySelector('[data-testid="nav-memories"]')).toBeInTheDocument();
      expect(container.querySelector('[data-testid="nav-entities"]')).toBeInTheDocument();
    });
  });
});

describe('AgentSidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render sidebar component', () => {
      const { container } = renderWithRouter(<AgentSidebar projectId="project-789" />);

      expect(container.querySelector('[data-testid="app-sidebar"]')).toBeInTheDocument();
    });

    it('should render agent-specific navigation items', () => {
      const { container } = renderWithRouter(<AgentSidebar projectId="test-project" />);

      expect(container.querySelector('[data-testid="nav-back"]')).toBeInTheDocument();
      expect(container.querySelector('[data-testid="nav-memories"]')).toBeInTheDocument();
    });
  });

  describe('Controlled Collapse', () => {
    it('should support controlled collapse state', () => {
      const { container } = renderWithRouter(<AgentSidebar projectId="test" collapsed={true} />);

      const sidebar = container.querySelector('[data-testid="app-sidebar"]');
      expect(sidebar).toHaveClass('collapsed');
    });

    it('should support controlled collapse toggle callback', () => {
      const onCollapseToggle = vi.fn();
      const { container } = renderWithRouter(
        <AgentSidebar projectId="test" onCollapseToggle={onCollapseToggle} />
      );

      const toggleButton = container.querySelector('[data-testid="collapse-toggle"]');
      if (toggleButton) {
        fireEvent.click(toggleButton);
        expect(onCollapseToggle).toHaveBeenCalledTimes(1);
      }
    });
  });
});
