import type { ReactNode } from 'react';

import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { OAuthCallback } from '@/pages/OAuthCallback';
import { ApiError, ApiErrorType } from '@/services/client/ApiError';

const mocks = vi.hoisted(() => ({
  completeAuthorization: vi.fn(),
  setAuthState: vi.fn(),
  token: null as string | null,
}));

vi.mock('@/stores/auth', () => {
  const useAuthStore = Object.assign(
    (selector: (state: { token: string | null }) => unknown) =>
      selector({ token: mocks.token }),
    { setState: mocks.setAuthState }
  );
  return { useAuthStore };
});

vi.mock('@/services/oauthLoginService', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/oauthLoginService')>();
  return {
    ...actual,
    oauthLoginService: {
      ...actual.oauthLoginService,
      completeAuthorization: mocks.completeAuthorization,
    },
  };
});

vi.mock('@/components/auth/AuthSplitLayout', () => ({
  AuthSplitLayout: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? key,
  }),
}));

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function renderCallback(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/login/callback/:provider" element={<OAuthCallback />} />
        <Route path="*" element={<LocationDisplay />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('OAuthCallback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.token = null;
  });

  it('stores the trusted session and restores the server-approved route', async () => {
    mocks.completeAuthorization.mockResolvedValue({
      access_token: 'opaque-session-token',
      token_type: 'bearer',
      redirect_to: '/tenant/tenant-1/overview',
      user: {
        user_id: 'user-1',
        email: 'user@example.com',
        name: 'Example User',
        roles: ['member'],
        global_roles: [],
        is_active: true,
        is_superuser: false,
        created_at: '2026-08-06T00:00:00.000Z',
      },
    });

    renderCallback('/login/callback/google?code=code-1&state=state-1');

    await waitFor(() => {
      expect(mocks.completeAuthorization).toHaveBeenCalledWith('google', 'code-1', 'state-1');
      expect(mocks.setAuthState).toHaveBeenCalledWith(
        expect.objectContaining({
          token: 'opaque-session-token',
          isAuthenticated: true,
          user: expect.objectContaining({ id: 'user-1', email: 'user@example.com' }),
        })
      );
    });
    expect(screen.getByText('login.oauth.success')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/tenant/tenant-1/overview');
    });
  });

  it('renders the stable authority reason when the callback is rejected', async () => {
    mocks.completeAuthorization.mockRejectedValue(
      new ApiError(
        ApiErrorType.AUTHENTICATION,
        'OAUTH_CALLBACK_FAILED',
        'OAuth callback failed',
        401,
        { detail: { reason_code: 'oauth_callback_state_invalid' } }
      )
    );

    renderCallback('/login/callback/google?code=code-1&state=expired-state');

    expect(await screen.findByText('oauth_callback_state_invalid')).toBeInTheDocument();
    expect(mocks.setAuthState).not.toHaveBeenCalled();
  });

  it('fails closed before transport when the one-time state is missing', async () => {
    renderCallback('/login/callback/google?code=code-1');

    expect(await screen.findByText('login.oauth.errors.noState')).toBeInTheDocument();
    expect(mocks.completeAuthorization).not.toHaveBeenCalled();
    expect(mocks.setAuthState).not.toHaveBeenCalled();
  });
});
