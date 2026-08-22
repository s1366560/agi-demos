import type { ReactNode } from 'react';

import { MemoryRouter, Outlet } from 'react-router-dom';

import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '@/App';
import {
  activateWebPluginGenerationRootV2,
  deactivateWebPluginGenerationRootV2,
} from '@/plugins/webPluginGenerationV2';
import { createDefaultBusinessRouteElementsV2 } from '@/routes/v2/webDefaultBusinessRouteElementsV2';

const authState = {
  isAuthenticated: true,
  user: { user_id: 'user-1', email: 'user@example.com', must_change_password: false },
};

type RouteAuthorityTestState = {
  routeArtifacts: Array<{
    createRouteElements: () => ReactNode;
    id: string;
  }>;
  routeArtifactIds: string[];
  status: 'disabled' | 'loading' | 'ready' | 'unavailable';
};

const routeAuthority = vi.hoisted(() => ({
  state: {
    routeArtifacts: [],
    routeArtifactIds: ['web.routes.default-business.v1'],
    status: 'ready',
  } as RouteAuthorityTestState,
}));

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

vi.mock('@/routes/v2/WebRouteAuthorityV2', () => ({
  WebRouteAuthorityProviderV2: ({
    children,
  }: {
    children: ReactNode | ((state: RouteAuthorityTestState) => ReactNode);
  }) => <>{typeof children === 'function' ? children(routeAuthority.state) : children}</>,
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

vi.mock('@/pages/NotFound', () => ({
  NotFound: () => <div data-testid="not-found-route">not found</div>,
}));

function renderAppAt(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <App />
    </MemoryRouter>
  );
}

describe('App project Agent production routes', () => {
  beforeEach(() => {
    routeAuthority.state = {
      routeArtifacts: [
        {
          createRouteElements: createDefaultBusinessRouteElementsV2,
          id: 'web.routes.default-business.v1',
        },
      ],
      routeArtifactIds: ['web.routes.default-business.v1'],
      status: 'ready',
    };
    activateWebPluginGenerationRootV2();
  });
  afterEach(async () => deactivateWebPluginGenerationRootV2());

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

  it('does not mount a known business route when its V2 artifact is disabled', async () => {
    routeAuthority.state = { routeArtifacts: [], routeArtifactIds: [], status: 'ready' };

    renderAppAt('/tenant/tenant-1/project/project-1/agent');

    expect(await screen.findByTestId('not-found-route')).toBeInTheDocument();
    expect(screen.queryByTestId('project-agent-route')).not.toBeInTheDocument();
  });

  it('shows the generation loader for an authenticated business URL during bootstrap', async () => {
    routeAuthority.state = { routeArtifacts: [], routeArtifactIds: [], status: 'loading' };

    renderAppAt('/tenant/tenant-1/project/project-1/agent');

    expect(await screen.findByRole('status')).toHaveTextContent('common.loading');
    expect(screen.queryByTestId('project-agent-route')).not.toBeInTheDocument();
  });
});
