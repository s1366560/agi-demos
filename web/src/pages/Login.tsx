import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal } from 'antd';
import { Eye, EyeOff, AlertCircle, Share2, Database, ShieldCheck } from 'lucide-react';

import { AuthSplitLayout } from '@/components/auth/AuthSplitLayout';
import { LanguageSwitcher } from '@/components/shared/ui/LanguageSwitcher';

import { useAuthStore } from '../stores/auth';

export const Login: React.FC = () => {
  const { t } = useTranslation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const passwordVisibilityLabel = showPassword
    ? t('login.form.hide_password')
    : t('login.form.show_password');

  const { login, error, isLoading: authLoading } = useAuthStore();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      await login(email, password);
      // Navigation is handled by the route guard
    } catch (_error) {
      // Error is handled in store
    } finally {
      setIsLoading(false);
    }
  };

  const handleForgotPassword = () => {
    Modal.info({
      title: t('login.form.forgot_password'),
      content: (
        <div className="space-y-2">
          <p>{t('login.form.forgot_unavailable')}</p>
          <p>
            {t(
              'login.form.forgot_sso_hint',
              'If your organization uses single sign-on (SSO), sign in with your identity provider instead.'
            )}
          </p>
        </div>
      ),
      centered: true,
    });
  };

  const handleDemoLogin = (type: 'admin' | 'user') => {
    if (type === 'admin') {
      setEmail('admin@memstack.ai');
      setPassword('adminpassword');
    } else {
      setEmail('user@memstack.ai');
      setPassword('userpassword');
    }
  };

  const heroFeatures = (
    <div className="grid grid-cols-2 gap-6 pt-8">
      <div className="flex items-start space-x-3">
        <div className="rounded-md border border-blue-400/20 bg-blue-400/10 p-2">
          <Database className="h-5 w-5 text-blue-400" />
        </div>
        <div>
          <h3 className="font-semibold text-white">{t('login.hero.features.memory.title')}</h3>
          <p className="text-sm text-slate-400 mt-1">{t('login.hero.features.memory.desc')}</p>
        </div>
      </div>
      <div className="flex items-start space-x-3">
        <div className="rounded-md border border-emerald-400/20 bg-emerald-400/10 p-2">
          <Share2 className="h-5 w-5 text-emerald-400" />
        </div>
        <div>
          <h3 className="font-semibold text-white">{t('login.hero.features.graph.title')}</h3>
          <p className="text-sm text-slate-400 mt-1">{t('login.hero.features.graph.desc')}</p>
        </div>
      </div>
    </div>
  );

  return (
    <AuthSplitLayout
      heroTitle={t('login.hero.title')}
      heroSubtitle={t('login.hero.subtitle')}
      copyright={t('login.footer.rights', { year: new Date().getFullYear() })}
      mobileTitle={t('login.mobile.title')}
      mobileSubtitle={t('login.mobile.subtitle')}
      heroExtra={heroFeatures}
      corner={<LanguageSwitcher />}
    >
      <div className="mb-8">
        <h2 className="text-3xl font-bold text-gray-900 dark:text-white">{t('login.title')}</h2>
        <p className="mt-2 text-sm text-gray-600 dark:text-slate-400">{t('login.subtitle')}</p>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-6 flex items-center p-4 bg-red-50 dark:bg-red-900/20 border border-red-100 dark:border-red-900/30 rounded-lg"
        >
          <AlertCircle className="h-5 w-5 text-red-500 dark:text-red-400 mr-3 flex-shrink-0" />
          <span className="text-sm text-red-700 dark:text-red-300">{error}</span>
        </div>
      )}

      <form
        onSubmit={(event) => {
          void handleSubmit(event);
        }}
        className="space-y-6"
        data-testid="login-form"
      >
        <div>
          <label
            htmlFor="email"
            className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1.5"
          >
            {t('login.email')}
          </label>
          <div className="relative">
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
              }}
              className="block w-full px-4 py-3 text-gray-900 dark:text-white border border-gray-200 dark:border-slate-700 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-[color,background-color,border-color,box-shadow,opacity,transform] bg-gray-50 dark:bg-slate-800 focus:bg-white dark:focus:bg-slate-900"
              placeholder={t('login.form.email_placeholder')}
              required
              disabled={isLoading || authLoading}
              data-testid="email-input"
            />
          </div>
        </div>

        <div>
          <div className="mb-1.5 space-y-1">
            <div className="flex items-center justify-between">
              <label
                htmlFor="password"
                className="block text-sm font-medium text-gray-700 dark:text-slate-300"
              >
                {t('login.password')}
              </label>
              <button
                type="button"
                onClick={handleForgotPassword}
                className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
              >
                {t('login.form.forgot_password')}
              </button>
            </div>
            <p
              id="password-help"
              className="text-xs leading-snug text-gray-500 dark:text-slate-400"
            >
              {t('login.form.forgot_unavailable')}
            </p>
          </div>
          <div className="relative">
            <input
              id="password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
              }}
              className="block w-full px-4 py-3 pr-10 text-gray-900 dark:text-white border border-gray-200 dark:border-slate-700 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-[color,background-color,border-color,box-shadow,opacity,transform] bg-gray-50 dark:bg-slate-800 focus:bg-white dark:focus:bg-slate-900"
              placeholder={t('login.form.password_placeholder')}
              required
              disabled={isLoading || authLoading}
              aria-describedby="password-help"
              data-testid="password-input"
            />
            <button
              type="button"
              onClick={() => {
                setShowPassword(!showPassword);
              }}
              className="absolute inset-y-0 right-0 pr-3 flex items-center"
              disabled={isLoading || authLoading}
              data-testid="toggle-password-visibility"
              aria-label={passwordVisibilityLabel}
              title={passwordVisibilityLabel}
            >
              {showPassword ? (
                <EyeOff className="h-5 w-5 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 transition-colors" />
              ) : (
                <Eye className="h-5 w-5 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 transition-colors" />
              )}
            </button>
          </div>
        </div>

        <button
          type="submit"
          className="w-full flex justify-center items-center py-3 px-4 border border-transparent rounded-lg shadow-sm text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-500 transition-[color,background-color,border-color,box-shadow,opacity,transform] disabled:opacity-50 disabled:cursor-not-allowed"
          disabled={isLoading || authLoading}
          data-testid="login-submit-button"
        >
          {isLoading || authLoading ? (
            <>
              <div className="animate-spin motion-reduce:animate-none rounded-full h-4 w-4 border-2 border-white border-t-transparent mr-2"></div>
              {t('login.loading')}
            </>
          ) : (
            t('login.submit')
          )}
        </button>
      </form>

      <div className="mt-8">
        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-gray-200 dark:border-slate-800" />
          </div>
          <div className="relative flex justify-center text-sm">
            <span className="px-4 bg-white dark:bg-slate-900 text-gray-500 dark:text-slate-500">
              {t('login.form.or')}
            </span>
          </div>
        </div>

        <div className="mt-8 text-center">
          <p className="text-sm text-gray-600 dark:text-slate-400">
            {t('login.form.register_unavailable')}
          </p>
        </div>
      </div>

      {/* Demo Credentials Hint — dev-only so production never exposes seed accounts. */}
      {import.meta.env.DEV && (
        <div className="mt-10 p-5 bg-blue-50 dark:bg-blue-900/10 rounded-lg border border-blue-100 dark:border-blue-900/30">
          <div className="flex items-center space-x-2 mb-3">
            <ShieldCheck className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            <h3 className="text-sm font-semibold text-blue-900 dark:text-blue-200">
              {t('login.demo.title')}
            </h3>
          </div>
          <div className="space-y-2 text-sm">
            <button
              type="button"
              onClick={() => {
                handleDemoLogin('admin');
              }}
              className="flex w-full flex-col gap-1 rounded bg-blue-100/50 p-2 text-left text-blue-800 transition-colors hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:bg-blue-900/30 dark:text-blue-300 dark:hover:bg-blue-900/50"
              aria-label={t('login.demo.adminAria')}
            >
              <span className="font-medium leading-tight">{t('login.demo.admin')}</span>
              <span className="break-all font-mono text-xs leading-snug">
                admin@memstack.ai / adminpassword
              </span>
            </button>
            <button
              type="button"
              onClick={() => {
                handleDemoLogin('user');
              }}
              className="flex w-full flex-col gap-1 rounded bg-blue-100/50 p-2 text-left text-blue-800 transition-colors hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:bg-blue-900/30 dark:text-blue-300 dark:hover:bg-blue-900/50"
              aria-label={t('login.demo.userAria')}
            >
              <span className="font-medium leading-tight">{t('login.demo.user')}</span>
              <span className="break-all font-mono text-xs leading-snug">
                user@memstack.ai / userpassword
              </span>
            </button>
          </div>
        </div>
      )}
    </AuthSplitLayout>
  );
};
