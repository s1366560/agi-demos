import type { ReactNode } from 'react';

import { MemoryRouter, Outlet } from 'react-router-dom';

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import App from '@/App';

const authState = {
  isAuthenticated: true,
  user: { user_id: 'user-1', email: 'user@example.com', must_change_password: false },
};

vi.mock('@/stores/auth', () => ({
  useAuthStore: (selector: (state: typeof authState) => unknown) => selector(authState),
}));

vi.mock('@/components/common/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('@/components/common/OrgSetupGuard', () => ({
  OrgSetupGuard: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('@/layouts/TenantLayout', () => ({
  TenantLayout: () => <Outlet />,
}));

vi.mock('@/theme', () => ({
  ThemeProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('@/pages/project/ProjectAgentDashboard', () => ({
  default: () => <div data-testid="project-agent-route">dashboard</div>,
}));

vi.mock('@/pages/project/ProjectAgentLogs', () => ({
  default: () => <div data-testid="project-agent-route">logs</div>,
}));

vi.mock('@/pages/project/ProjectAgentPatterns', () => ({
  default: () => <div data-testid="project-agent-route">patterns</div>,
}));

function renderAppAt(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <App />
    </MemoryRouter>
  );
}

describe('App project Agent production routes', () => {
  it.each([
    ['/tenant/tenant-1/project/project-1/agent', 'dashboard'],
    ['/tenant/tenant-1/project/project-1/agent/logs', 'logs'],
    ['/tenant/tenant-1/project/project-1/agent/patterns', 'patterns'],
  ])('renders and restores %s through the production router', async (entry, expected) => {
    const firstRender = renderAppAt(entry);
    expect(await screen.findByTestId('project-agent-route')).toHaveTextContent(expected);

    firstRender.unmount();
    renderAppAt(entry);

    expect(await screen.findByTestId('project-agent-route')).toHaveTextContent(expected);
  });
});
