import { ApiError } from './client/ApiError';
import { httpClient } from './client/httpClient';

export interface OAuthProviderDescriptor {
  id: string;
  display_name: string;
}

export interface OAuthAuthorizationResponse {
  provider: string;
  authorization_url: string;
  expires_in: number;
}

export interface OAuthLoginUser {
  user_id: string;
  email: string;
  name: string;
  roles: string[];
  global_roles?: string[] | undefined;
  is_active: boolean;
  is_superuser?: boolean | undefined;
  created_at: string;
  profile?: Record<string, unknown> | undefined;
  preferred_language?: string | null | undefined;
}

export interface OAuthCallbackResponse {
  access_token: string;
  token_type: string;
  redirect_to: string;
  user: OAuthLoginUser;
}

const PROVIDER_ID = /^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/u;

function requireProviderId(value: string): string {
  if (!PROVIDER_ID.test(value)) {
    throw new Error('OAuth provider identifier is invalid');
  }
  return value;
}

function requireSameOriginPath(value: string): string {
  if (!value.startsWith('/') || value.startsWith('//')) {
    throw new Error('OAuth redirect target must be a same-origin path');
  }
  const parsed = new URL(value, 'https://memstack.local');
  if (parsed.origin !== 'https://memstack.local') {
    throw new Error('OAuth redirect target must be a same-origin path');
  }
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}

function requireAuthorizationUrl(value: string): string {
  const parsed = new URL(value);
  const loopbackHttp =
    parsed.protocol === 'http:' &&
    (parsed.hostname === 'localhost' ||
      parsed.hostname === '127.0.0.1' ||
      parsed.hostname === '[::1]');
  if (
    (parsed.protocol !== 'https:' && !loopbackHttp) ||
    parsed.username.length > 0 ||
    parsed.password.length > 0
  ) {
    throw new Error('OAuth authorization URL is invalid');
  }
  return parsed.toString();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function requireProvider(value: unknown): OAuthProviderDescriptor {
  if (
    !isRecord(value) ||
    typeof value.id !== 'string' ||
    typeof value.display_name !== 'string' ||
    value.display_name.trim().length === 0
  ) {
    throw new Error('OAuth provider response is invalid');
  }
  return { id: requireProviderId(value.id), display_name: value.display_name.trim() };
}

function requireAuthorization(
  value: OAuthAuthorizationResponse,
  providerId: string
): OAuthAuthorizationResponse {
  if (
    !isRecord(value) ||
    value.provider !== providerId ||
    typeof value.authorization_url !== 'string' ||
    !Number.isInteger(value.expires_in) ||
    value.expires_in <= 0
  ) {
    throw new Error('OAuth authorization response is invalid');
  }
  return {
    provider: providerId,
    authorization_url: requireAuthorizationUrl(value.authorization_url),
    expires_in: value.expires_in,
  };
}

function requireCallback(value: OAuthCallbackResponse): OAuthCallbackResponse {
  if (
    !isRecord(value) ||
    typeof value.access_token !== 'string' ||
    value.access_token.length === 0 ||
    value.token_type !== 'bearer' ||
    typeof value.redirect_to !== 'string' ||
    !isRecord(value.user) ||
    typeof value.user.user_id !== 'string' ||
    typeof value.user.email !== 'string' ||
    typeof value.user.name !== 'string' ||
    !Array.isArray(value.user.roles) ||
    typeof value.user.is_active !== 'boolean' ||
    typeof value.user.created_at !== 'string'
  ) {
    throw new Error('OAuth callback response is invalid');
  }
  return { ...value, redirect_to: requireSameOriginPath(value.redirect_to) };
}

export function oauthReasonCode(error: unknown): string | null {
  if (!(error instanceof ApiError) || !isRecord(error.details)) return null;
  const detail = error.details.detail;
  if (!isRecord(detail) || typeof detail.reason_code !== 'string') return null;
  return detail.reason_code;
}

export const oauthLoginService = {
  async listProviders(): Promise<OAuthProviderDescriptor[]> {
    const response = await httpClient.get<{ providers: unknown }>('/auth/oauth/providers');
    if (!isRecord(response) || !Array.isArray(response.providers)) {
      throw new Error('OAuth provider response is invalid');
    }
    return response.providers.map(requireProvider);
  },

  async beginAuthorization(
    providerId: string,
    redirectTo: string
  ): Promise<OAuthAuthorizationResponse> {
    const provider = requireProviderId(providerId);
    const redirect_to = requireSameOriginPath(redirectTo);
    const response = await httpClient.post<OAuthAuthorizationResponse>(
      `/auth/oauth/${encodeURIComponent(provider)}/authorize`,
      { redirect_to }
    );
    return requireAuthorization(response, provider);
  },

  async completeAuthorization(
    providerId: string,
    code: string,
    state: string
  ): Promise<OAuthCallbackResponse> {
    const provider = requireProviderId(providerId);
    if (code.length === 0 || state.length === 0) {
      throw new Error('OAuth callback parameters are invalid');
    }
    const response = await httpClient.post<OAuthCallbackResponse>(
      `/auth/oauth/${encodeURIComponent(provider)}/callback`,
      { code, state }
    );
    return requireCallback(response);
  },
};

export default oauthLoginService;
