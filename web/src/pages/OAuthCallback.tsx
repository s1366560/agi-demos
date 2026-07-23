/**
 * OAuth Callback Page
 *
 * Handles OAuth provider callbacks at /login/callback/:provider
 * Exchanges authorization code for token, stores auth state, and redirects.
 *
 * @module pages/OAuthCallback
 */

import { useEffect, useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { AlertCircle, CheckCircle, Loader2 } from 'lucide-react';

import { useAuthStore } from '@/stores/auth';

import { httpClient } from '@/services/client/httpClient';

import { AuthSplitLayout } from '@/components/auth/AuthSplitLayout';

interface OAuthTokenResponse {
  access_token: string;
  token_type: string;
  user: {
    user_id: string;
    email: string;
    name: string;
    roles: string[];
    is_active: boolean;
    created_at: string;
    profile?: Record<string, unknown>;
  };
}

type CallbackStatus = 'loading' | 'success' | 'error';

function parseRedirectUrl(encodedState: string): string | undefined {
  try {
    const stateData = JSON.parse(atob(encodedState)) as { redirect_to?: unknown };
    return typeof stateData.redirect_to === 'string' ? stateData.redirect_to : undefined;
  } catch {
    // State is not encoded JSON, ignore
    return undefined;
  }
}

export const OAuthCallback: React.FC = () => {
  const { provider } = useParams<{ provider: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [status, setStatus] = useState<CallbackStatus>('loading');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const token = useAuthStore((state) => state.token);

  const code = searchParams.get('code');
  const state = searchParams.get('state');
  const error = searchParams.get('error');
  const errorDescription = searchParams.get('error_description');

  // Map backend response to frontend User format
  const mapUser = (backendUser: OAuthTokenResponse['user']) => ({
    id: backendUser.user_id,
    email: backendUser.email,
    name: backendUser.name,
    roles: backendUser.roles,
    is_active: backendUser.is_active,
    created_at: backendUser.created_at,
    profile: backendUser.profile,
  });

  const handleOAuthCallback = useCallback(async () => {
    // Check for OAuth error in URL params
    if (error) {
      setStatus('error');
      setErrorMessage(errorDescription || error);
      return;
    }

    // Validate required params
    if (!code) {
      setStatus('error');
      setErrorMessage(t('login.oauth.errors.noCode', 'Authorization code not found'));
      return;
    }

    if (!provider) {
      setStatus('error');
      setErrorMessage(t('login.oauth.errors.noProvider', 'OAuth provider not specified'));
      return;
    }

    try {
      // Exchange code for token via backend API
      const response = await httpClient.post<OAuthTokenResponse>(
        `/auth/oauth/${provider}/callback`,
        {
          code,
          state,
        }
      );

      const { access_token, user } = response;

      // Store token in auth store (this will persist via zustand persist middleware)
      useAuthStore.setState({
        token: access_token,
        user: mapUser(user),
        isAuthenticated: true,
        isLoading: false,
        error: null,
      });

      setStatus('success');

      // Get redirect URL from state or default to home
      let redirectUrl = '/';

      // Check if state contains a redirect URL (encoded JSON).
      // Only allow same-origin paths (starting with a single '/') to
      // prevent open-redirects to external sites.
      if (state) {
        const parsed = parseRedirectUrl(state);
        if (parsed?.startsWith('/') && !parsed.startsWith('//')) {
          redirectUrl = parsed;
        }
      }

      // Short delay to show success state before redirect
      setTimeout(() => {
        void navigate(redirectUrl, { replace: true });
      }, 500);
    } catch (err) {
      setStatus('error');

      // Extract error message from API response
      const apiError = err as { response?: { data?: { detail?: string } } };
      const detail = apiError.response?.data?.detail;

      setErrorMessage(
        detail || t('login.oauth.errors.exchangeFailed', 'Failed to complete OAuth authentication')
      );
    }
  }, [code, error, errorDescription, provider, state, navigate, t]);

  useEffect(() => {
    // Only run callback once
    if (status === 'loading' && !token) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void handleOAuthCallback();
    } else if (token) {
      // Already authenticated, redirect to home
      void navigate('/', { replace: true });
    }
  }, [status, token, handleOAuthCallback, navigate]);

  const handleRetry = () => {
    void navigate('/login');
  };

  const providerName = provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : '';

  return (
    <AuthSplitLayout
      heroTitle={t('login.hero.title', 'Enterprise AI Memory Cloud')}
      heroSubtitle={t(
        'login.hero.subtitle',
        'Build intelligent applications with persistent memory'
      )}
      copyright={t('login.footer.rights', { year: new Date().getFullYear() })}
      mobileTitle="MemStack"
    >
      {/* Status Content */}
      <div className="text-center" aria-live="polite">
        {status === 'loading' && (
          <>
            <div className="mx-auto w-16 h-16 flex items-center justify-center mb-6 bg-blue-100 dark:bg-blue-900/30 rounded-full">
              <Loader2 className="h-8 w-8 text-blue-600 dark:text-blue-400 animate-spin motion-reduce:animate-none" />
            </div>
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
              {t('login.oauth.processing', 'Completing sign in…')}
            </h2>
            <p className="text-gray-600 dark:text-slate-400">
              {providerName
                ? t('login.oauth.authenticatingWith', {
                    provider: providerName,
                    defaultValue: `Authenticating with ${providerName}…`,
                  })
                : t('login.oauth.authenticating', 'Authenticating…')}
            </p>
          </>
        )}

        {status === 'success' && (
          <>
            <div className="mx-auto w-16 h-16 flex items-center justify-center mb-6 bg-green-100 dark:bg-green-900/30 rounded-full">
              <CheckCircle className="h-8 w-8 text-green-600 dark:text-green-400" />
            </div>
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
              {t('login.oauth.success', 'Sign in successful!')}
            </h2>
            <p className="text-gray-600 dark:text-slate-400">
              {t('login.oauth.redirecting', 'Redirecting you now…')}
            </p>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="mx-auto w-16 h-16 flex items-center justify-center mb-6 bg-red-100 dark:bg-red-900/30 rounded-full">
              <AlertCircle className="h-8 w-8 text-red-600 dark:text-red-400" />
            </div>
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
              {t('login.oauth.failed', 'Sign in failed')}
            </h2>
            {errorMessage && (
              <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/30 rounded-lg">
                <p className="text-sm text-red-700 dark:text-red-300">{errorMessage}</p>
              </div>
            )}
            <button
              type="button"
              onClick={handleRetry}
              className="mt-6 inline-flex items-center px-6 py-3 border border-transparent rounded-lg shadow-sm text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-500 transition-colors"
            >
              {t('login.oauth.tryAgain', 'Try again')}
            </button>
          </>
        )}
      </div>
    </AuthSplitLayout>
  );
};

export default OAuthCallback;
