import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

type Theme = 'light' | 'dark' | 'system' | 'high-contrast';

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  computedTheme: 'light' | 'dark'; // The actual theme being applied
}

export const useThemeStore = create<ThemeState>()(
  devtools(
    persist(
      (set) => ({
        theme: 'system',
        computedTheme: 'light', // Default initial
        setTheme: (theme) => {
          set({ theme });
          updateDocumentClass(theme);
        },
      }),
      {
        name: 'theme-storage',
        onRehydrateStorage: () => (state) => {
          if (state) {
            updateDocumentClass(state.theme);
          }
        },
      }
    ),
    {
      name: 'ThemeStore',
      enabled: import.meta.env.DEV,
    }
  )
);

const updateDocumentClass = (theme: Theme) => {
  const root = window.document.documentElement;

  if (theme === 'high-contrast') {
    root.classList.add('dark', 'high-contrast');
    useThemeStore.setState({ computedTheme: 'dark' });
    return;
  }

  root.classList.remove('high-contrast');
  const isDark =
    theme === 'dark' ||
    (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);

  if (isDark) {
    root.classList.add('dark');
    useThemeStore.setState({ computedTheme: 'dark' });
  } else {
    root.classList.remove('dark');
    useThemeStore.setState({ computedTheme: 'light' });
  }
};

// Listen for system changes if theme is 'system'
if (typeof window !== 'undefined') {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    const { theme } = useThemeStore.getState();
    if (theme === 'system') {
      updateDocumentClass('system');
    }
  });
}
