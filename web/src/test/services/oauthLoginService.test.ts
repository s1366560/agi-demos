import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { httpClient } from '@/services/client/httpClient';
import { ApiError, ApiErrorType } from '@/services/client/ApiError';
import { oauthLoginService, oauthReasonCode } from '@/services/oauthLoginService';

describe('oauthLoginService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists only providers exposed by the server authority', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      providers: [{ id: 'google', display_name: 'Google' }],
    });

    const providers = await oauthLoginService.listProviders();

    expect(httpClient.get).toHaveBeenCalledWith('/auth/oauth/providers');
    expect(providers).toEqual([{ id: 'google', display_name: 'Google' }]);
  });

  it('requests an authorization URL without placing credentials in the browser', async () => {
    (httpClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      provider: 'google',
      authorization_url: 'https://accounts.google.com/o/oauth2/v2/auth?state=opaque',
      expires_in: 600,
    });

    const result = await oauthLoginService.beginAuthorization('google', '/tenant/t-1/overview');

    expect(httpClient.post).toHaveBeenCalledWith('/auth/oauth/google/authorize', {
      redirect_to: '/tenant/t-1/overview',
    });
    expect(result.authorization_url).toContain('accounts.google.com');
  });

  it('rejects unsafe redirect targets before contacting the backend', async () => {
    await expect(
      oauthLoginService.beginAuthorization('google', '//attacker.example/path')
    ).rejects.toThrow('OAuth redirect target must be a same-origin path');
    expect(httpClient.post).not.toHaveBeenCalled();
  });

  it('completes authorization through the server-owned callback contract', async () => {
    (httpClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      access_token: 'opaque-session-token',
      token_type: 'bearer',
      redirect_to: '/tenant/tenant-1/overview',
      user: {
        user_id: 'user-1',
        email: 'user@example.com',
        name: 'Example User',
        roles: ['member'],
        is_active: true,
        created_at: '2026-08-06T00:00:00.000Z',
      },
    });

    const result = await oauthLoginService.completeAuthorization('google', 'code-1', 'state-1');

    expect(httpClient.post).toHaveBeenCalledWith('/auth/oauth/google/callback', {
      code: 'code-1',
      state: 'state-1',
    });
    expect(result.redirect_to).toBe('/tenant/tenant-1/overview');
  });

  it('rejects an unsafe redirect returned by the callback authority', async () => {
    (httpClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      access_token: 'opaque-session-token',
      token_type: 'bearer',
      redirect_to: '//attacker.example/path',
      user: {
        user_id: 'user-1',
        email: 'user@example.com',
        name: 'Example User',
        roles: ['member'],
        is_active: true,
        created_at: '2026-08-06T00:00:00.000Z',
      },
    });

    await expect(
      oauthLoginService.completeAuthorization('google', 'code-1', 'state-1')
    ).rejects.toThrow('OAuth redirect target must be a same-origin path');
  });

  it('reads a stable OAuth reason code from a structured API error', () => {
    const error = new ApiError(
      ApiErrorType.AUTHENTICATION,
      'OAUTH_CALLBACK_FAILED',
      'OAuth callback failed',
      401,
      { detail: { reason_code: 'oauth_callback_state_invalid' } }
    );

    expect(oauthReasonCode(error)).toBe('oauth_callback_state_invalid');
  });
});
