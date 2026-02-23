import { beforeEach, describe, expect, it, vi } from 'vitest';

import TenantHeader from '@/components/layout/TenantHeader';

import { render, screen } from '../../utils';

const togglePanel = vi.fn();
const setTheme = vi.fn();
const logout = vi.fn();

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback || _key,
    i18n: {
      language: 'en-US',
      changeLanguage: vi.fn(),
    },
  }),
}));

vi.mock('@/stores/auth', () => ({
  useUser: () => ({
    name: 'Test User',
    email: 'test@example.com',
    profile: {},
  }),
  useAuthActions: () => ({ logout }),
}));

vi.mock('@/stores/backgroundStore', () => ({
  useRunningCount: () => 0,
  useBackgroundStore: (selector: (state: { togglePanel: typeof togglePanel }) => unknown) =>
    selector({ togglePanel }),
}));

vi.mock('@/stores/theme', () => ({
  useThemeStore: (selector: (state: { theme: 'light'; setTheme: typeof setTheme }) => unknown) =>
    selector({ theme: 'light', setTheme }),
}));

describe('TenantHeader', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders agent workspace entry in top navigation', () => {
    render(
      <TenantHeader
        tenantId="tenant-1"
        sidebarCollapsed={false}
        onSidebarToggle={vi.fn()}
        onMobileMenuOpen={vi.fn()}
      />
    );

    expect(screen.getByRole('link', { name: 'Agent Workspace' })).toHaveAttribute(
      'href',
      '/tenant/tenant-1/agent-workspace'
    );
  });
});
