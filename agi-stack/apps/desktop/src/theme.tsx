import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from 'react';

export type ThemePreference = 'dark' | 'light' | 'system';
export type ResolvedTheme = 'dark' | 'light';

export const THEME_STORAGE_KEY = 'agistack.desktop.theme';
// The product shipped dark-only; existing users keep dark unless they opt out.
export const DEFAULT_THEME_PREFERENCE: ThemePreference = 'dark';

const SYSTEM_DARK_QUERY = '(prefers-color-scheme: dark)';

export function parseThemePreference(raw: string | null): ThemePreference {
  if (raw === 'dark' || raw === 'light' || raw === 'system') return raw;
  return DEFAULT_THEME_PREFERENCE;
}

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference === 'system') return systemPrefersDark ? 'dark' : 'light';
  return preference;
}

type ThemePreferenceContextValue = {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
};

const ThemePreferenceContext = createContext<ThemePreferenceContextValue | null>(null);

export function ThemePreferenceProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(() =>
    parseThemePreference(readStoredPreference()),
  );
  const [systemDark, setSystemDark] = useState<boolean>(() => readSystemPrefersDark());

  const setPreference = (nextPreference: ThemePreference) => {
    setPreferenceState(nextPreference);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, nextPreference);
    } catch {
      // The in-memory preference remains authoritative when storage is unavailable.
    }
  };

  useEffect(() => {
    if (preference !== 'system') return undefined;
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return undefined;
    }
    const media = window.matchMedia(SYSTEM_DARK_QUERY);
    setSystemDark(media.matches);
    const handleChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', handleChange);
      return () => media.removeEventListener('change', handleChange);
    }
    media.addListener(handleChange);
    return () => media.removeListener(handleChange);
  }, [preference]);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY) {
        setPreferenceState(parseThemePreference(event.newValue));
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  const resolved = resolveTheme(preference, systemDark);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  const value = useMemo<ThemePreferenceContextValue>(
    () => ({ preference, resolved, setPreference }),
    [preference, resolved],
  );

  return (
    <ThemePreferenceContext.Provider value={value}>{children}</ThemePreferenceContext.Provider>
  );
}

function readStoredPreference(): string | null {
  try {
    if (typeof window === 'undefined') return null;
    return window.localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    return null;
  }
}

function readSystemPrefersDark(): boolean {
  try {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true;
    return window.matchMedia(SYSTEM_DARK_QUERY).matches;
  } catch {
    return true;
  }
}

export function useThemePreference(): ThemePreferenceContextValue {
  const context = useContext(ThemePreferenceContext);
  if (!context) throw new Error('useThemePreference must be used inside ThemePreferenceProvider');
  return context;
}
