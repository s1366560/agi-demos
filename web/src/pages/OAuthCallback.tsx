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

import { Brain, AlertCircle, CheckCircle, Loader2 } from 'lucide-react';

import { useAuthStore } from '@/stores/auth';

import { httpClient } from '@/services/client/httpClient';

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

      // Check if state contains a redirect URL (encoded JSON)
      if (state) {
        try {
          const stateData = JSON.parse(atob(state));
          if (stateData.redirect_to) {
            redirectUrl = stateData.redirect_to;
          }
        } catch {
          // State is not encoded JSON, ignore
        }
      }

      // Short delay to show success state before redirect
      setTimeout(() => {
        navigate(redirectUrl, { replace: true });
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
      handleOAuthCallback();
    } else if (token) {
      // Already authenticated, redirect to home
      navigate('/', { replace: true });
    }
  }, [status, token, handleOAuthCallback, navigate]);

  const handleRetry = () => {
    navigate('/login');
  };

  const providerName = provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : '';

  return (
    <div className="min-h-screen flex bg-gray-50 dark:bg-[#121520]">
      {/* Left Side - Hero Section (same as Login page) */}
      <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden bg-slate-900">
        <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-br from-blue-600/20 to-purple-600/20 z-10" />
        <div className="absolute -top-24 -left-24 w-96 h-96 bg-blue-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob" />
        <div className="absolute top-1/2 left-1/2 w-96 h-96 bg-purple-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob animation-delay-2000" />
        <div className="absolute -bottom-24 -right-24 w-96 h-96 bg-indigo-500 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-blob animation-delay-4000" />

        <div className="relative z-20 flex flex-col justify-between w-full p-12 text-white">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-blue-500/20 rounded-lg backdrop-blur-sm border border-blue-400/20">
              <Brain className="h-8 w-8 text-blue-400" />
            </div>
            <span className="text-2xl font-bold tracking-tight">Mem Stack</span>
          </div>

          <div className="space-y-8">
            <h1 className="text-5xl font-extrabold leading-tight">
              {t('login.hero.title', 'Enterprise AI Memory Cloud')}
            </h1>
            <p className="text-lg text-slate-300 max-w-md">
              {t('login.hero.subtitle', 'Build intelligent applications with persistent memory')}
            </p>
          </div>

          <div className="text-sm text-slate-400 flex justify-between items-center">
            <span>{t('login.footer.rights', { year: new Date().getFullYear() })}</span>
          </div>
        </div>
      </div>

      {/* Right Side - Callback Status */}
      <div className="flex-1 flex flex-col justify-center py-12 px-4 sm:px-6 lg:px-20 xl:px-24 bg-white dark:bg-slate-900">
        <div className="mx-auto w-full max-w-sm lg:w-96">
          {/* Mobile Logo */}
          <div className="lg:hidden mb-8 text-center">
            <div className="flex items-center justify-center space-x-2 mb-2">
              <div className="p-2 bg-blue-600 rounded-lg">
                <Brain className="h-8 w-8 text-white" />
              </div>
              <span className="text-2xl font-bold text-gray-900 dark:text-white">Mem Stack</span>
            </div>
          </div>

          {/* Status Content */}
          <div className="text-center">
            {status === 'loading' && (
              <>
                <div className="mx-auto w-16 h-16 flex items-center justify-center mb-6 bg-blue-100 dark:bg-blue-900/30 rounded-full">
                  <Loader2 className="h-8 w-8 text-blue-600 dark:text-blue-400 animate-spin" />
                </div>
                <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
                  {t('login.oauth.processing', 'Completing sign in...')}
                </h2>
                <p className="text-gray-600 dark:text-slate-400">
                  {providerName
                    ? t('login.oauth.authenticatingWith', {
                        provider: providerName,
                        defaultValue: `Authenticating with ${providerName}...`,
                      })
                    : t('login.oauth.authenticating', 'Authenticating...')}
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
                  {t('login.oauth.redirecting', 'Redirecting you now...')}
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
                  onClick={handleRetry}
                  className="mt-6 inline-flex items-center px-6 py-3 border border-transparent rounded-xl shadow-sm text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors"
                >
                  {t('login.oauth.tryAgain', 'Try again')}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default OAuthCallback;
