/**
 * DarkModeProvider - Theme management context
 *
 * Provides dark mode toggle functionality with localStorage persistence.
 * Uses class-based strategy for Tailwind CSS v4 dark mode.
 */

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

interface DarkModeContextValue {
  dark: boolean;
  setDark: (dark: boolean) => void;
  toggleDark: () => void;
}

const DarkModeContext = createContext<DarkModeContextValue | undefined>(undefined);

interface DarkModeProviderProps {
  children: ReactNode;
  /** Default dark mode value (default: false) */
  defaultDark?: boolean;
  /** Key for localStorage persistence (default: 'theme') */
  storageKey?: string;
}

/**
 * DarkModeProvider component
 *
 * Wraps the application to provide dark mode functionality.
 * Persists preference to localStorage.
 *
 * @example
 * <DarkModeProvider>
 *   <App />
 * </DarkModeProvider>
 */
export function DarkModeProvider({
  children,
  defaultDark = false,
  storageKey = 'theme',
}: DarkModeProviderProps) {
  const [dark, setDarkState] = useState(() => {
    // Initialize from localStorage or default
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem(storageKey);
      if (stored !== null) {
        return stored === 'dark';
      }
      // Check system preference
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return true;
      }
    }
    return defaultDark;
  });

  useEffect(() => {
    const root = document.documentElement;

    // Update document class for Tailwind dark mode
    if (dark) {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }

    // Persist to localStorage
    if (typeof window !== 'undefined') {
      localStorage.setItem(storageKey, dark ? 'dark' : 'light');
    }
  }, [dark, storageKey]);

  const setDark = (value: boolean) => {
    setDarkState(value);
  };

  const toggleDark = () => {
    setDarkState((prev) => !prev);
  };

  return (
    <DarkModeContext.Provider value={{ dark, setDark, toggleDark }}>
      {children}
    </DarkModeContext.Provider>
  );
}

/**
 * useDarkMode hook
 *
 * Access the dark mode context.
 *
 * @example
 * const { dark, toggleDark } = useDarkMode();
 *
 * @throws If used outside of DarkModeProvider
 */
export function useDarkMode(): DarkModeContextValue {
  const context = useContext(DarkModeContext);
  if (context === undefined) {
    throw new Error('useDarkMode must be used within a DarkModeProvider');
  }
  return context;
}

export default DarkModeProvider;
