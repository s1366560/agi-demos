/**
 * AppInitializer - Application initialization wrapper
 * 
 * Ensures all required resources (i18n, theme, auth) are loaded
 * before rendering the application to prevent FOUC/FOUT.
 */

import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '../../stores/auth';

interface AppInitializerProps {
  children: React.ReactNode;
}

/**
 * Initial loading screen
 */
const InitialLoadingScreen: React.FC = () => {
  return (
    <div className="fixed inset-0 bg-background-light dark:bg-background-dark flex items-center justify-center z-50">
      <div className="flex flex-col items-center gap-4">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div className="bg-primary/10 p-3 rounded-xl">
            <span className="material-symbols-outlined text-primary text-3xl">memory</span>
          </div>
          <h1 className="text-slate-900 dark:text-white text-2xl font-bold">
            MemStack<span className="text-primary">.ai</span>
          </h1>
        </div>
        
        {/* Loading spinner */}
        <div className="flex items-center gap-2 text-slate-500">
          <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          <span className="text-sm">Loading...</span>
        </div>
      </div>
    </div>
  );
};

/**
 * AppInitializer - Wraps the app and waits for initialization
 */
export const AppInitializer: React.FC<AppInitializerProps> = ({ children }) => {
  const [isReady, setIsReady] = useState(false);
  const { i18n } = useTranslation();
  const { isLoading: isAuthLoading } = useAuthStore();

  useEffect(() => {
    // Check if i18n is initialized
    const checkReady = () => {
      const i18nReady = i18n.isInitialized;
      const authReady = !isAuthLoading;
      
      if (i18nReady && authReady) {
        // Add ready class to html for CSS transitions
        document.documentElement.classList.add('app-ready');
        
        // Small delay to ensure smooth transition
        setTimeout(() => {
          setIsReady(true);
        }, 50);
      }
    };

    checkReady();

    // If not ready, check again after a short delay
    if (!isReady) {
      const timer = setInterval(checkReady, 50);
      return () => clearInterval(timer);
    }
    
    return undefined;
  }, [i18n.isInitialized, isAuthLoading, isReady]);

  if (!isReady) {
    return <InitialLoadingScreen />;
  }

  return <>{children}</>;
};

export default AppInitializer;
