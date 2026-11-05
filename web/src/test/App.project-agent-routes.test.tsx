import type { ReactNode } from 'react';

import { MemoryRouter, Outlet, useLocation } from 'react-router-dom';

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '@/App';
import {
  activateWebPluginGenerationRootV2,
  deactivateWebPluginGenerationRootV2,
} from '@/plugins/webPluginGenerationV2';
import { createDefaultBusinessRouteElementsV2 } from '@/routes/v2/webDefaultBusinessRouteElementsV2';

type AuthState = {
  isAuthenticated: boolean;
  user: {
    user_id: string;
    email: string;
    must_change_password: boolean;
  } | null;
};

const authState: AuthState = {
  isAuthenticated: true,
  user: { user_id: 'user-1', email: 'user@example.com', must_change_password: false },
};

const authenticatedShellRender = vi.hoisted(() => vi.fn());

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
  useAuthStore: Object.assign(
    (selector: (state: typeof authState) => unknown) => selector(authState),
    { getState: () => authState, subscribe: () => () => undefined }
  ),
}));

vi.mock('@/components/common/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('@/components/common/OrgSetupGuard', () => ({
  OrgSetupGuard: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('@/plugins/WebRendererAuthenticatedShellV2', () => ({
  WebRendererAuthenticatedShellV2: () => {
    authenticatedShellRender();
    return <Outlet />;
  },
}));

vi.mock('@/pages/Login', () => ({
  Login: () => <div data-testid="login-route">login</div>,
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
      <LocationDisplay />
    </MemoryRouter>
  );
}

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="route-location">{location.pathname + location.search}</div>;
}

describe('App project Agent production routes', () => {
  beforeEach(() => {
    authenticatedShellRender.mockClear();
    authState.isAuthenticated = true;
    authState.user = {
      user_id: 'user-1',
      email: 'user@example.com',
      must_change_password: false,
    };
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
  afterEach(async () => {
    cleanup();
    await deactivateWebPluginGenerationRootV2();
  });

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

  it('mounts contributed business routes only behind the authenticated shell outlet', async () => {
    renderAppAt('/tenant/tenant-1/project/project-1/agent');

    expect(await screen.findByTestId('project-agent-route')).toBeInTheDocument();
    expect(authenticatedShellRender).toHaveBeenCalled();
  });

  it('keeps the unauthenticated login route outside the contributed shell boundary', async () => {
    authState.isAuthenticated = false;
    authState.user = null;

    renderAppAt('/login');

    expect(await screen.findByTestId('login-route')).toBeInTheDocument();
    expect(authenticatedShellRender).not.toHaveBeenCalled();
  });

  it('returns an expired protected session to login when its generation has retired', async () => {
    authState.isAuthenticated = false;
    authState.user = null;
    routeAuthority.state = { routeArtifacts: [], routeArtifactIds: [], status: 'disabled' };

    renderAppAt('/tenant?tab=overview');

    expect(await screen.findByTestId('login-route')).toBeInTheDocument();
    expect(screen.getByTestId('route-location')).toHaveTextContent(
      '/login?redirect=%2Ftenant%3Ftab%3Doverview'
    );
    expect(screen.queryByTestId('not-found-route')).not.toBeInTheDocument();
    expect(authenticatedShellRender).not.toHaveBeenCalled();
  });

  it('keeps an authenticated unknown route as not found after authority is ready', async () => {
    renderAppAt('/unknown-route');

    expect(await screen.findByTestId('not-found-route')).toBeInTheDocument();
    expect(screen.queryByTestId('login-route')).not.toBeInTheDocument();
  });

  it('shows the generation loader for an authenticated business URL during bootstrap', async () => {
    routeAuthority.state = { routeArtifacts: [], routeArtifactIds: [], status: 'loading' };

    renderAppAt('/tenant/tenant-1/project/project-1/agent');

    expect(await screen.findByRole('status')).toHaveTextContent('common.loading');
    expect(screen.queryByTestId('project-agent-route')).not.toBeInTheDocument();
  });
});
