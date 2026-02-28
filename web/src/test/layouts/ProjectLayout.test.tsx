import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ProjectLayout } from '../../layouts/ProjectLayout';
import { screen, render, waitFor } from '../utils';

// Mock stores with complete state to prevent useEffect from running async operations
vi.mock('@/stores/project', () => ({
  useProjectStore: vi.fn(() => ({
    currentProject: { id: 'p1', name: 'Test Project' },
    projects: [{ id: 'p1', name: 'Test Project' }],
    setCurrentProject: vi.fn(),
    getProject: vi.fn().mockResolvedValue({ id: 'p1', name: 'Test Project' }),
  })),
}));

vi.mock('@/stores/tenant', () => ({
  useTenantStore: vi.fn(() => ({
    tenants: [{ id: 't1', name: 'Test Tenant' }],
    currentTenant: { id: 't1', name: 'Test Tenant' },
    setCurrentTenant: vi.fn(),
    listTenants: vi.fn().mockResolvedValue([]),
  })),
}));

vi.mock('@/stores/auth', () => ({
  useAuthStore: vi.fn(() => ({
    user: { name: 'Test User', email: 'test@example.com' },
    logout: vi.fn(),
  })),
}));

// Mock i18n - must be before component imports
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'nav.overview': 'Overview',
        'nav.knowledgeBase': 'Knowledge Base',
        'nav.memories': 'Memories',
        'nav.entities': 'Entities',
        'nav.communities': 'Communities',
        'nav.knowledgeGraph': 'Knowledge Graph',
        'nav.discovery': 'Discovery',
        'nav.deepSearch': 'Deep Search',
        'nav.configuration': 'Configuration',
        'nav.schema': 'Schema',
        'nav.maintenance': 'Maintenance',
        'nav.team': 'Team',
        'nav.settings': 'Settings',
        'nav.support': 'Support',
        'nav.newMemory': 'New Memory',
      };
      return translations[key] || key;
    },
  }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useParams: vi.fn(() => ({ projectId: 'p1' })),
  };
});

vi.mock('../../components/shared/ui/WorkspaceSwitcher', () => ({
  WorkspaceSwitcher: () => <div data-testid="workspace-switcher">MockSwitcher</div>,
}));
vi.mock('../../components/shared/ui/ThemeToggle', () => ({
  ThemeToggle: () => <div data-testid="theme-toggle">Theme</div>,
}));
vi.mock('../../components/shared/ui/LanguageSwitcher', () => ({
  LanguageSwitcher: () => <div data-testid="lang-toggle">Lang</div>,
}));

describe('ProjectLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders project navigation items', async () => {
    render(<ProjectLayout />);

    // Wait for any async state updates to complete
    await waitFor(() => {
      expect(screen.getByText('Overview')).toBeInTheDocument();
    });
    expect(screen.getByText('Memories')).toBeInTheDocument();
    expect(screen.getByText('Knowledge Graph')).toBeInTheDocument();
  });

  it('renders header components', async () => {
    render(<ProjectLayout />);

    await waitFor(() => {
      expect(screen.getByTestId('theme-toggle')).toBeInTheDocument();
    });
    expect(screen.getByTestId('lang-toggle')).toBeInTheDocument();
    expect(screen.getByTestId('workspace-switcher')).toBeInTheDocument();
  });

  it('renders New Memory button', async () => {
    render(<ProjectLayout />);

    await waitFor(() => {
      expect(screen.getByText('New Memory')).toBeInTheDocument();
    });
  });
});
