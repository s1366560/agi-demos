/**
 * AppInitializer - Application initialization wrapper
 *
 * Ensures all required resources (i18n, theme, auth) are loaded
 * before rendering the application to prevent FOUC/FOUT.
 */

import React, { useState, useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { Brain } from 'lucide-react';

interface AppInitializerProps {
  children: React.ReactNode;
}

/**
 * Initial loading screen
 */
const InitialLoadingScreen: React.FC<{ timedOut?: boolean | undefined }> = ({
  timedOut = false,
}) => {
  const { t } = useTranslation();

  return (
    <div className="fixed inset-0 bg-background-light dark:bg-background-dark flex items-center justify-center z-50">
      <div className="flex flex-col items-center gap-4">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div className="bg-primary/10 p-3 rounded-xl">
            <Brain size={30} className="text-primary" />
          </div>
          <h1 className="text-slate-900 dark:text-white text-2xl font-bold">
            MemStack<span className="text-primary">.ai</span>
          </h1>
        </div>

        {/* Loading spinner */}
        <div
          className="flex items-center gap-2 text-slate-500"
          role="status"
          aria-live="polite"
        >
          <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin motion-reduce:animate-none" />
          <span className="text-sm">{t('common.loading')}</span>
        </div>

        {/* Timeout fallback: i18n may have failed to initialize */}
        {timedOut && (
          <div className="flex flex-col items-center gap-2 text-center" role="alert">
            <p className="text-sm text-slate-500">
              {t('common.initializationSlow', {
                defaultValue: 'Initialization is taking longer than expected.',
              })}
            </p>
            <button
              type="button"
              onClick={() => {
                window.location.reload();
              }}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            >
              {t('common.reload', { defaultValue: 'Reload' })}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * AppInitializer - Wraps the app and waits for initialization
 */
export const AppInitializer: React.FC<AppInitializerProps> = ({ children }) => {
  const [isReady, setIsReady] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const { i18n } = useTranslation();

  useEffect(() => {
    const checkReady = () => {
      if (i18n.isInitialized) {
        document.documentElement.classList.add('app-ready');
        setTimeout(() => {
          setIsReady(true);
        }, 50);
      }
    };

    checkReady();

    if (!isReady) {
      const timer = setInterval(checkReady, 50);
      return () => {
        clearInterval(timer);
      };
    }

    return undefined;
  }, [i18n.isInitialized, isReady]);

  // Surface a recovery path if initialization hangs (e.g. i18n never resolves).
  useEffect(() => {
    if (isReady) return undefined;
    const timeout = setTimeout(() => {
      setTimedOut(true);
    }, 15000);
    return () => {
      clearTimeout(timeout);
    };
  }, [isReady]);

  if (!isReady) {
    return <InitialLoadingScreen timedOut={timedOut} />;
  }

  return <>{children}</>;
};

export default AppInitializer;
